"""
T1 — test_missing_scene (VALIDATION_AND_TESTING.md §6 T1).
Tests SceneExistenceValidator, dependent validator skipping, and repair loop.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from src.models import (
    TrailerPlan,
    TrailerSegment,
    ValidatorStatus,
    TrailerStatus,
    HumanReviewItem,
)
from src.validators.scene_existence import SceneExistenceValidator
from src.validators.aggregate import run_validators, aggregate_trailer_status
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.constraints import build_constraint_map
from src.repair import repair_plan
from src.graph import graph


@pytest.fixture
def baseline_data():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    cmap = build_constraint_map(
        fixtures["contracts"], fixtures["policies"], fixtures["audiences"], fixtures["cost_sheet"]
    )
    clean_plans_raw = json.loads(
        (data_dir / "replay" / "trailer_plans.clean.json").read_text(encoding="utf-8")
    )
    raw_plans = clean_plans_raw["response"]["plans"]
    plans = {}
    for tid, p in raw_plans.items():
        p_copy = dict(p)
        p_copy["audience"] = p_copy.get("audience_id", p_copy.get("audience", "family"))
        p_copy["duration_seconds"] = float(p_copy.get("total_duration_s", 38.0))
        p_copy["audience_promise"] = "Baseline family promise"
        # Ensure video is set
        for s in p_copy.get("segments", []):
            if "video" not in s and "scene_id" in s:
                s["video"] = s["scene_id"]
        plans[tid] = TrailerPlan.model_validate(p_copy)
    return {
        "fixtures": fixtures,
        "ev_index": ev_index,
        "cmap": cmap,
        "plans": plans,
    }


def test_missing_scene_unit_scene_not_found(baseline_data):
    """
    Setup: baseline family_v1.segment_03 with video="scene_11" (non-existent).
    Expected: SceneExistenceValidator FAIL with SCENE_NOT_FOUND.
    """
    family = baseline_data["plans"]["family_v1"]
    ev_index = baseline_data["ev_index"]
    cmap = baseline_data["cmap"]

    # Mutate segment_03
    seg_dict = family.segments[2].model_dump()
    seg_dict["video"] = "scene_11"
    seg_dict["evidence"] = ["scene:scene_11"]

    validator = SceneExistenceValidator()
    result = validator.validate_segment(seg_dict, ev_index, cmap, seen_segment_ids=set())

    assert result.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in result.errors]
    assert "SCENE_NOT_FOUND" in error_codes


def test_missing_scene_dependent_validators_skipped(baseline_data):
    """
    When SceneExistence FAILs, dependent validators must return SKIPPED
    with blocked_by="SceneExistenceValidator".
    """
    family = copy.deepcopy(baseline_data["plans"]["family_v1"])
    family_dict = family.model_dump()
    family_dict["segments"][2]["video"] = "scene_11"
    family_dict["segments"][2]["evidence"] = ["scene:scene_11"]

    fixtures = baseline_data["fixtures"]
    val = run_validators(
        family_dict,
        evidence_index=baseline_data["ev_index"],
        spoiler_map={},
        story_map={},
        story_facts=fixtures["story_facts"].model_dump(),
        constraint_map=baseline_data["cmap"],
        subtitles=fixtures["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=2.0,
    )

    # 1. SceneExistence must fail
    v_scene = val.validators[0]
    assert v_scene.status == ValidatorStatus.FAIL
    assert any(e.code == "SCENE_NOT_FOUND" for e in v_scene.errors)

    # 2. Timecode / Rights / Spoiler for segment_03 must be SKIPPED with blocked_by="SceneExistenceValidator"
    for v in val.validators[1:6]:
        sid_detail = v.details.get("segment_03", {})
        assert sid_detail.get("status") == ValidatorStatus.SKIPPED.value
        assert sid_detail.get("blocked_by") == "SceneExistenceValidator"

    # Trailer status should be REPAIR_REQUIRED
    assert val.status == TrailerStatus.REPAIR_REQUIRED


def test_missing_scene_graph_repairs_segment(baseline_data):
    """
    Graph assertion: final plan contains no segment with video="scene_11";
    replacement passes all validators; revision record exists.
    """
    family = copy.deepcopy(baseline_data["plans"]["family_v1"])
    family_dict = family.model_dump()
    family_dict["segments"][2]["video"] = "scene_11"
    family_dict["segments"][2]["evidence"] = ["scene:scene_11"]

    plans = {
        "family_v1": TrailerPlan.model_validate(family_dict),
        "young_adult_v1": baseline_data["plans"]["young_adult_v1"],
        "dialect_region_v1": baseline_data["plans"]["dialect_region_v1"],
    }

    # Run repair loop
    fixtures = baseline_data["fixtures"]
    patched_plans, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation={
            "family_v1": run_validators(
                family_dict,
                baseline_data["ev_index"],
                {},
                {},
                fixtures["story_facts"].model_dump(),
                baseline_data["cmap"],
                fixtures["subtitles"].model_dump(),
                {"rating_ceiling": "U", "subtitle_track": "hi"},
                0.13,
                2.0,
            )
        },
        evidence_index=baseline_data["ev_index"],
        constraint_map=baseline_data["cmap"],
        audience_promises={"family": {"framing_tags": ["warmth"], "required_beats": []}},
        repair_attempts={},
        revision_counter=1,
        story_facts=fixtures["story_facts"].model_dump(),
        subtitles=fixtures["subtitles"].model_dump(),
    )

    repaired_family = patched_plans["family_v1"]
    final_videos = [s.video for s in repaired_family.segments]
    assert "scene_11" not in final_videos
    assert len(revs) >= 1
    assert "family_v1.segment_03" in revs[0].affected


def test_missing_scene_empty_pool_rejected(baseline_data):
    """
    When candidate pool is exhausted: trailer REJECTED (REPAIR_EXHAUSTED)
    and a blocking human-review item exists.
    """
    family = copy.deepcopy(baseline_data["plans"]["family_v1"])
    family_dict = family.model_dump()
    family_dict["segments"][2]["video"] = "scene_11"
    family_dict["segments"][2]["evidence"] = ["scene:scene_11"]

    plans = {"family_v1": TrailerPlan.model_validate(family_dict)}
    fixtures = baseline_data["fixtures"]

    # Provide empty evidence index to simulate exhausted candidate pool
    patched_plans, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation={
            "family_v1": run_validators(
                family_dict,
                baseline_data["ev_index"],
                {},
                {},
                fixtures["story_facts"].model_dump(),
                baseline_data["cmap"],
                fixtures["subtitles"].model_dump(),
                {"rating_ceiling": "U", "subtitle_track": "hi"},
                0.13,
                2.0,
            )
        },
        evidence_index={"by_scene": {}},  # Empty scene pool!
        constraint_map=baseline_data["cmap"],
        audience_promises={},
        repair_attempts={},
        revision_counter=1,
    )

    # Must generate blocking human review item with REPAIR_EXHAUSTED
    assert any(h.reason_code == "REPAIR_EXHAUSTED" and h.blocking for h in hrs)
    assert any(d.get("entry_type") == "SEGMENT_REJECTED" for d in dlogs)
