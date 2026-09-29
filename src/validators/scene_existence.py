"""
Validator 1 — SceneExistenceValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.1.

Checks:
  - segment.video ∈ scenes.json
  - every evidence ref resolves (scene, dialogue, cue, contract, fact)
  - trailer_id, audience, segment_id valid and unique
  - subtitle.cue_ids exist

Error codes (all repairable by replacing the segment):
  SCENE_NOT_FOUND
  EVIDENCE_REF_UNRESOLVED
  CUE_NOT_FOUND
  DUPLICATE_SEGMENT_ID

Segments failing this validator cause dependent validators to mark
the segment SKIPPED with blocked_by="SceneExistenceValidator".
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    VALID_AUDIENCE_IDS,
    VALID_TRAILER_IDS,
)


class SceneExistenceValidator:
    """
    Deterministic. Imports no planner or LLM code.
    """

    name = "SceneExistenceValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        evidence_index: dict[str, Any],
        constraint_map: dict[str, Any],
        seen_segment_ids: set[str],
    ) -> ValidatorResult:
        """
        Validate one segment for scene/evidence existence.
        Returns a ValidatorResult with status PASS, WARN, or FAIL.
        """
        errors: list[ValidationError] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        video = segment.get("video") or segment.get("scene_id", "")

        # 1. Check duplicate segment_id
        if sid in seen_segment_ids:
            errors.append(
                ValidationError(
                    code="DUPLICATE_SEGMENT_ID",
                    rule_id="STRUCT-001",
                    segment_id=sid,
                    message=f"Duplicate segment ID {sid!r} within trailer plan",
                    evidence=[f"segment:{sid}"],
                    repairable=True,
                )
            )
        else:
            seen_segment_ids.add(sid)

        # 2. Check segment.video resolves to a known scene
        scenes_map = evidence_index.get("by_scene", {})
        if video not in scenes_map:
            errors.append(
                ValidationError(
                    code="SCENE_NOT_FOUND",
                    rule_id="STRUCT-SCENE-001",
                    segment_id=sid,
                    message=f"Segment references scene {video!r} which does not exist in episode",
                    evidence=[f"scene:{video}"],
                    repairable=True,
                )
            )
        else:
            evidence.append(f"scene:{video}")

        # 3. Check evidence refs resolve
        all_eids = set(evidence_index.get("all_evidence_ids", []))
        # Add basic known patterns if not indexed
        for ref in segment.get("evidence", []):
            if ref in all_eids:
                evidence.append(ref)
            else:
                # Check if it starts with valid prefix
                parts = ref.split(":", 1)
                prefix = parts[0]
                ident = parts[1] if len(parts) > 1 else ""
                valid = False
                if prefix == "scene" and ident in scenes_map:
                    valid = True
                elif prefix == "contract" and ident in evidence_index.get("by_contract", {}):
                    valid = True
                elif prefix == "policy" and ident in evidence_index.get("by_policy", {}):
                    valid = True
                elif prefix == "fact" and ident in evidence_index.get("by_fact", {}):
                    valid = True
                elif prefix == "cue":
                    # Check across scenes
                    for s_data in scenes_map.values():
                        for track_cues in s_data.get("subtitle_cues", {}).values():
                            if any(c.get("cue_id") == ident for c in track_cues):
                                valid = True
                                break
                elif prefix == "history":
                    valid = True

                if valid:
                    evidence.append(ref)
                else:
                    errors.append(
                        ValidationError(
                            code="EVIDENCE_REF_UNRESOLVED",
                            rule_id="STRUCT-EV-001",
                            segment_id=sid,
                            message=f"Evidence ref {ref!r} cannot be resolved in evidence index",
                            evidence=[ref],
                            repairable=True,
                        )
                    )

        # 4. Check subtitle.cue_ids resolve
        sub = segment.get("subtitle", {})
        cue_ids = sub.get("cue_ids", []) if isinstance(sub, dict) else getattr(sub, "cue_ids", [])
        if cue_ids and video in scenes_map:
            scene_cues = scenes_map[video].get("subtitle_cues", {})
            known_scene_cue_ids = {
                c.get("cue_id")
                for track_cues in scene_cues.values()
                for c in track_cues
            }
            for cid in cue_ids:
                if cid not in known_scene_cue_ids:
                    errors.append(
                        ValidationError(
                            code="CUE_NOT_FOUND",
                            rule_id="STRUCT-CUE-001",
                            segment_id=sid,
                            message=f"Subtitle cue {cid!r} not found in scene {video}",
                            evidence=[f"cue:{cid}", f"scene:{video}"],
                            repairable=True,
                        )
                    )

        status = ValidatorStatus.FAIL if errors else ValidatorStatus.PASS

        return ValidatorResult(
            validator=self.name,
            status=status,
            errors=errors,
            warnings=[],
            evidence=sorted(set(evidence)),
        )

    def validate(
        self,
        plan: dict[str, Any],
        evidence_index: dict[str, Any],
        constraint_map: dict[str, Any],
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment validation for an entire trailer plan.
        Returns {segment_id: ValidatorResult}.
        """
        results: dict[str, ValidatorResult] = {}
        seen_ids: set[str] = set()

        segments = plan.get("segments", [])
        for seg in segments:
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(seg_dict, evidence_index, constraint_map, seen_ids)

        plan_errors: list[ValidationError] = []
        tid = plan.get("trailer_id")
        aud = plan.get("audience")

        if tid and tid not in VALID_TRAILER_IDS:
            plan_errors.append(
                ValidationError(
                    code="TRAILER_ID_INVALID",
                    rule_id="STRUCT-002",
                    segment_id="__plan__",
                    message=f"Trailer ID {tid!r} is invalid. Must be one of {sorted(VALID_TRAILER_IDS)}",
                    evidence=[f"trailer_id:{tid}"],
                    repairable=False,
                )
            )

        if aud and aud not in VALID_AUDIENCE_IDS:
            plan_errors.append(
                ValidationError(
                    code="AUDIENCE_INVALID",
                    rule_id="STRUCT-003",
                    segment_id="__plan__",
                    message=f"Audience ID {aud!r} is invalid. Must be one of {sorted(VALID_AUDIENCE_IDS)}",
                    evidence=[f"audience:{aud}"],
                    repairable=False,
                )
            )

        if plan_errors:
            results["__plan__"] = ValidatorResult(
                validator=self.name,
                status=ValidatorStatus.FAIL,
                errors=plan_errors,
                warnings=[],
                evidence=[],
            )

        return results
