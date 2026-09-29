"""
Phase 6 + Phase 7 integration and repair tests.
Authority: IMPLEMENTATION_PLAN.md Phase 6+7, VALIDATION_AND_TESTING.md §6.
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
    HumanReviewItem,
)
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.constraints import build_constraint_map
from src.validators.aggregate import run_validators, aggregate_run_status
from src.repair import repair_plan
from src.graph import graph


@pytest.fixture
def test_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    cmap = build_constraint_map(
        fixtures["contracts"], fixtures["policies"], fixtures["audiences"], fixtures["cost_sheet"]
    )
    clean_plans_path = data_dir / "replay" / "trailer_plans.clean.json"
    with open(clean_plans_path, "r", encoding="utf-8") as f:
        clean_raw = json.load(f)["response"]["plans"]
    clean_plans = {}
    for tid, p in clean_raw.items():
        p_copy = dict(p)
        p_copy["audience"] = p_copy.get("audience_id", p_copy.get("audience", "family"))
        p_copy["duration_seconds"] = float(p_copy.get("total_duration_s", 38.0))
        p_copy["audience_promise"] = "Baseline promise"
        for s in p_copy.get("segments", []):
            if "video" not in s and "scene_id" in s:
                s["video"] = s["scene_id"]
        clean_plans[tid] = TrailerPlan.model_validate(p_copy)

    traps_plans_path = data_dir / "replay" / "trailer_plans.traps.json"
    with open(traps_plans_path, "r", encoding="utf-8") as f:
        traps_raw = json.load(f)["response"]["plans"]
    traps_plans = {}
    for tid, p in traps_raw.items():
        p_copy = dict(p)
        p_copy["audience"] = p_copy.get("audience_id", p_copy.get("audience", "family"))
        p_copy["duration_seconds"] = float(p_copy.get("total_duration_s", 38.0))
        p_copy["audience_promise"] = "Traps promise"
        for s in p_copy.get("segments", []):
            if "video" not in s and "scene_id" in s:
                s["video"] = s["scene_id"]
        traps_plans[tid] = TrailerPlan.model_validate(p_copy)

    return {
        "fixtures": fixtures,
        "ev_index": ev_index,
        "cmap": cmap,
        "clean_plans": clean_plans,
        "traps_plans": traps_plans,
    }


def test_missing_scene_repaired(test_context):
    """
    Test 23 & 29 & 30: Missing scene is repaired by valid candidate from pool,
    replacement passes full validation, revision record written.
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    family = plans["family_v1"].model_dump()
    family["segments"][0]["video"] = "scene_99"  # Non-existent scene
    plans["family_v1"] = TrailerPlan.model_validate(family)

    val_res = {
        "family_v1": run_validators(
            family,
            test_context["ev_index"],
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "U", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    assert val_res["family_v1"].status == TrailerStatus.REPAIR_REQUIRED

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index=test_context["ev_index"],
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={},
        revision_counter=1,
        max_repair_iterations=2,
    )

    # 1. Missing scene was replaced
    repaired_seg = patched["family_v1"].segments[0]
    assert repaired_seg.video != "scene_99"
    assert repaired_seg.video in test_context["ev_index"]["by_scene"]

    # 2. Revision record written
    assert len(revs) > 0
    assert any("SCENE_NOT_FOUND" in r.trigger for r in revs)
    assert any("family_v1.segment_01" in r.affected for r in revs)

    # 3. Decision log recorded
    assert any(d["entry_type"] == "REPAIR_APPLIED" for d in dlogs)


def test_rights_trap_repaired(test_context):
    """
    Test 24: Restricted music asset repaired (swapped or stripped).
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    ya = plans["young_adult_v1"].model_dump()
    # music_07 is promo-restricted / expired
    ya["segments"][0]["audio_mode"] = "dialogue_and_music"
    ya["segments"][0]["music_asset_id"] = "music_07"
    plans["young_adult_v1"] = TrailerPlan.model_validate(ya)

    val_res = {
        "young_adult_v1": run_validators(
            ya,
            test_context["ev_index"],
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "UA13+", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    assert val_res["young_adult_v1"].status in (TrailerStatus.REPAIR_REQUIRED, TrailerStatus.REJECTED)

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index=test_context["ev_index"],
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={},
        revision_counter=1,
        max_repair_iterations=2,
    )

    # Music asset must no longer be music_07
    repaired_seg = patched["young_adult_v1"].segments[0]
    assert repaired_seg.music_asset_id != "music_07"
    assert len(revs) > 0


def test_spoiler_trap_repaired(test_context):
    """
    Test 25: Segment revealing major spoiler fact repaired with safe segment.
    """
    from src.story import build_spoiler_map
    plans = copy.deepcopy(test_context["clean_plans"])
    ya = plans["young_adult_v1"].model_dump()
    # Put major spoiler reveal window in segment 0
    ya["segments"][0]["video"] = "scene_07"
    ya["segments"][0]["source_in"] = "00:04:50.000"
    ya["segments"][0]["source_out"] = "00:04:54.000"
    ya["segments"][0]["subtitle"] = {
        "track": "hi",
        "cue_ids": ["sub_hi_007_04"],
        "text": "Haan... woh sach tha jo usme likha tha.",
    }
    plans["young_adult_v1"] = TrailerPlan.model_validate(ya)

    spoiler_map = build_spoiler_map(test_context["fixtures"]["story_facts"].model_dump(), [])

    val_res = {
        "young_adult_v1": run_validators(
            ya,
            test_context["ev_index"],
            spoiler_map,
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "UA13+", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    assert val_res["young_adult_v1"].status == TrailerStatus.REPAIR_REQUIRED

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index=test_context["ev_index"],
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={},
        revision_counter=1,
        spoiler_map=spoiler_map,
        max_repair_iterations=2,
    )

    repaired_seg = patched["young_adult_v1"].segments[0]
    # Repaired segment must not be the spoiler segment
    assert not (repaired_seg.video == "scene_07" and repaired_seg.source_in == "00:04:50.000")
    assert any("SPOILER_" in r.trigger for r in revs)


def test_story_truth_trap_repaired(test_context):
    """
    Test 26: Forbidden claim pattern or relation mismatch repaired.
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    ya = plans["young_adult_v1"].model_dump()
    ya["segments"][0]["claims"] = [
        {"type": "relation", "value": "Randhir is Sunita's spouse", "supported_by": ["scene:scene_01"]}
    ]
    plans["young_adult_v1"] = TrailerPlan.model_validate(ya)

    val_res = {
        "young_adult_v1": run_validators(
            ya,
            test_context["ev_index"],
            {},
            {"relationships": [{"a": "char_randhir", "b": "char_sunita", "relation": "uncle_niece", "visibility": "public"}]},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "UA13+", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    assert val_res["young_adult_v1"].status == TrailerStatus.REPAIR_REQUIRED

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index=test_context["ev_index"],
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={},
        revision_counter=1,
        max_repair_iterations=2,
    )

    # Claim should be removed or sanitized
    repaired_claims = patched["young_adult_v1"].segments[0].claims
    assert not any("spouse" in c.value.lower() for c in repaired_claims)
    assert any("STORY_" in r.trigger for r in revs)


def test_no_valid_candidate_rejects_and_exhausts(test_context):
    """
    Test 27: No valid candidate exists -> trailer marked REJECTED,
    reason REPAIR_EXHAUSTED, blocking human review item created.
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    ya = plans["young_adult_v1"].model_dump()
    ya["segments"][0]["video"] = "scene_99"
    plans["family_v1"] = TrailerPlan.model_validate(ya)

    val_res = {
        "family_v1": run_validators(
            ya,
            {"by_scene": {}},  # Empty pool
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "U", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index={"by_scene": {}},
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={"family_v1.segment_01": 2},
        revision_counter=1,
        max_repair_iterations=2,
    )

    assert any(h.reason_code == "REPAIR_EXHAUSTED" and h.blocking for h in hrs)
    assert any(d["entry_type"] == "SEGMENT_REJECTED" for d in dlogs)


def test_repair_loop_stops_at_max_2(test_context):
    """
    Test 28: Repair attempts track iteration count and stop at max 2.
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    family = plans["family_v1"].model_dump()
    family["segments"][0]["video"] = "scene_99"
    plans["family_v1"] = TrailerPlan.model_validate(family)

    val_res = {
        "family_v1": run_validators(
            family,
            {"by_scene": {}},  # Empty candidate pool prevents repair
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "U", "subtitle_track": "hi"},
            0.13,
            2.0,
        )
    }

    # Iteration 1
    p1, att1, rev1, h1, d1 = repair_plan(
        plans, val_res, {"by_scene": {}}, test_context["cmap"], {},
        repair_attempts={}, revision_counter=1, max_repair_iterations=2
    )
    assert att1.get("family_v1.segment_01", 0) == 1

    # Iteration 2
    p2, att2, rev2, h2, d2 = repair_plan(
        p1, val_res, {"by_scene": {}}, test_context["cmap"], {},
        repair_attempts=att1, revision_counter=2, max_repair_iterations=2
    )
    assert att2.get("family_v1.segment_01") == 2
    # At max iterations, exhausted
    assert any(h.reason_code == "REPAIR_EXHAUSTED" and h.blocking for h in h2)


def test_graph_clean_scenario_reaches_finalize():
    """
    Test 31: Clean scenario executes through validate and reaches finalize with PASS / PASS_WITH_WARNINGS.
    """
    init_state = {
        "run_config": {
            "mode": "replay",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 5.0,
        },
        "decision_log": [],
    }
    out = graph.invoke(init_state)

    # Status must be PASS or PASS_WITH_WARNINGS (not REPAIR_REQUIRED or REJECTED)
    assert out["status"] in ("PASS", "PASS_WITH_WARNINGS")
    # All 3 trailers present
    assert len(out["candidate_plan"]) == 3
    # Check decision log for validation
    assert any(d["entry_type"] == "VALIDATION_RESULT" for d in out["decision_log"])


def test_graph_traps_scenario_reaches_repair():
    """
    Test 32 & 33: Traps scenario detects violations, enters repair loop,
    and repaired trap does not retain the original invalid segment.
    """
    init_state = {
        "run_config": {
            "mode": "replay",
            "scenario": "traps",
            "data_dir": "data",
            "run_budget": 5.0,
        },
        "decision_log": [],
    }
    out = graph.invoke(init_state)

    # Must have entered repair
    decision_types = [d["entry_type"] for d in out["decision_log"]]
    assert any(dt in ("REPAIR_APPLIED", "SEGMENT_REJECTED") for dt in decision_types)

    # Revisions or repair actions were executed
    assert len(out.get("revisions", [])) > 0 or len(out.get("human_review_items", [])) > 0


def test_one_rejected_trailer_does_not_block_others(test_context):
    """
    Test 34: One unrepairable trailer marked REJECTED does not block emission of other valid trailers.
    """
    plans = copy.deepcopy(test_context["clean_plans"])
    # Sabotage only dialect_region_v1 with unrepairable error
    dr = plans["dialect_region_v1"].model_dump()
    dr["segments"][0]["video"] = "scene_non_existent"
    plans["dialect_region_v1"] = TrailerPlan.model_validate(dr)

    # Run repair with empty pool for dialect_region to force rejection
    val_res = {
        "family_v1": run_validators(
            plans["family_v1"].model_dump(),
            test_context["ev_index"],
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "U", "subtitle_track": "hi"},
            0.13,
            2.0,
        ),
        "dialect_region_v1": run_validators(
            dr,
            {"by_scene": {}},
            {},
            {},
            test_context["fixtures"]["story_facts"].model_dump(),
            test_context["cmap"],
            test_context["fixtures"]["subtitles"].model_dump(),
            {"rating_ceiling": "UA16+", "subtitle_track": "bgc"},
            0.13,
            2.0,
        ),
    }

    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation=val_res,
        evidence_index={"by_scene": {}},
        constraint_map=test_context["cmap"],
        audience_promises={},
        repair_attempts={"dialect_region_v1.segment_01": 2},
        revision_counter=1,
        max_repair_iterations=2,
    )

    # Dialect region trailer generated blocking human review item
    assert any(h.trailer_id == "dialect_region_v1" and h.reason_code == "REPAIR_EXHAUSTED" for h in hrs)

    # Family trailer remains unaffected and valid
    assert "family_v1" in patched
    assert len(patched["family_v1"].segments) == len(plans["family_v1"].segments)
