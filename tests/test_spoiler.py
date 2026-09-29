"""
T3 — test_spoiler (VALIDATION_AND_TESTING.md §6 T3).
Deterministic spoiler validation, window overlap, trigger terms, and repair.
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
    SubtitleRef,
    AudioMode,
)
from src.validators.spoiler import SpoilerValidator
from src.validators.aggregate import run_validators
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.constraints import build_constraint_map
from src.story import build_spoiler_map
from src.repair import repair_plan


@pytest.fixture
def spoiler_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    cmap = build_constraint_map(
        fixtures["contracts"], fixtures["policies"], fixtures["audiences"], fixtures["cost_sheet"]
    )
    s_map = build_spoiler_map(fixtures["story_facts"].model_dump(), [])
    return {
        "fixtures": fixtures,
        "ev_index": ev_index,
        "cmap": cmap,
        "spoiler_map": s_map,
    }


def test_spoiler_major_window(spoiler_context):
    """
    Scenario: traps draft — dialect_region_v1.segment_03 = scene_07 [04:48, 04:56).
    Expected: SPOILER_MAJOR citing F01; trailer REPAIR_REQUIRED.
    Repair: repaired clip not in any MAJOR window; repair record cites fact:F01.
    Historic score 0.90 did NOT prevent failure.
    """
    validator = SpoilerValidator()
    s_map = spoiler_context["spoiler_map"]

    seg = {
        "segment_id": "segment_03",
        "video": "scene_07",
        "source_in": "00:04:48.000",
        "source_out": "00:04:56.000",
    }
    res = validator.validate_segment(seg, s_map)
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "SPOILER_MAJOR" in error_codes
    assert any("F01" in " ".join(e.evidence) or "F01" in e.message for e in res.errors)

    # Replay traps draft in full plan
    traps_raw = json.loads((Path("data/replay/trailer_plans.traps.json")).read_text(encoding="utf-8"))
    plan_dict = dict(traps_raw["response"]["plans"]["dialect_region_v1"])
    plan_dict["audience"] = "dialect_region"
    plan_dict["duration_seconds"] = float(plan_dict.get("total_duration_s", 36.0))
    plan_dict["audience_promise"] = "Dialect regional promise"
    for s in plan_dict["segments"]:
        if "video" not in s and "scene_id" in s:
            s["video"] = s["scene_id"]

    fixtures = spoiler_context["fixtures"]
    val = run_validators(
        plan_dict,
        spoiler_context["ev_index"],
        s_map,
        {},
        fixtures["story_facts"].model_dump(),
        spoiler_context["cmap"],
        fixtures["subtitles"].model_dump(),
        {"rating_ceiling": "UA13+", "subtitle_track": "bgc"},
        0.13,
        2.0,
    )
    assert val.status == TrailerStatus.REPAIR_REQUIRED

    # Repair should replace the spoiler clip
    plans = {"dialect_region_v1": TrailerPlan.model_validate(plan_dict)}
    patched, attempts, revs, hrs, dlogs = repair_plan(
        candidate_plan=plans,
        validation={"dialect_region_v1": val},
        evidence_index=spoiler_context["ev_index"],
        constraint_map=spoiler_context["cmap"],
        audience_promises={"dialect_region": {"framing_tags": ["humour"], "required_beats": []}},
        repair_attempts={},
        revision_counter=1,
        spoiler_map=s_map,
        story_facts=fixtures["story_facts"].model_dump(),
        subtitles=fixtures["subtitles"].model_dump(),
    )

    repaired_seg = patched["dialect_region_v1"].segments[2]
    # Repaired clip should not overlap F01 [00:04:50, 00:05:10) on scene_07
    if repaired_seg.video == "scene_07":
        assert not (repaired_seg.source_in < "00:05:10.000" and repaired_seg.source_out > "00:04:50.000")
    else:
        assert repaired_seg.video != "scene_07"
    assert len(revs) >= 1
    assert "SPOILER_MAJOR" in revs[0].trigger


def test_spoiler_touching_endpoint_no_overlap(spoiler_context):
    """
    [04:25.000, 04:30.000) touching F02 window at 04:30.000 → NO spoiler (PD-4).
    """
    validator = SpoilerValidator()
    s_map = spoiler_context["spoiler_map"]

    # F02 reveal window on scene_07 starts at 00:04:30.000
    seg = {
        "segment_id": "segment_touching",
        "video": "scene_07",
        "source_in": "00:04:25.000",
        "source_out": "00:04:30.000",
    }
    res = validator.validate_segment(seg, s_map)
    # Should not fail for F02
    assert not any("F02" in " ".join(e.evidence) for e in res.errors)


def test_spoiler_overlapping_endpoint(spoiler_context):
    """
    [04:29.000, 04:31.000) overlaps F02 window → SPOILER_MAJOR (F02).
    """
    validator = SpoilerValidator()
    s_map = spoiler_context["spoiler_map"]

    # F02 reveal window on scene_07 is 00:04:30.000 - 00:04:45.000
    seg = {
        "segment_id": "segment_overlapping",
        "video": "scene_07",
        "source_in": "00:04:29.000",
        "source_out": "00:04:31.000",
    }
    res = validator.validate_segment(seg, s_map)
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "SPOILER_MAJOR" in error_codes
    assert any("F02" in " ".join(e.evidence) or "F02" in e.message for e in res.errors)


def test_spoiler_trigger_term_in_tagline(spoiler_context):
    """
    Tagline "her real father" → SPOILER_MAJOR_TERM.
    """
    validator = SpoilerValidator()
    s_map = spoiler_context["spoiler_map"]

    plan = {
        "tagline": "Discover her real father in this epic drama",
        "segments": [],
    }
    res_dict = validator.validate(plan, s_map)
    plan_res = res_dict["__plan__"]
    assert plan_res.status == ValidatorStatus.FAIL
    codes = [e.code for e in plan_res.errors]
    assert "SPOILER_MAJOR_TERM" in codes
