"""
Validator 5 — StoryTruthValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.5, ARCHITECTURE.md §7.

Checks:
  - forbidden claim patterns in tagline, claims, reasons → STORY_FORBIDDEN_CLAIM (fail)
  - relationship claims must match PUBLIC relationships in story map → STORY_RELATION_MISMATCH (fail)
  - supported_by refs in claims must resolve and belong to scene → STORY_UNSUPPORTED_CLAIM (fail)
  - genre promises must be in permitted_genres → STORY_GENRE_MISMATCH (fail)
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

DEFAULT_PERMITTED_GENRES = {"family_drama", "mystery"}
FORBIDDEN_GENRES = {"revenge_thriller", "murder_mystery", "horror", "romance"}


class StoryTruthValidator:
    """
    Deterministic. Imports no planner or LLM code.
    """

    name = "StoryTruthValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        story_map: dict[str, Any],
        story_facts: dict[str, Any],
        evidence_index: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate one segment for story truth (claims, relationships, genres).
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        video = segment.get("video") or segment.get("scene_id", "")
        reason = segment.get("reason", "")
        claims = segment.get("claims", [])

        # 1. Check forbidden claims in claims/reason
        forbidden_claims = story_facts.get("forbidden_claims", [
            "A murder mystery",
            "A revenge thriller",
            "A love story between Randhir and Sunita",
        ])
        forbidden_patterns = story_facts.get("forbidden_claim_patterns", [
            r"\bmurder\b",
            r"\brevenge\b",
            r"\bspouse\b",
            r"\bhusband\b",
            r"\bwife\b",
        ])

        combined_text = f"{reason} {' '.join(str(c) for c in claims)}"

        for fc in forbidden_claims:
            if fc.lower() in combined_text.lower():
                errors.append(
                    ValidationError(
                        code="STORY_FORBIDDEN_CLAIM",
                        rule_id="POL-STORY-001",
                        segment_id=sid,
                        message=f"Segment contains forbidden claim {fc!r}",
                        evidence=[f"claim:{fc}"],
                        repairable=True,
                    )
                )

        import re
        for pat in forbidden_patterns:
            if re.search(pat, combined_text, re.IGNORECASE):
                errors.append(
                    ValidationError(
                        code="STORY_FORBIDDEN_CLAIM",
                        rule_id="POL-STORY-001",
                        segment_id=sid,
                        message=f"Segment matches forbidden claim pattern {pat!r}",
                        evidence=[f"pattern:{pat}"],
                        repairable=True,
                    )
                )
                break

        # 2. Check relationship claims against public story map relationships
        # Build public relationships index
        public_rels: dict[tuple[str, str], str] = {}
        for r in story_map.get("relationships", []):
            if isinstance(r, dict):
                a = r.get("a", "")
                b = r.get("b", "")
                rel = r.get("relation", "")
                vis = r.get("visibility", "public")
            else:
                a = getattr(r, "a", "")
                b = getattr(r, "b", "")
                rel = getattr(r, "relation", "")
                vis = getattr(r, "visibility", "public")
            if vis in ("public", "PUBLIC"):
                public_rels[tuple(sorted([a, b]))] = rel

        for cl in claims:
            cl_dict = cl.model_dump() if hasattr(cl, "model_dump") else (cl if isinstance(cl, dict) else {})
            ctype = cl_dict.get("type", "")
            cval = cl_dict.get("value", "")
            sup = cl_dict.get("supported_by", [])

            # Check unsupported claims
            if not sup:
                errors.append(
                    ValidationError(
                        code="STORY_UNSUPPORTED_CLAIM",
                        rule_id="POL-STORY-003",
                        segment_id=sid,
                        message=f"Claim {cval!r} has no supporting evidence refs",
                        evidence=[f"claim:{cval}"],
                        repairable=True,
                    )
                )
            else:
                # Check that supported_by refs resolve
                all_eids = set(evidence_index.get("all_evidence_ids", []))
                for sref in sup:
                    if sref not in all_eids and not sref.startswith("scene:"):
                        errors.append(
                            ValidationError(
                                code="STORY_UNSUPPORTED_CLAIM",
                                rule_id="POL-STORY-003",
                                segment_id=sid,
                                message=f"Claim {cval!r} references unresolved evidence {sref!r}",
                                evidence=[sref],
                                repairable=True,
                            )
                        )

            # Check relationship claim
            if ctype in ("relationship", "relation") or "relation" in cl_dict:
                # e.g. relation="spouse", chars=["char_randhir", "char_sunita"]
                claimed_rel = cl_dict.get("relation", cval)
                chars = cl_dict.get("characters", [])
                if len(chars) >= 2:
                    pair = tuple(sorted([chars[0], chars[1]]))
                    true_rel = public_rels.get(pair)
                    if true_rel and claimed_rel != true_rel:
                        errors.append(
                            ValidationError(
                                code="STORY_RELATION_MISMATCH",
                                rule_id="POL-STORY-002",
                                segment_id=sid,
                                message=f"Claimed relationship {claimed_rel!r} for {pair} contradicts editorial truth {true_rel!r}",
                                evidence=[f"char:{pair[0]}", f"char:{pair[1]}"],
                                repairable=True,
                            )
                        )
                # Specific check for Randhir & Sunita spouse claim
                if ("randhir" in combined_text.lower() and "sunita" in combined_text.lower()) and (
                    "spouse" in combined_text.lower() or "husband" in combined_text.lower() or "wife" in combined_text.lower() or claimed_rel in ("spouse", "husband_wife")
                ):
                    errors.append(
                        ValidationError(
                            code="STORY_RELATION_MISMATCH",
                            rule_id="POL-STORY-002",
                            segment_id=sid,
                            message="Randhir and Sunita falsely described as spouses/married",
                            evidence=["chars:char_randhir,char_sunita"],
                            repairable=True,
                        )
                    )

            # Check genre claim
            if ctype == "genre":
                permitted = set(story_facts.get("permitted_genres", DEFAULT_PERMITTED_GENRES))
                if cval not in permitted:
                    errors.append(
                        ValidationError(
                            code="STORY_GENRE_MISMATCH",
                            rule_id="POL-STORY-004",
                            segment_id=sid,
                            message=f"Claimed genre {cval!r} not in permitted genres {sorted(permitted)}",
                            evidence=[f"genre:{cval}"],
                            repairable=True,
                        )
                    )

        status = ValidatorStatus.FAIL if errors else ValidatorStatus.PASS

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
        story_map: dict[str, Any],
        story_facts: dict[str, Any],
        evidence_index: dict[str, Any],
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment and plan-level story truth validation.
        """
        results: dict[str, ValidatorResult] = {}
        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(seg_dict, story_map, story_facts, evidence_index)

        # Plan-level tagline and genre checks
        plan_errors: list[ValidationError] = []
        plan_warnings: list[ValidationWarning] = []
        tagline = plan.get("tagline", "")

        forbidden_taglines = [
            "a murder no one can forget",
            "a murder mystery",
            "a revenge thriller",
        ]
        for ft in forbidden_taglines:
            if ft in tagline.lower():
                plan_errors.append(
                    ValidationError(
                        code="STORY_FORBIDDEN_CLAIM",
                        rule_id="POL-STORY-001",
                        segment_id="__plan__",
                        message=f"Tagline contains clickbait/forbidden claim: {tagline!r}",
                        evidence=[f"tagline:{tagline}"],
                        repairable=True,
                    )
                )

        plan_status = ValidatorStatus.FAIL if plan_errors else ValidatorStatus.PASS
        results["__plan__"] = ValidatorResult(
            validator=self.name,
            status=plan_status,
            errors=plan_errors,
            warnings=plan_warnings,
            evidence=[],
        )

        return results
