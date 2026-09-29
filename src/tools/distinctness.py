"""
distinctness.py — Pairwise distinctness metrics across trailer plans.
Authority: VALIDATION_AND_TESTING.md §4.10, ARCHITECTURE.md §7, SUMMARY.md §16.

Note: Distinctness is a plan-level report/test metric, NOT a PASS/FAIL validator (PD-7).
"""

from __future__ import annotations

from typing import Any
from src.tools.timecode import parse_timecode, intervals_overlap


def compute_pairwise_overlap_seconds(
    plan_a: dict[str, Any],
    plan_b: dict[str, Any],
) -> float:
    """
    Compute total overlapping source footage seconds between two trailer plans.
    Interval rule PD-4: half-open intervals [in, out).
    Only segments referencing the same scene can overlap.
    """
    segs_a = plan_a.get("segments", [])
    segs_b = plan_b.get("segments", [])

    overlap_ms = 0

    for sa in segs_a:
        sa_dict = sa.model_dump() if hasattr(sa, "model_dump") else dict(sa)
        va = sa_dict.get("video") or sa_dict.get("scene_id")
        ina_str = sa_dict.get("source_in", "")
        outa_str = sa_dict.get("source_out", "")

        try:
            ina = parse_timecode(ina_str)
            outa = parse_timecode(outa_str)
        except Exception:
            continue

        for sb in segs_b:
            sb_dict = sb.model_dump() if hasattr(sb, "model_dump") else dict(sb)
            vb = sb_dict.get("video") or sb_dict.get("scene_id")
            if va != vb:
                continue

            inb_str = sb_dict.get("source_in", "")
            outb_str = sb_dict.get("source_out", "")
            try:
                inb = parse_timecode(inb_str)
                outb = parse_timecode(outb_str)
            except Exception:
                continue

            if intervals_overlap(ina, outa, inb, outb):
                start = max(ina, inb)
                end = min(outa, outb)
                if end > start:
                    overlap_ms += (end - start)

    return overlap_ms / 1000.0


def compute_distinctness_report(
    plans: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute distinctness metrics across all pairs of trailer plans.
    Returns:
      {
        "pairwise_overlap": {
          "family_v1__vs__young_adult_v1": {
            "overlap_seconds": float,
            "shorter_duration_s": float,
            "overlap_ratio": float,
            "within_target": bool  # <= 25% (VALIDATION_AND_TESTING.md §8)
          },
          ...
        },
        "first_segments": {trailer_id: {"scene": ..., "role": ...}},
        "first_segments_distinct": bool,
        "taglines": {trailer_id: tagline},
        "taglines_distinct": bool,
      }
    """
    tids = sorted(plans.keys())
    pairwise: dict[str, Any] = {}

    for i in range(len(tids)):
        for j in range(i + 1, len(tids)):
            t1 = tids[i]
            t2 = tids[j]
            p1 = plans[t1]
            p2 = plans[t2]
            p1_dict = p1.model_dump() if hasattr(p1, "model_dump") else dict(p1)
            p2_dict = p2.model_dump() if hasattr(p2, "model_dump") else dict(p2)

            overlap_s = compute_pairwise_overlap_seconds(p1_dict, p2_dict)
            dur1 = float(p1_dict.get("duration_seconds", 30.0))
            dur2 = float(p2_dict.get("duration_seconds", 30.0))
            shorter_dur = min(dur1, dur2) if min(dur1, dur2) > 0 else 30.0
            ratio = overlap_s / shorter_dur

            key = f"{t1}__vs__{t2}"
            pairwise[key] = {
                "overlap_seconds": round(overlap_s, 2),
                "shorter_duration_s": round(shorter_dur, 2),
                "overlap_ratio": round(ratio, 4),
                "within_target": ratio <= 0.25,
            }

    # First segments
    first_segs: dict[str, Any] = {}
    first_keys: list[tuple[str, str]] = []
    for tid, p in plans.items():
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        segs = p_dict.get("segments", [])
        if segs:
            s0 = segs[0].model_dump() if hasattr(segs[0], "model_dump") else dict(segs[0])
            sc = s0.get("video") or s0.get("scene_id", "")
            role = s0.get("role", "")
            sin = s0.get("source_in", "")
            sout = s0.get("source_out", "")
            first_segs[tid] = {"scene": sc, "role": role, "in": sin, "out": sout}
            first_keys.append((sc, sin, sout))
        else:
            first_segs[tid] = {}

    first_distinct = len(set(first_keys)) == len(first_keys) if first_keys else True

    # Taglines
    taglines: dict[str, str] = {}
    for tid, p in plans.items():
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        taglines[tid] = p_dict.get("tagline", "").strip()

    tagline_vals = [t.lower() for t in taglines.values() if t]
    taglines_distinct = len(set(tagline_vals)) == len(tagline_vals) if tagline_vals else True

    return {
        "pairwise_overlap": pairwise,
        "first_segments": first_segs,
        "first_segments_distinct": first_distinct,
        "taglines": taglines,
        "taglines_distinct": taglines_distinct,
    }
