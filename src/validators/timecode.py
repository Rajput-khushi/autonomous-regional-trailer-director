"""
Validator 2 — TimecodeValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.2.

Checks (hard failures unless marked warn):
  - format HH:MM:SS.mmm
  - in < out
  - [in, out) inside scene bounds (PD-3: single scene)
  - inside episode duration
  - duration_seconds equals summed segment lengths (±0.05 s)
  - trailer length in hard window 20–60 s (POL-DURATION-001)

Warnings:
  - Duration outside 30–45 s target
  - Segment length < 2 s or > 12 s

Interval rule PD-4: half-open; [04:25, 04:30) does NOT overlap a window
starting at 04:30.000.
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
)
from src.tools.timecode import (
    parse_timecode,
    validate_timecode_format,
    segment_duration_ms,
)


class TimecodeValidator:
    """
    Deterministic. Imports no planner or LLM code.
    Time parsing helpers live in src/tools/timecode.py.
    """

    name = "TimecodeValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        scene: dict[str, Any],
        episode_duration_ms: int = 360000,
    ) -> ValidatorResult:
        """
        Validate timecodes for one segment.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        sin = segment.get("source_in", "")
        sout = segment.get("source_out", "")

        # 1. Format check
        if not validate_timecode_format(sin) or not validate_timecode_format(sout):
            errors.append(
                ValidationError(
                    code="TIMECODE_FORMAT",
                    rule_id="TC-001",
                    segment_id=sid,
                    message=f"Invalid timecode format in segment {sid}: in={sin!r}, out={sout!r}",
                    evidence=[f"timecode:{sin}", f"timecode:{sout}"],
                    repairable=True,
                )
            )
            return ValidatorResult(
                validator=self.name,
                status=ValidatorStatus.FAIL,
                errors=errors,
                warnings=warnings,
                evidence=evidence,
            )

        in_ms = parse_timecode(sin)
        out_ms = parse_timecode(sout)

        # 2. in < out order check (half-open [in, out) requires in < out)
        if in_ms >= out_ms:
            errors.append(
                ValidationError(
                    code="TIMECODE_ORDER",
                    rule_id="TC-002",
                    segment_id=sid,
                    message=f"Segment {sid} interval invalid: source_in ({sin}) >= source_out ({sout})",
                    evidence=[f"timecode:{sin}", f"timecode:{sout}"],
                    repairable=True,
                )
            )
            return ValidatorResult(
                validator=self.name,
                status=ValidatorStatus.FAIL,
                errors=errors,
                warnings=warnings,
                evidence=evidence,
            )

        # 3. Scene containment check
        if scene:
            sc_in_str = scene.get("in") or scene.get("source_in", "00:00:00.000")
            sc_out_str = scene.get("out") or scene.get("source_out", "00:06:00.000")
            sc_in_ms = parse_timecode(sc_in_str)
            sc_out_ms = parse_timecode(sc_out_str)

            if in_ms < sc_in_ms or out_ms > sc_out_ms:
                errors.append(
                    ValidationError(
                        code="TIMECODE_OUT_OF_SCENE",
                        rule_id="TC-003",
                        segment_id=sid,
                        message=(
                            f"Segment {sid} [{sin}, {sout}) falls outside scene bounds "
                            f"[{sc_in_str}, {sc_out_str})"
                        ),
                        evidence=[f"scene:{scene.get('scene_id')}", f"timecode:{sin}", f"timecode:{sout}"],
                        repairable=True,
                    )
                )

        # 4. Episode duration containment
        if out_ms > episode_duration_ms:
            errors.append(
                ValidationError(
                    code="TIMECODE_OUT_OF_EPISODE",
                    rule_id="TC-004",
                    segment_id=sid,
                    message=f"Segment {sid} out ({sout}) exceeds episode duration ({episode_duration_ms} ms)",
                    evidence=[f"timecode:{sout}"],
                    repairable=True,
                )
            )

        # 5. Segment length warning (< 2s or > 12s)
        dur_s = (out_ms - in_ms) / 1000.0
        if dur_s < 2.0 or dur_s > 12.0:
            warnings.append(
                ValidationWarning(
                    code="SEGMENT_LENGTH_UNUSUAL",
                    rule_id="TC-005",
                    segment_id=sid,
                    message=f"Segment {sid} duration {dur_s:.2f}s outside typical 2-12s window",
                    evidence=[f"duration:{dur_s}"],
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
        constraint_map: dict[str, Any],
        episode_duration_ms: int = 360000,
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment and plan-level timecode validation for an entire trailer plan.
        Returns {segment_id: ValidatorResult} plus {"__plan__": ValidatorResult}.
        """
        results: dict[str, ValidatorResult] = {}
        scenes_map = evidence_index.get("by_scene", {})

        segments = plan.get("segments", [])
        total_duration_ms = 0

        for seg in segments:
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            video = seg_dict.get("video") or seg_dict.get("scene_id", "")
            sc = scenes_map.get(video, {})
            r = self.validate_segment(seg_dict, sc, episode_duration_ms)
            results[sid] = r

            sin = seg_dict.get("source_in", "")
            sout = seg_dict.get("source_out", "")
            if validate_timecode_format(sin) and validate_timecode_format(sout):
                try:
                    in_ms = parse_timecode(sin)
                    out_ms = parse_timecode(sout)
                    if in_ms < out_ms:
                        total_duration_ms += (out_ms - in_ms)
                except Exception:
                    pass

        # Plan-level duration checks
        plan_errors: list[ValidationError] = []
        plan_warnings: list[ValidationWarning] = []

        total_s = total_duration_ms / 1000.0
        plan_dur_s = float(plan.get("duration_seconds", plan.get("total_duration_s", total_s)))

        # Trailer duration must equal summed segments (±0.05s)
        if abs(total_s - plan_dur_s) > 0.05:
            plan_errors.append(
                ValidationError(
                    code="TIMECODE_DURATION_MISMATCH",
                    rule_id="POL-DURATION-001",
                    segment_id="__plan__",
                    message=f"Plan duration {plan_dur_s:.2f}s does not match summed segments {total_s:.2f}s (±0.05s)",
                    evidence=[f"duration:{total_s}", f"stated:{plan_dur_s}"],
                    repairable=True,
                )
            )

        # Hard bounds 20-60s
        if total_s < 20.0 or total_s > 60.0:
            plan_errors.append(
                ValidationError(
                    code="DURATION_OUT_OF_HARD_WINDOW",
                    rule_id="POL-DURATION-001",
                    segment_id="__plan__",
                    message=f"Trailer total duration {total_s:.2f}s outside hard window [20.0, 60.0]s",
                    evidence=[f"duration:{total_s}"],
                    repairable=True,
                )
            )

        # Target bounds 30-45s (warning only)
        if total_s < 30.0 or total_s > 45.0:
            plan_warnings.append(
                ValidationWarning(
                    code="DURATION_OUTSIDE_TARGET",
                    rule_id="TARGET-DURATION-001",
                    segment_id="__plan__",
                    message=f"Trailer total duration {total_s:.2f}s outside target window [30.0, 45.0]s",
                    evidence=[f"duration:{total_s}"],
                )
            )

        plan_status = (
            ValidatorStatus.FAIL
            if plan_errors
            else (ValidatorStatus.WARN if plan_warnings else ValidatorStatus.PASS)
        )
        results["__plan__"] = ValidatorResult(
            validator=self.name,
            status=plan_status,
            errors=plan_errors,
            warnings=plan_warnings,
            evidence=[f"total_duration:{total_s}"],
        )

        return results
