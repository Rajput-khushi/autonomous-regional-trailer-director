"""
tools/timecode.py — Timecode parsing, formatting and interval utilities.
Authority: DATA_SPEC.md §1, VALIDATION_AND_TESTING.md §4.2, PROTOTYPE_SPEC.md PD-4.

Conventions:
  - Timecodes are strings in the format HH:MM:SS.mmm.
  - Internally parsed to integer milliseconds.
  - Intervals are half-open [in, out).
  - Touching endpoints do NOT overlap (PD-4).
"""

from __future__ import annotations

import re

_TC_PATTERN = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})$")


def validate_timecode_format(tc: str) -> bool:
    """Return True if tc matches HH:MM:SS.mmm."""
    if not isinstance(tc, str):
        return False
    return bool(_TC_PATTERN.match(tc))


def parse_timecode(tc: str) -> int:
    """
    Parse a HH:MM:SS.mmm string to integer milliseconds.
    Raises ValueError on invalid format.
    """
    if not isinstance(tc, str):
        raise ValueError(f"Timecode must be string, got {type(tc).__name__}")
    m = _TC_PATTERN.match(tc)
    if not m:
        raise ValueError(f"Invalid timecode format: {tc!r}. Expected HH:MM:SS.mmm")
    h, mins, s, ms = m.groups()
    return ((int(h) * 3600) + (int(mins) * 60) + int(s)) * 1000 + int(ms)


def format_timecode(ms: int) -> str:
    """Format integer milliseconds to HH:MM:SS.mmm string."""
    if ms < 0:
        raise ValueError(f"Milliseconds cannot be negative: {ms}")
    total_seconds, rem_ms = divmod(ms, 1000)
    total_minutes, s = divmod(total_seconds, 60)
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{rem_ms:03d}"


def intervals_overlap(a_in: int, a_out: int, b_in: int, b_out: int) -> bool:
    """
    Return True if half-open intervals [a_in, a_out) and [b_in, b_out) overlap.
    PD-4: touching endpoints (a_out == b_in or b_out == a_in) do NOT overlap.
    """
    return max(a_in, b_in) < min(a_out, b_out)


def segment_duration_ms(source_in: str, source_out: str) -> int:
    """Return the duration of a segment in milliseconds."""
    in_ms = parse_timecode(source_in)
    out_ms = parse_timecode(source_out)
    return out_ms - in_ms
