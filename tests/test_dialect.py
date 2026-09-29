"""
Adversarial test stubs — dialect consistency (VALIDATION_AND_TESTING.md §7).
"""

from __future__ import annotations

import copy
from pathlib import Path
import pytest

from src.models import ValidatorStatus
from src.validators.dialect import DialectConsistencyValidator
from src.evidence import load_and_validate_fixtures, build_evidence_index


@pytest.fixture
def dialect_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    return {"fixtures": fixtures, "ev_index": ev_index}


def test_dialect_meaning_mismatch(dialect_context):
    """
    Mutate bgc cue meaning_tags (drop 'missing_letter', add 'accusation')
    → DIALECT_MEANING_MISMATCH; trailer not PASS.
    """
    validator = DialectConsistencyValidator()
    ev_index = copy.deepcopy(dialect_context["ev_index"])

    # Mutate sub_bgc_003_02 meaning_tags in scene_03
    sc_cues = ev_index["by_scene"]["scene_03"]["subtitle_cues"]["bgc"]
    for cue in sc_cues:
        if cue.get("cue_id") == "sub_bgc_003_02":
            cue["meaning_tags"] = ["accusation", "anger"]

    seg = {
        "segment_id": "seg_bgc_01",
        "video": "scene_03",
        "subtitle": {
            "track": "bgc",
            "cue_ids": ["sub_bgc_003_02"],
            "text": "Kaun sa khat, Chachi?",
        },
    }

    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "UA13+", "subtitle_track": "bgc"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "DIALECT_MEANING_MISMATCH" in error_codes


def test_dialect_comic_framing(dialect_context):
    """
    Add 'dialect_as_comedy' framing tag → DIALECT_COMIC_FRAMING (fail).
    """
    validator = DialectConsistencyValidator()
    ev_index = dialect_context["ev_index"]

    seg = {
        "segment_id": "seg_comic",
        "video": "scene_01",
        "subtitle": {
            "track": "bgc",
            "cue_ids": ["sub_bgc_001_01"],
            "text": "Aa ja, chai pee le.",
        },
        "framing_tags": ["dialect_as_comedy"],
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "UA13+", "subtitle_track": "bgc"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "DIALECT_COMIC_FRAMING" in error_codes


def test_dialect_stereotype_flag(dialect_context):
    """
    Add stereotype_flag to a cue → DIALECT_STEREOTYPE_FLAG (fail).
    """
    validator = DialectConsistencyValidator()
    ev_index = copy.deepcopy(dialect_context["ev_index"])

    sc_cues = ev_index["by_scene"]["scene_01"]["subtitle_cues"]["bgc"]
    for cue in sc_cues:
        if cue.get("cue_id") == "sub_bgc_001_01":
            cue["stereotype_flags"] = ["rustic_caricature"]

    seg = {
        "segment_id": "seg_st",
        "video": "scene_01",
        "subtitle": {
            "track": "bgc",
            "cue_ids": ["sub_bgc_001_01"],
            "text": "Aa ja, chai pee le.",
        },
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "UA13+", "subtitle_track": "bgc"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "DIALECT_STEREOTYPE_FLAG" in error_codes


def test_dialect_native_review_pending_always_warns(dialect_context):
    """
    NATIVE_REVIEW_PENDING warning is always present for dialect tracks.
    """
    validator = DialectConsistencyValidator()
    ev_index = dialect_context["ev_index"]

    seg = {
        "segment_id": "seg_clean_bgc",
        "video": "scene_01",
        "subtitle": {
            "track": "bgc",
            "cue_ids": ["sub_bgc_001_01"],
            "text": "Aa ja, chai pee le, thandi ho rahi se.",
        },
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "UA13+", "subtitle_track": "bgc"}
    )
    # Status should be WARN (warnings present, no errors)
    assert res.status == ValidatorStatus.WARN
    warn_codes = [w.code for w in res.warnings]
    assert "NATIVE_REVIEW_PENDING" in warn_codes
