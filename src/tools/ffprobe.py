"""
tools/ffprobe.py — Optional ffprobe duration check helper.
Authority: IMPLEMENTATION_PLAN.md §7 (evidence/story/constraints), §11 (cut list).

Used to verify that the episode media file duration matches episode.duration.
This is optional (IMPLEMENTATION_PLAN.md cut list item 2).
All core logic works without it.

Phase 0: stub only.
"""

from __future__ import annotations

from pathlib import Path


def probe_duration_ms(media_path: Path) -> int | None:
    """
    Run ffprobe on media_path and return duration in milliseconds.
    Returns None if ffprobe is not installed or the file doesn't exist.

    TODO Phase 4 (optional): implement subprocess ffprobe call.
    """
    # TODO Phase 4 (optional):
    # import subprocess, json
    # result = subprocess.run(
    #     ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(media_path)],
    #     capture_output=True, text=True, timeout=10
    # )
    # data = json.loads(result.stdout)
    # return int(float(data["format"]["duration"]) * 1000)
    return None  # graceful no-op if ffprobe not available
