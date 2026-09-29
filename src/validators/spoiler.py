"""
Validator 4 — SpoilerValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.4, ARCHITECTURE.md §7.

Checks:
  - Interval overlap: segment [in, out) vs reveal windows of protected facts.
    MAJOR → SPOILER_MAJOR (fail)
    MEDIUM → SPOILER_MEDIUM (warn)
  - Trigger terms: case-insensitive scan across subtitle text, claims, captions,
    and plan-level tagline/text cards.
    MAJOR → SPOILER_MAJOR_TERM (fail)
    MEDIUM → SPOILER_MEDIUM (warn)
  - LLM-added candidates without windows → SPOILER_CANDIDATE_UNVERIFIED (warn)

CRITICAL INVARIANT:
  Historic CTR/engagement MUST NOT override spoiler protection.
  scene_07 (CTR 0.90) must FAIL when it reveals F01/F02.
"""

from __future__ import annotations

import re
from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
)
from src.tools.timecode import parse_timecode, intervals_overlap


class SpoilerValidator:
    """
    Deterministic. Imports no planner or LLM code.
    """

    name = "SpoilerValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        spoiler_map: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate one segment for spoiler reveals (reveal windows + trigger terms).
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        video = segment.get("video") or segment.get("scene_id", "")
        sin = segment.get("source_in", "")
        sout = segment.get("source_out", "")

        try:
            in_ms = parse_timecode(sin)
            out_ms = parse_timecode(sout)
        except Exception:
            # Timecode error will be caught by TimecodeValidator
            in_ms, out_ms = 0, 0

        # Subtitle and claim texts for trigger term scan
        sub = segment.get("subtitle", {})
        sub_text = sub.get("text", "") if isinstance(sub, dict) else getattr(sub, "text", "")
        claims = segment.get("claims", [])
        claim_texts = []
        for cl in claims:
            if isinstance(cl, dict):
                claim_texts.append(cl.get("value", ""))
            else:
                claim_texts.append(getattr(cl, "value", ""))
        combined_text = f"{sub_text} {' '.join(claim_texts)} {segment.get('reason', '')}".lower()

        facts = spoiler_map.get("facts", [])

        for f in facts:
            fid = f.get("fact_id", "")
            slevel = f.get("spoiler_level", "MAJOR")
            if hasattr(slevel, "value"):
                slevel = slevel.value

            # A. Window overlap check
            for win in f.get("reveal_windows", []):
                win_scene = win.get("scene_id", "")
                if win_scene == video:
                    win_in_str = win.get("in") or win.get("source_in", "")
                    win_out_str = win.get("out") or win.get("source_out", "")
                    try:
                        win_in_ms = parse_timecode(win_in_str)
                        win_out_ms = parse_timecode(win_out_str)
                        if intervals_overlap(in_ms, out_ms, win_in_ms, win_out_ms):
                            evidence.append(f"fact:{fid}")
                            if slevel == "MAJOR":
                                errors.append(
                                    ValidationError(
                                        code="SPOILER_MAJOR",
                                        rule_id="POL-SPOILER-001",
                                        segment_id=sid,
                                        message=(
                                            f"Segment {sid} [{sin}, {sout}) overlaps reveal window "
                                            f"[{win_in_str}, {win_out_str}) of MAJOR protected fact {fid}"
                                        ),
                                        evidence=[f"fact:{fid}", f"scene:{video}"],
                                        repairable=True,
                                    )
                                )
                            elif slevel == "MEDIUM":
                                warnings.append(
                                    ValidationWarning(
                                        code="SPOILER_MEDIUM",
                                        rule_id="POL-SPOILER-002",
                                        segment_id=sid,
                                        message=(
                                            f"Segment {sid} overlaps reveal window of MEDIUM protected fact {fid}"
                                        ),
                                        evidence=[f"fact:{fid}", f"scene:{video}"],
                                    )
                                )
                    except Exception:
                        pass

            # B. Trigger terms check in segment viewer-facing text
            trigger_terms = f.get("trigger_terms", [])
            for term in trigger_terms:
                if term and re.search(r"\b" + re.escape(term.lower()) + r"\b", combined_text):
                    evidence.append(f"fact:{fid}")
                    if slevel == "MAJOR":
                        errors.append(
                            ValidationError(
                                code="SPOILER_MAJOR_TERM",
                                rule_id="POL-SPOILER-001",
                                segment_id=sid,
                                message=f"Segment text matches trigger term {term!r} for MAJOR protected fact {fid}",
                                evidence=[f"fact:{fid}", f"term:{term}"],
                                repairable=True,
                            )
                        )
                    elif slevel == "MEDIUM":
                        warnings.append(
                            ValidationWarning(
                                code="SPOILER_MEDIUM",
                                rule_id="POL-SPOILER-002",
                                segment_id=sid,
                                message=f"Segment text matches trigger term {term!r} for MEDIUM protected fact {fid}",
                                evidence=[f"fact:{fid}", f"term:{term}"],
                            )
                        )

        status = ValidatorStatus.FAIL if errors else (ValidatorStatus.WARN if warnings else ValidatorStatus.PASS)

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
        spoiler_map: dict[str, Any],
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment and plan-level spoiler validation.
        """
        results: dict[str, ValidatorResult] = {}
        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(seg_dict, spoiler_map)

        # Plan-level tagline and candidate checks
        plan_errors: list[ValidationError] = []
        plan_warnings: list[ValidationWarning] = []
        plan_evidence: list[str] = []

        tagline = plan.get("tagline", "").lower()
        facts = spoiler_map.get("facts", [])

        for f in facts:
            fid = f.get("fact_id", "")
            slevel = f.get("spoiler_level", "MAJOR")
            if hasattr(slevel, "value"):
                slevel = slevel.value

            for term in f.get("trigger_terms", []):
                if term and re.search(r"\b" + re.escape(term.lower()) + r"\b", tagline):
                    plan_evidence.append(f"fact:{fid}")
                    if slevel == "MAJOR":
                        plan_errors.append(
                            ValidationError(
                                code="SPOILER_MAJOR_TERM",
                                rule_id="POL-SPOILER-001",
                                segment_id="__plan__",
                                message=f"Plan tagline matches trigger term {term!r} for MAJOR protected fact {fid}",
                                evidence=[f"fact:{fid}", f"term:{term}"],
                                repairable=True,
                            )
                        )

        # Unverified LLM candidates
        for cand in spoiler_map.get("llm_added_candidates", []):
            cid = cand.get("fact_id", "LLM_CAND")
            if not cand.get("reveal_windows"):
                plan_warnings.append(
                    ValidationWarning(
                        code="SPOILER_CANDIDATE_UNVERIFIED",
                        rule_id="POL-SPOILER-003",
                        segment_id="__plan__",
                        message=f"LLM proposed spoiler candidate {cid} without reveal windows",
                        evidence=[f"fact:{cid}"],
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
            evidence=plan_evidence,
        )

        return results
