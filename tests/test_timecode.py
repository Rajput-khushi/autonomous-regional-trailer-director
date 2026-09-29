"""
Adversarial test stubs — timecode validation (VALIDATION_AND_TESTING.md §7).
"""

from __future__ import annotations

import pytest

from src.models import ValidatorStatus
from src.validators.timecode import TimecodeValidator
from src.tools.timecode import parse_timecode, intervals_overlap


@pytest.mark.parametrize("bad_timecode,expected_code", [
    ("02:14",           "TIMECODE_FORMAT"),
    ("00:00:50.000",    "TIMECODE_ORDER"),          # in >= out (same timecode)
    ("00:00:00.000",    "TIMECODE_OUT_OF_SCENE"),    # before scene start
    ("00:06:01.000",    "TIMECODE_OUT_OF_EPISODE"),  # past episode end
])
def test_invalid_timecode(bad_timecode: str, expected_code: str):
    """Various invalid timecode cases → matching TIMECODE_* fail code."""
    validator = TimecodeValidator()
    # scene_02 runs from 00:00:45.000 to 00:01:25.000
    scene_02 = {
        "scene_id": "scene_02",
        "in": "00:00:45.000",
        "out": "00:01:25.000",
    }

    if expected_code == "TIMECODE_FORMAT":
        seg = {
            "segment_id": "seg_test",
            "source_in": bad_timecode,
            "source_out": "00:01:00.000",
            "video": "scene_02",
        }
    elif expected_code == "TIMECODE_ORDER":
        seg = {
            "segment_id": "seg_test",
            "source_in": "00:00:50.000",
            "source_out": bad_timecode,  # in >= out
            "video": "scene_02",
        }
    elif expected_code == "TIMECODE_OUT_OF_SCENE":
        seg = {
            "segment_id": "seg_test",
            "source_in": bad_timecode,  # before scene start 00:00:45.000
            "source_out": "00:01:00.000",
            "video": "scene_02",
        }
    elif expected_code == "TIMECODE_OUT_OF_EPISODE":
        seg = {
            "segment_id": "seg_test",
            "source_in": "00:05:55.000",
            "source_out": bad_timecode,  # past episode end 00:06:00.000
            "video": "scene_02",
        }
    else:
        raise ValueError(f"Unknown test case {expected_code}")

    res = validator.validate_segment(seg, scene_02, episode_duration_ms=360000)
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert expected_code in error_codes


def test_timecode_touching_endpoint_does_not_overlap():
    """
    [04:25.000, 04:30.000) touching a spoiler window at 04:30.000 → no overlap (PD-4).
    """
    a_in = parse_timecode("00:04:25.000")
    a_out = parse_timecode("00:04:30.000")

    b_in = parse_timecode("00:04:30.000")
    b_out = parse_timecode("00:04:45.000")

    assert not intervals_overlap(a_in, a_out, b_in, b_out)
