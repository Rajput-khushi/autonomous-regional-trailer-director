"""
Validator 7 — DialectConsistencyValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.7, ARCHITECTURE.md §7.

Checks:
  - Aligned hi cue must exist → DIALECT_CUE_MISSING (fail)
  - Meaning tags parity between dialect and hi cue → DIALECT_MEANING_MISMATCH (fail)
  - Stereotype flags must be empty → DIALECT_STEREOTYPE_FLAG (fail)
  - Comic/caricature framing forbidden → DIALECT_COMIC_FRAMING (fail)
  - Always emits warning NATIVE_REVIEW_PENDING on dialect tracks.
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
)

FORBIDDEN_DIALECT_FRAMING = {
    "dialect_as_comedy",
    "stereotype_caricature",
    "location_assumption",
}


class DialectConsistencyValidator:
    """
    Deterministic. Imports no planner or LLM code.
    Checks tag parity as semantic proxy; does not claim native linguistic expertise.
    """

    name = "DialectConsistencyValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        evidence_index: dict[str, Any],
        audience_profile: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate one segment for dialect consistency and respect.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        video = segment.get("video") or segment.get("scene_id", "")
        sub = segment.get("subtitle", {})
        track = sub.get("track", "hi") if isinstance(sub, dict) else getattr(sub, "track", "hi")
        cue_ids = sub.get("cue_ids", []) if isinstance(sub, dict) else getattr(sub, "cue_ids", [])

        is_dialect_track = track in ("bgc", "raj")

        # 1. Framing tags check
        framing_tags = set(segment.get("framing_tags", []))
        comic_tags = framing_tags.intersection(FORBIDDEN_DIALECT_FRAMING)
        if comic_tags:
            errors.append(
                ValidationError(
                    code="DIALECT_COMIC_FRAMING",
                    rule_id="POL-DIALECT-002",
                    segment_id=sid,
                    message=f"Segment {sid} uses forbidden dialect framing tags: {sorted(comic_tags)}",
                    evidence=[f"tag:{t}" for t in comic_tags],
                    repairable=True,
                )
            )

        # 2. Check dialect cues if this is a dialect track
        if is_dialect_track:
            # Always emit advisory warning for dialect review
            warnings.append(
                ValidationWarning(
                    code="NATIVE_REVIEW_PENDING",
                    rule_id="POL-DIALECT-003",
                    segment_id=sid,
                    message=f"Segment {sid} uses dialect track {track}; native linguistic review pending",
                    evidence=[f"track:{track}"],
                )
            )

            scenes_map = evidence_index.get("by_scene", {})
            sc_data = scenes_map.get(video, {})
            track_cues = sc_data.get("subtitle_cues", {}).get(track, [])
            hi_cues = sc_data.get("subtitle_cues", {}).get("hi", [])

            # Index by cue_id
            dialect_cues_by_id = {c.get("cue_id"): c for c in track_cues}
            hi_cues_by_id = {c.get("cue_id"): c for c in hi_cues}

            for cid in cue_ids:
                d_cue = dialect_cues_by_id.get(cid)
                if not d_cue:
                    continue

                evidence.append(f"cue:{cid}")

                # Check aligns_with
                aligns_with = d_cue.get("aligns_with")
                if not aligns_with or aligns_with not in hi_cues_by_id:
                    errors.append(
                        ValidationError(
                            code="DIALECT_CUE_MISSING",
                            rule_id="POL-DIALECT-001",
                            segment_id=sid,
                            message=f"Dialect cue {cid} has no valid aligned Hindi source cue",
                            evidence=[f"cue:{cid}"],
                            repairable=True,
                        )
                    )
                else:
                    hi_cue = hi_cues_by_id[aligns_with]
                    # Check meaning tags parity
                    d_tags = set(d_cue.get("meaning_tags", []))
                    hi_tags = set(hi_cue.get("meaning_tags", []))
                    if d_tags != hi_tags:
                        errors.append(
                            ValidationError(
                                code="DIALECT_MEANING_MISMATCH",
                                rule_id="POL-DIALECT-001",
                                segment_id=sid,
                                message=(
                                    f"Dialect cue {cid} meaning tags {sorted(d_tags)} mismatch "
                                    f"aligned Hindi cue {aligns_with} tags {sorted(hi_tags)}"
                                ),
                                evidence=[f"cue:{cid}", f"cue:{aligns_with}"],
                                repairable=True,
                            )
                        )

                # Check stereotype flags
                st_flags = d_cue.get("stereotype_flags", [])
                if st_flags:
                    errors.append(
                        ValidationError(
                            code="DIALECT_STEREOTYPE_FLAG",
                            rule_id="POL-DIALECT-002",
                            segment_id=sid,
                            message=f"Dialect cue {cid} contains stereotype flags: {st_flags}",
                            evidence=[f"cue:{cid}", f"flag:{st_flags}"],
                            repairable=True,
                        )
                    )

        status = ValidatorStatus.FAIL if errors else (ValidatorStatus.WARN if warnings else ValidatorStatus.PASS)

        return ValidatorResult(
            validator=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
            evidence=evidence,
        )

    def validate(
        self,
        plan: dict[str, Any],
        evidence_index: dict[str, Any],
        audience_profile: dict[str, Any],
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment dialect consistency validation for an entire trailer plan.
        """
        results: dict[str, ValidatorResult] = {}
        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(seg_dict, evidence_index, audience_profile)
        return results
