"""
T5 — test_changed_contract (VALIDATION_AND_TESTING.md §6 T5).
Change-impact analysis tests for Phase 8.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import pytest

from src.graph import graph
from src.impact import (
    analyze_change_impact,
    assert_unaffected_unchanged,
    compute_segment_hash,
)
from src.models import ChangeEvent, TrailerStatus
from src.validators.rights import RightsValidator
from src.validators.aggregate import run_validators


@pytest.fixture
def baseline_clean_state(tmp_path):
    """Run baseline clean scenario and return the final state."""
    init_state = {
        "run_config": {
            "mode": "replay",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 5.0,
            "output_dir": str(tmp_path),
        },
        "decision_log": [],
    }
    return graph.invoke(init_state)


def test_changed_contract_affected_decisions_exact(baseline_clean_state):
    """
    Setup: baseline clean run → run_state.json.
    Apply music_03_expired.json change event.
    Expected affected_decisions == {family_v1.segment_02, dialect_region_v1.segment_04} (exact set).
    """
    change_evt_path = Path("data/change_events/music_03_expired.json")
    with open(change_evt_path, "r", encoding="utf-8") as f:
        change_evt = json.load(f)

    # 1. Direct unit test of analyze_change_impact
    new_cmap, affected_sids, unaffected_hashes = analyze_change_impact(
        change_event=change_evt,
        candidate_plan=baseline_clean_state["candidate_plan"],
        dependency_index=baseline_clean_state.get("dependency_index"),
        constraint_map=baseline_clean_state["constraint_map"],
    )

    expected = {"family_v1.segment_02", "dialect_region_v1.segment_04"}
    assert set(affected_sids) == expected

    # 2. Graph execution test
    change_state = dict(baseline_clean_state)
    change_state["change_event"] = change_evt
    out = graph.invoke(change_state)

    # Validate that affected_decisions was identified and repaired
    rev_affected = {
        aff
        for r in out.get("revisions", [])
        for aff in (r.affected if hasattr(r, "affected") else r.get("affected", []))
    }
    assert rev_affected == expected

    # Also verify IMPACT_ANALYSIS log entry
    impact_logs = [d for d in out.get("decision_log", []) if d.get("entry_type") == "IMPACT_ANALYSIS"]
    assert len(impact_logs) >= 1
    assert set(impact_logs[0]["evidence"]) == expected


def test_changed_contract_unaffected_segments_byte_identical(baseline_clean_state, tmp_path):
    """
    young_adult_v1 and all other segments are byte-identical (hash equality) before/after.
    """
    change_evt_path = Path("data/change_events/music_03_expired.json")
    with open(change_evt_path, "r", encoding="utf-8") as f:
        change_evt = json.load(f)

    # Snapshot hashes before
    before_plans = baseline_clean_state["candidate_plan"]
    unaffected_ids = [
        "family_v1.segment_01",
        "family_v1.segment_03",
        "family_v1.segment_04",
        "young_adult_v1.segment_01",
        "young_adult_v1.segment_02",
        "young_adult_v1.segment_03",
        "young_adult_v1.segment_04",
        "young_adult_v1.segment_05",
        "dialect_region_v1.segment_01",
        "dialect_region_v1.segment_02",
        "dialect_region_v1.segment_03",
    ]
    before_hashes = {}
    for tid, p in before_plans.items():
        p_dict = p if isinstance(p, dict) else p.model_dump()
        for s in p_dict.get("segments", []):
            full_id = f"{tid}.{s['segment_id']}"
            if full_id in unaffected_ids:
                before_hashes[full_id] = compute_segment_hash(s)

    # Run change impact
    change_state = dict(baseline_clean_state)
    change_state["change_event"] = change_evt
    change_state["run_config"] = dict(baseline_clean_state.get("run_config", {}))
    change_state["run_config"]["output_dir"] = str(tmp_path / "after")

    out = graph.invoke(change_state)

    # Invariant assertion
    violations = assert_unaffected_unchanged(
        before_hashes,
        out["candidate_plan"],
        unaffected_ids,
    )
    assert violations == [], f"Found hash violations in unaffected segments: {violations}"

    # Specifically check young_adult_v1
    ya_before = before_plans["young_adult_v1"].model_dump() if hasattr(before_plans["young_adult_v1"], "model_dump") else before_plans["young_adult_v1"]
    ya_after = out["candidate_plan"]["young_adult_v1"].model_dump() if hasattr(out["candidate_plan"]["young_adult_v1"], "model_dump") else out["candidate_plan"]["young_adult_v1"]
    for s_before, s_after in zip(ya_before["segments"], ya_after["segments"]):
        assert compute_segment_hash(s_before) == compute_segment_hash(s_after)


def test_changed_contract_affected_segments_repaired(baseline_clean_state, tmp_path):
    """
    Both affected segments fail RIGHTS_EXPIRED → repaired to music_05
    (shares mood tag 'warm', passes rights) → final PASS/PASS_WITH_WARNINGS.
    """
    change_evt_path = Path("data/change_events/music_03_expired.json")
    with open(change_evt_path, "r", encoding="utf-8") as f:
        change_evt = json.load(f)

    change_state = dict(baseline_clean_state)
    change_state["change_event"] = change_evt
    change_state["run_config"] = dict(baseline_clean_state.get("run_config", {}))
    change_state["run_config"]["output_dir"] = str(tmp_path / "after")

    out = graph.invoke(change_state)

    assert out["status"] in ("PASS", "PASS_WITH_WARNINGS")

    # Check that affected segments now use music_05
    family_plan = out["candidate_plan"]["family_v1"]
    family_dict = family_plan if isinstance(family_plan, dict) else family_plan.model_dump()
    seg2 = next(s for s in family_dict["segments"] if s["segment_id"] == "segment_02")
    assert seg2["music_asset_id"] == "music_05"

    dr_plan = out["candidate_plan"]["dialect_region_v1"]
    dr_dict = dr_plan if isinstance(dr_plan, dict) else dr_plan.model_dump()
    seg4 = next(s for s in dr_dict["segments"] if s["segment_id"] == "segment_04")
    assert seg4["music_asset_id"] == "music_05"


def test_changed_contract_validators_rerun_only_affected(baseline_clean_state):
    """
    Validators ran ONLY for affected segments (assert by segment id);
    plan-level checks ran for all.
    """
    change_evt_path = Path("data/change_events/music_03_expired.json")
    with open(change_evt_path, "r", encoding="utf-8") as f:
        change_evt = json.load(f)

    new_cmap, affected_sids, _ = analyze_change_impact(
        change_event=change_evt,
        candidate_plan=baseline_clean_state["candidate_plan"],
        dependency_index=baseline_clean_state.get("dependency_index"),
        constraint_map=baseline_clean_state["constraint_map"],
    )

    # When run_validators is called with affected_decisions, it only executes
    # segment checks on affected segments.
    family_plan = baseline_clean_state["candidate_plan"]["family_v1"]
    val_res = run_validators(
        plan=family_plan,
        evidence_index=baseline_clean_state["evidence"],
        spoiler_map=baseline_clean_state["spoiler_map"],
        story_map=baseline_clean_state["story_map"],
        story_facts=baseline_clean_state["episode"]["_validated_fixtures"]["story_facts"].model_dump(),
        constraint_map=new_cmap,
        subtitles=baseline_clean_state["episode"]["_validated_fixtures"]["subtitles"].model_dump(),
        audience_profile={"rating_ceiling": "U", "subtitle_track": "hi"},
        estimated_cost=0.13,
        run_budget=5.0,
        affected_decisions=affected_sids,
    )

    # Must contain RIGHTS_EXPIRED for segment_02 only
    errors = [e for v in val_res.validators for e in v.errors]
    assert any(e.code == "RIGHTS_EXPIRED" and e.segment_id == "segment_02" for e in errors)
    # segment_01, 03, 04 must not have errors
    assert not any(e.segment_id in ("segment_01", "segment_03", "segment_04") for e in errors)


def test_changed_contract_revision_log_updated(baseline_clean_state, tmp_path):
    """
    revision_log.json gains a record with trigger, affected, unchanged,
    action, validators_rerun, validation fields.
    """
    change_evt_path = Path("data/change_events/music_03_expired.json")
    with open(change_evt_path, "r", encoding="utf-8") as f:
        change_evt = json.load(f)

    change_state = dict(baseline_clean_state)
    change_state["change_event"] = change_evt
    change_state["run_config"] = dict(baseline_clean_state.get("run_config", {}))
    change_state["run_config"]["output_dir"] = str(tmp_path / "after")

    out = graph.invoke(change_state)

    rev_log_path = tmp_path / "after" / "revision_log.json"
    assert rev_log_path.exists()

    with open(rev_log_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    revisions = data.get("revisions", [])
    assert len(revisions) >= 2

    for r in revisions:
        assert "trigger" in r
        assert "affected" in r
        assert "unchanged" in r
        assert "action" in r
        assert "validators_rerun" in r
        assert "validation" in r
        assert "hashes_unchanged" in r


def test_changed_contract_unknown_asset_hard_error(baseline_clean_state):
    """
    Change event with an unknown asset_id → hard error (no silent no-op).
    """
    bad_change_event = {
        "synthetic": True,
        "event_id": "CE-BAD",
        "event_type": "CONTRACT_UPDATE",
        "target_asset_id": "unknown_asset_9999",
        "change": {
            "field": "valid_until",
            "old_value": "2027-12-31",
            "new_value": "2026-09-01",
        },
    }

    with pytest.raises(ValueError, match="Unknown asset_id in change event"):
        analyze_change_impact(
            change_event=bad_change_event,
            candidate_plan=baseline_clean_state["candidate_plan"],
            dependency_index=baseline_clean_state.get("dependency_index"),
            constraint_map=baseline_clean_state["constraint_map"],
        )
