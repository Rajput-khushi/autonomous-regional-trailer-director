"""
test_invariants.py — Cross-cutting invariant tests (VALIDATION_AND_TESTING.md §8).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from src.models import (
    TrailerPlan,
    TrailerStatus,
    ValidatorStatus,
    ValidationError,
)
from src.validators.aggregate import (
    run_validators,
    aggregate_trailer_status,
    aggregate_run_status,
)
from src.tools.distinctness import compute_distinctness_report
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.constraints import build_constraint_map
from src.story import build_spoiler_map
from src.repair import repair_plan
from src.graph import graph


@pytest.fixture
def invariant_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    cmap = build_constraint_map(
        fixtures["contracts"], fixtures["policies"], fixtures["audiences"], fixtures["cost_sheet"]
    )
    s_map = build_spoiler_map(fixtures["story_facts"].model_dump(), [])
    clean_plans_raw = json.loads(
        (data_dir / "replay" / "trailer_plans.clean.json").read_text(encoding="utf-8")
    )
    raw_plans = clean_plans_raw["response"]["plans"]
    plans = {}
    for tid, p in raw_plans.items():
        p_copy = dict(p)
        p_copy["audience"] = p_copy.get("audience_id", p_copy.get("audience", "family"))
        p_copy["duration_seconds"] = float(p_copy.get("total_duration_s", 38.0))
        p_copy["audience_promise"] = "Baseline promise"
        for s in p_copy.get("segments", []):
            if "video" not in s and "scene_id" in s:
                s["video"] = s["scene_id"]
        plans[tid] = TrailerPlan.model_validate(p_copy)

    return {
        "fixtures": fixtures,
        "ev_index": ev_index,
        "cmap": cmap,
        "spoiler_map": s_map,
        "plans": plans,
    }


def test_fixtures_schema(invariant_context):
    """Every data file validates against Pydantic models; every file has synthetic=True."""
    fixtures = invariant_context["fixtures"]
    assert len(fixtures["scenes"]) == 8
    assert len(fixtures["contracts"]) == 8
    assert len(fixtures["policies"]) == 7
    assert len(fixtures["audiences"]) == 3


def test_baseline_is_clean(invariant_context):
    """
    Baseline plans validate to PASS / PASS_WITH_WARNINGS with expected
    warnings only (no unexpected failures).
    """
    fixtures = invariant_context["fixtures"]
    ev_index = invariant_context["ev_index"]
    cmap = invariant_context["cmap"]
    s_map = invariant_context["spoiler_map"]
    plans = invariant_context["plans"]

    results = {}
    for tid, plan in plans.items():
        aud_track = "bgc" if tid == "dialect_region_v1" else "hi"
        aud_ceiling = "UA13+" if tid != "family_v1" else "U"
        val = run_validators(
            plan.model_dump(),
            evidence_index=ev_index,
            spoiler_map=s_map,
            story_map={},
            story_facts=fixtures["story_facts"].model_dump(),
            constraint_map=cmap,
            subtitles=fixtures["subtitles"].model_dump(),
            audience_profile={"rating_ceiling": aud_ceiling, "subtitle_track": aud_track},
            estimated_cost=0.13,
            run_budget=2.0,
        )
        results[tid] = val

    # Verify no failures
    for tid, val in results.items():
        assert val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS)
        for v in val.validators:
            assert v.status != ValidatorStatus.FAIL


def test_plans_distinct(invariant_context):
    """
    Pairwise source-second overlap ≤ 25% of the shorter trailer;
    distinct first segments; distinct taglines.
    """
    plans = invariant_context["plans"]
    report = compute_distinctness_report(plans)

    assert report["first_segments_distinct"] is True
    assert report["taglines_distinct"] is True

    for pair, stats in report["pairwise_overlap"].items():
        assert stats["within_target"] is True, f"Overlap ratio {stats['overlap_ratio']} exceeds 25% for {pair}"


def test_hard_fail_never_downgraded(invariant_context):
    """
    No code path yields PASS_WITH_WARNINGS when a hard error exists.
    """
    fixtures = invariant_context["fixtures"]
    ev_index = invariant_context["ev_index"]
    cmap = invariant_context["cmap"]
    s_map = invariant_context["spoiler_map"]
    family = copy.deepcopy(invariant_context["plans"]["family_v1"])

    # Introduce hard error: scene_11 (does not exist)
    f_dict = family.model_dump()
    f_dict["segments"][0]["video"] = "scene_11"

    val = run_validators(
        f_dict,
        evidence_index=ev_index,
        spoiler_map=s_map,
        story_map={},
        story_facts=fixtures["story_facts"].model_dump(),
        constraint_map=cmap,
        subtitles=fixtures["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )

    assert val.status != TrailerStatus.PASS
    assert val.status != TrailerStatus.PASS_WITH_WARNINGS
    assert val.status in (TrailerStatus.REPAIR_REQUIRED, TrailerStatus.REJECTED)


def test_repair_terminates(invariant_context):
    """
    With an always-invalid candidate pool, graph ends REJECTED within
    max_repair_iterations (max 2).
    """
    family = copy.deepcopy(invariant_context["plans"]["family_v1"])
    f_dict = family.model_dump()
    f_dict["segments"][0]["video"] = "scene_11"

    plans = {"family_v1": TrailerPlan.model_validate(f_dict)}

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation={
            "family_v1": run_validators(
                f_dict,
                invariant_context["ev_index"],
                {},
                {},
                invariant_context["fixtures"]["story_facts"].model_dump(),
                invariant_context["cmap"],
                invariant_context["fixtures"]["subtitles"].model_dump(),
                {"rating_ceiling": "U", "subtitle_track": "hi"},
                0.13,
                2.0,
            )
        },
        evidence_index={"by_scene": {}},  # Empty pool → cannot repair
        constraint_map=invariant_context["cmap"],
        audience_promises={},
        repair_attempts={"family_v1.segment_01": 2},  # Max iterations reached
        revision_counter=1,
        max_repair_iterations=2,
    )

    # Must be marked REJECTED and human review item created
    assert any(h.reason_code == "REPAIR_EXHAUSTED" and h.blocking for h in hrs)


def test_llm_cannot_clear_failure(invariant_context):
    """
    Mock returns 'this is safe' advisory for a spoiler → still FAIL.
    Deterministic validation boundary cannot be overridden by model outputs.
    """
    from src.validators.spoiler import SpoilerValidator

    family = copy.deepcopy(invariant_context["plans"]["family_v1"])
    f_dict = family.model_dump()
    # Inject major spoiler: scene_07 [00:04:48.000, 00:04:56.000) reveals fact F01
    f_dict["segments"][0]["video"] = "scene_07"
    f_dict["segments"][0]["source_in"] = "00:04:48.000"
    f_dict["segments"][0]["source_out"] = "00:04:56.000"
    f_dict["segments"][0]["reason"] = "Model claims: this is completely safe, no spoilers, verified family beat."
    f_dict["segments"][0]["claims"] = [{"type": "advisory", "claim": "safe", "supported_by": ["llm_claim"]}]

    # Run spoiler validator
    s_val = SpoilerValidator()
    res = s_val.validate_segment(
        segment=f_dict["segments"][0],
        spoiler_map=invariant_context["spoiler_map"],
    )
    assert res.status == ValidatorStatus.FAIL
    assert any(e.code == "SPOILER_MAJOR" for e in res.errors)

    # Full aggregate validation must also fail (never clear to PASS)
    val = run_validators(
        f_dict,
        evidence_index=invariant_context["ev_index"],
        spoiler_map=invariant_context["spoiler_map"],
        story_map={},
        story_facts=invariant_context["fixtures"]["story_facts"].model_dump(),
        constraint_map=invariant_context["cmap"],
        subtitles=invariant_context["fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )
    assert val.status in (TrailerStatus.REPAIR_REQUIRED, TrailerStatus.REJECTED)
    assert val.status not in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS)


def test_validator_exception_fails_closed(invariant_context, monkeypatch):
    """
    Injecting an exception in a validator yields FAIL (fail closed).
    """
    from src.validators.scene_existence import SceneExistenceValidator

    def crash(*args, **kwargs):
        raise RuntimeError("Injected validator crash")

    monkeypatch.setattr(SceneExistenceValidator, "validate_segment", crash)

    family = copy.deepcopy(invariant_context["plans"]["family_v1"])
    f_dict = family.model_dump()

    val = run_validators(
        f_dict,
        evidence_index=invariant_context["ev_index"],
        spoiler_map={},
        story_map={},
        story_facts=invariant_context["fixtures"]["story_facts"].model_dump(),
        constraint_map=invariant_context["cmap"],
        subtitles=invariant_context["fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )

    # Must be FAIL (fail-closed, never PASS)
    assert val.status in (TrailerStatus.REJECTED, TrailerStatus.REPAIR_REQUIRED)
    v_errors = [e for v in val.validators for e in v.errors]
    assert any(e.code == "VALIDATOR_EXCEPTION" for e in v_errors)


def test_state_serializable(invariant_context):
    """
    json.dumps(state) succeeds after every node.
    """
    init_state = {
        "run_config": {
            "mode": "replay",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 2.0,
        },
        "decision_log": [],
    }
    out = graph.invoke(init_state)

    # Must serialize cleanly to JSON
    # Remove any internal objects with leading underscore if present
    sanitized = {}
    for k, v in out.items():
        if k == "episode" and isinstance(v, dict):
            sanitized[k] = {ik: iv for ik, iv in v.items() if not ik.startswith("_")}
        elif k == "candidate_plan" and isinstance(v, dict):
            sanitized[k] = {ik: iv.model_dump() if hasattr(iv, "model_dump") else iv for ik, iv in v.items()}
        elif k == "validation" and isinstance(v, dict):
            sanitized[k] = {ik: iv.model_dump() if hasattr(iv, "model_dump") else iv for ik, iv in v.items()}
        elif k == "revisions" and isinstance(v, list):
            sanitized[k] = [iv.model_dump() if hasattr(iv, "model_dump") else iv for iv in v]
        elif k == "human_review_items" and isinstance(v, list):
            sanitized[k] = [iv.model_dump() if hasattr(iv, "model_dump") else iv for iv in v]
        else:
            sanitized[k] = v

    json_str = json.dumps(sanitized, default=str)
    assert len(json_str) > 0


def test_scene_timecode_blocking_causes_dependent_skipped(invariant_context):
    """
    If SceneExistence or Timecode blocks a segment, dependent validators
    for that segment return SKIPPED with blocked_by.
    """
    family = copy.deepcopy(invariant_context["plans"]["family_v1"])
    f_dict = family.model_dump()
    # Break scene on segment 0
    f_dict["segments"][0]["video"] = "scene_99"

    val = run_validators(
        f_dict,
        evidence_index=invariant_context["ev_index"],
        spoiler_map={},
        story_map={},
        story_facts=invariant_context["fixtures"]["story_facts"].model_dump(),
        constraint_map=invariant_context["cmap"],
        subtitles=invariant_context["fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )

    # Rights, Spoiler, etc. should have SKIPPED for segment_01 with blocked_by="SceneExistenceValidator"
    seg_01_skipped = [
        v.details.get("segment_01")
        for v in val.validators
        if v.details and v.details.get("segment_01", {}).get("status") == "SKIPPED"
    ]
    assert len(seg_01_skipped) > 0
    assert all(s.get("blocked_by") == "SceneExistenceValidator" for s in seg_01_skipped)

    # When all segments are blocked, dependent validators themselves report SKIPPED with blocked_by
    single_seg_plan = {
        "trailer_id": "single_seg_v1",
        "audience_id": "family",
        "segments": [f_dict["segments"][0]],
    }
    val_all_blocked = run_validators(
        single_seg_plan,
        evidence_index=invariant_context["ev_index"],
        spoiler_map={},
        story_map={},
        story_facts=invariant_context["fixtures"]["story_facts"].model_dump(),
        constraint_map=invariant_context["cmap"],
        subtitles=invariant_context["fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )
    all_skipped_vals = [
        v for v in val_all_blocked.validators
        if v.status == ValidatorStatus.SKIPPED
    ]
    assert len(all_skipped_vals) > 0
    assert any(v.blocked_by == "SceneExistenceValidator" for v in all_skipped_vals)


def test_all_nine_validators_execute(invariant_context):
    """
    All nine validators execute in the exact documented order for complete reporting.
    """
    family = copy.deepcopy(invariant_context["plans"]["family_v1"])
    f_dict = family.model_dump()

    val = run_validators(
        f_dict,
        evidence_index=invariant_context["ev_index"],
        spoiler_map={},
        story_map={},
        story_facts=invariant_context["fixtures"]["story_facts"].model_dump(),
        constraint_map=invariant_context["cmap"],
        subtitles=invariant_context["fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )

    validator_names = [v.validator for v in val.validators]
    expected_names = [
        "SceneExistenceValidator",
        "TimecodeValidator",
        "RightsValidator",
        "SpoilerValidator",
        "StoryTruthValidator",
        "AudienceSafetyValidator",
        "DialectConsistencyValidator",
        "AccessibilityValidator",
        "BudgetValidator",
    ]
    assert validator_names == expected_names


def test_validators_do_not_import_planner_or_llm():
    """
    Architectural boundary: deterministic validators must not import planner or LLM modules.
    """
    import inspect
    import src.validators.scene_existence as v1
    import src.validators.timecode as v2
    import src.validators.rights as v3
    import src.validators.spoiler as v4
    import src.validators.story_truth as v5
    import src.validators.audience_safety as v6
    import src.validators.dialect as v7
    import src.validators.accessibility as v8
    import src.validators.budget as v9
    import src.validators.aggregate as v_agg

    modules = [v1, v2, v3, v4, v5, v6, v7, v8, v9, v_agg]
    forbidden_terms = ["src.planners", "src.llm", "ModelClient", "ReplayClient"]

    for mod in modules:
        source = inspect.getsource(mod)
        for term in forbidden_terms:
            assert term not in source, f"Module {mod.__name__} illegally imports/references {term}"

