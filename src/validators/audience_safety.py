"""
Validator 6 — AudienceSafetyValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.6, ARCHITECTURE.md §7.

Checks:
  - Inspects sensitivity_flags on scene (whole-scene and windowed flags overlapping segment).
  - Compares flag minimum rating against audience rating ceiling using rating order:
    ["U", "UA13+", "UA16+", "A"].
  - Unknown sensitivity flag → SAFETY_UNKNOWN_FLAG (fail closed).
  - Flag rating > ceiling → SAFETY_FLAG_EXCEEDS_RATING (fail).
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
)
from src.tools.timecode import parse_timecode, intervals_overlap

RATING_ORDER = ["U", "UA13+", "UA16+", "A"]
RATING_INDEX = {r: i for i, r in enumerate(RATING_ORDER)}

KNOWN_FLAG_MIN_RATINGS: dict[str, str] = {
    "SUGGESTIVE_HUMOUR_MILD": "U",
    "VERBAL_CONFLICT_MILD": "U",
    "PHYSICAL_AGGRESSION_MODERATE": "UA13+",
    "INTENSE_THREAT": "UA13+",
}


class AudienceSafetyValidator:
    """
    Deterministic. Imports no planner or LLM code.
    """

    name = "AudienceSafetyValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        scene: dict[str, Any],
        rating_ceiling: str = "U",
    ) -> ValidatorResult:
        """
        Validate safety flags for one segment against audience rating ceiling.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        sin = segment.get("source_in", "")
        sout = segment.get("source_out", "")

        try:
            in_ms = parse_timecode(sin)
            out_ms = parse_timecode(sout)
        except Exception:
            in_ms, out_ms = 0, 0

        ceiling_idx = RATING_INDEX.get(rating_ceiling, 0)

        # Check sensitivity flags on scene
        sens_flags = scene.get("sensitivity_flags", [])
        for sf in sens_flags:
            flag_name = sf.get("flag", "")
            if not flag_name:
                continue

            # Check if flag is unknown
            if flag_name not in KNOWN_FLAG_MIN_RATINGS:
                errors.append(
                    ValidationError(
                        code="SAFETY_UNKNOWN_FLAG",
                        rule_id="POL-RATING-002",
                        segment_id=sid,
                        message=f"Unknown sensitivity flag {flag_name!r} encountered in scene {scene.get('scene_id')}",
                        evidence=[f"flag:{flag_name}"],
                        repairable=True,
                    )
                )
                continue

            min_rating = KNOWN_FLAG_MIN_RATINGS[flag_name]
            min_idx = RATING_INDEX[min_rating]

            # Check if flag is windowed or whole scene
            win_in = sf.get("in") or sf.get("source_in")
            win_out = sf.get("out") or sf.get("source_out")

            applies = False
            if win_in and win_out:
                try:
                    win_in_ms = parse_timecode(win_in)
                    win_out_ms = parse_timecode(win_out)
                    if intervals_overlap(in_ms, out_ms, win_in_ms, win_out_ms):
                        applies = True
                except Exception:
                    applies = True
            else:
                # Whole-scene flag applies to all segments in that scene
                applies = True

            if applies:
                evidence.append(f"flag:{flag_name}")
                if min_idx > ceiling_idx:
                    errors.append(
                        ValidationError(
                            code="SAFETY_FLAG_EXCEEDS_RATING",
                            rule_id="POL-RATING-001",
                            segment_id=sid,
                            message=(
                                f"Segment {sid} in scene {scene.get('scene_id')} contains flag {flag_name} "
                                f"(requires {min_rating}) which exceeds audience ceiling {rating_ceiling}"
                            ),
                            evidence=[f"flag:{flag_name}", f"scene:{scene.get('scene_id')}"],
                            repairable=True,
                        )
                    )

        status = ValidatorStatus.FAIL if errors else ValidatorStatus.PASS

        return ValidatorResult(
            validator=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
            evidence=sorted(set(evidence)),
        )

    def validate(
        self,
        plan: dict[str, Any],
        evidence_index: dict[str, Any],
        audience_profile: dict[str, Any],
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment safety validation for an entire trailer plan.
        """
        results: dict[str, ValidatorResult] = {}
        ceiling = audience_profile.get("rating_ceiling", "U")
        scenes_map = evidence_index.get("by_scene", {})

        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            video = seg_dict.get("video") or seg_dict.get("scene_id", "")
            sc = scenes_map.get(video, {})
            results[sid] = self.validate_segment(seg_dict, sc, rating_ceiling=ceiling)

        return results
