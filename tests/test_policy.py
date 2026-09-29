"""
T4 — test_policy_failure (VALIDATION_AND_TESTING.md §6 T4).
Audience safety rating ceiling enforcement, unknown flag fail-closed, and subtitle accessibility.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from src.models import ValidatorStatus
from src.validators.audience_safety import AudienceSafetyValidator
from src.validators.accessibility import AccessibilityValidator
from src.evidence import load_and_validate_fixtures, build_evidence_index


@pytest.fixture
def policy_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    return {"fixtures": fixtures, "ev_index": ev_index}


def test_policy_safety_family_rejects_intense_threat(policy_context):
    """
    Setup: clip overlapping PHYSICAL_AGGRESSION_MODERATE (requires UA13+).
    Expected: AudienceSafety FAIL SAFETY_FLAG_EXCEEDS_RATING for family (ceiling U).
    Identical clip in young_adult_v1 (ceiling UA13+) is NOT a failure.
    """
    validator = AudienceSafetyValidator()
    # scene_06 has PHYSICAL_AGGRESSION_MODERATE [00:03:50.000, 00:04:15.000)
    scene_06 = {
        "scene_id": "scene_06",
        "sensitivity_flags": [
            {
                "flag": "PHYSICAL_AGGRESSION_MODERATE",
                "in": "00:03:50.000",
                "out": "00:04:15.000",
            }
        ],
    }

    seg = {
        "segment_id": "seg_safety",
        "video": "scene_06",
        "source_in": "00:03:54.000",
        "source_out": "00:04:02.000",
    }

    # Family (ceiling U): must FAIL
    res_family = validator.validate_segment(seg, scene_06, rating_ceiling="U")
    assert res_family.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res_family.errors]
    assert "SAFETY_FLAG_EXCEEDS_RATING" in error_codes

    # Young Adult (ceiling UA13+): must PASS
    res_ya = validator.validate_segment(seg, scene_06, rating_ceiling="UA13+")
    assert res_ya.status == ValidatorStatus.PASS


def test_policy_safety_unknown_flag_fails_closed(policy_context):
    """
    Unknown sensitivity flag → SAFETY_UNKNOWN_FLAG (fail closed, not PASS).
    """
    validator = AudienceSafetyValidator()
    scene = {
        "scene_id": "scene_unknown_flag",
        "sensitivity_flags": [
            {
                "flag": "UNSPECIFIED_MYSTERIOUS_HAZARD",
                "in": "00:00:10.000",
                "out": "00:00:20.000",
            }
        ],
    }
    seg = {
        "segment_id": "seg_unknown",
        "video": "scene_unknown_flag",
        "source_in": "00:00:12.000",
        "source_out": "00:00:18.000",
    }
    res = validator.validate_segment(seg, scene, rating_ceiling="A")
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "SAFETY_UNKNOWN_FLAG" in error_codes


def test_policy_missing_subtitle_access_fail(policy_context):
    """
    Drop required subtitle (POL-ACCESS-001) → ACCESS_SUBTITLE_MISSING.
    """
    validator = AccessibilityValidator()
    ev_index = policy_context["ev_index"]

    # scene_02 has dialogue lines at [00:00:50.000, 00:00:55.000)
    seg = {
        "segment_id": "seg_no_sub",
        "video": "scene_02",
        "source_in": "00:00:50.000",
        "source_out": "00:01:00.000",
        "subtitle": {
            "track": "hi",
            "cue_ids": [],
            "text": "",
        },
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "U", "subtitle_track": "hi"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "ACCESS_SUBTITLE_MISSING" in error_codes


def test_accessibility_cue_outside_segment(policy_context):
    """
    Referenced cue extends outside segment bounds -> ACCESS_CUE_OUTSIDE_SEGMENT.
    """
    validator = AccessibilityValidator()
    ev_index = policy_context["ev_index"]

    # sub_hi_001_01 is [00:00:09.000, 00:00:13.000)
    # segment ends early at 00:00:11.000
    seg = {
        "segment_id": "seg_cue_out",
        "video": "scene_01",
        "source_in": "00:00:08.000",
        "source_out": "00:00:11.000",
        "subtitle": {
            "track": "hi",
            "cue_ids": ["sub_hi_001_01"],
            "text": "Aao, chai pi lo, thandi ho rahi hai.",
        },
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "U", "subtitle_track": "hi"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "ACCESS_CUE_OUTSIDE_SEGMENT" in error_codes


def test_accessibility_audio_only_info(policy_context):
    """
    Audio-only key info scene requires subtitle/caption -> ACCESS_AUDIO_ONLY_INFO.
    """
    validator = AccessibilityValidator()
    ev_index = policy_context["ev_index"]

    # scene_03 has audio_only_key_info = true
    seg = {
        "segment_id": "seg_audio_only",
        "video": "scene_03",
        "source_in": "00:01:25.000",
        "source_out": "00:01:35.000",
        "subtitle": {
            "track": "hi",
            "cue_ids": [],
            "text": "",
        },
        "reason": "silent clip without subtitle",
    }
    res = validator.validate_segment(
        seg, ev_index, {"rating_ceiling": "U", "subtitle_track": "hi"}
    )
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "ACCESS_AUDIO_ONLY_INFO" in error_codes

