"""
Validator 3 — RightsValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.3, ARCHITECTURE.md §7.

Checks:
  - Music rights: if music is used, music_asset_id must exist, contract must exist,
    promotional_use must be true, territory must match campaign, validity dates
    must cover campaign window.
  - Actor rights: all actors in selected scene are conservatively treated as on-screen;
    contract must exist, promotional_use true, territory valid, validity covers campaign.

Error codes (all hard failures):
  RIGHTS_CONTRACT_MISSING
  RIGHTS_PROMO_NOT_PERMITTED
  RIGHTS_TERRITORY
  RIGHTS_NOT_YET_VALID
  RIGHTS_EXPIRED
  RIGHTS_MUSIC_UNSPECIFIED
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
)

DEFAULT_CAMPAIGN_START = "2026-10-05"
DEFAULT_CAMPAIGN_END = "2026-11-05"
DEFAULT_TERRITORY = "IN"

SCENE_ACTOR_MAP = {
    "scene_01": ["actor_01", "actor_02", "actor_03"],
    "scene_02": ["actor_01", "actor_02", "actor_03"],
    "scene_03": ["actor_02", "actor_04"],
    "scene_04": ["actor_01", "actor_02"],
    "scene_05": ["actor_02"],
    "scene_06": ["actor_01", "actor_03"],
    "scene_07": ["actor_01", "actor_02", "actor_03"],
    "scene_08": ["actor_01", "actor_02"],
}


class RightsValidator:
    """
    Deterministic. Imports no planner or LLM code.
    Uses ONLY compiled constraint_map and contract metadata.
    """

    name = "RightsValidator"

    def _get_contracts_index(self, constraint_map: dict[str, Any], evidence_index: dict[str, Any]) -> dict[str, dict[str, Any]]:
        contracts_idx: dict[str, dict[str, Any]] = {}

        # 1. From constraint_map rules
        for r in constraint_map.get("rules", []):
            scope = r.get("scope", {})
            aid = scope.get("asset_id") or r.get("source_ref")
            if aid:
                contracts_idx[aid] = r.get("rule", {})

        # 2. From evidence_index by_contract
        for aid, c_data in evidence_index.get("by_contract", {}).items():
            if aid not in contracts_idx or not contracts_idx[aid]:
                contracts_idx[aid] = c_data
            # Also key by contract_id
            cid = c_data.get("contract_id")
            if cid:
                contracts_idx[cid] = c_data

        return contracts_idx

    def validate_segment(
        self,
        segment: dict[str, Any],
        constraint_map: dict[str, Any],
        evidence_index: dict[str, Any],
        campaign_start: str = DEFAULT_CAMPAIGN_START,
        campaign_end: str = DEFAULT_CAMPAIGN_END,
        territory: str = DEFAULT_TERRITORY,
    ) -> ValidatorResult:
        """
        Validate rights for one segment.
        """
        errors: list[ValidationError] = []
        evidence: list[str] = []

        sid = segment.get("segment_id", "")
        video = segment.get("video") or segment.get("scene_id", "")
        audio_mode = segment.get("audio_mode", "dialogue_only")
        if hasattr(audio_mode, "value"):
            audio_mode = audio_mode.value

        contracts_idx = self._get_contracts_index(constraint_map, evidence_index)

        # 1. Music Rights
        uses_music = audio_mode in ("dialogue_and_music", "music_only")
        if uses_music:
            music_id = segment.get("music_asset_id")
            if not music_id:
                errors.append(
                    ValidationError(
                        code="RIGHTS_MUSIC_UNSPECIFIED",
                        rule_id="RIGHTS-MUS-001",
                        segment_id=sid,
                        message=f"Segment {sid} uses audio_mode {audio_mode!r} but specifies no music_asset_id",
                        evidence=[f"audio_mode:{audio_mode}"],
                        repairable=True,
                    )
                )
            else:
                contract = contracts_idx.get(music_id)
                if not contract:
                    # Fail closed on missing contract!
                    errors.append(
                        ValidationError(
                            code="RIGHTS_CONTRACT_MISSING",
                            rule_id="RIGHTS-MUS-002",
                            segment_id=sid,
                            message=f"Missing contract for music asset {music_id!r}",
                            evidence=[f"music:{music_id}"],
                            repairable=True,
                        )
                    )
                else:
                    evidence.append(f"contract:{music_id}")
                    # Check promotional_use
                    if not contract.get("promotional_use", False):
                        errors.append(
                            ValidationError(
                                code="RIGHTS_PROMO_NOT_PERMITTED",
                                rule_id="RIGHTS-MUS-003",
                                segment_id=sid,
                                message=f"Music asset {music_id!r} has promotional_use=False",
                                evidence=[f"contract:{music_id}"],
                                repairable=True,
                            )
                        )
                    # Check territory
                    allowed_terrs = contract.get("territories", [])
                    if territory not in allowed_terrs:
                        errors.append(
                            ValidationError(
                                code="RIGHTS_TERRITORY",
                                rule_id="RIGHTS-MUS-004",
                                segment_id=sid,
                                message=f"Music asset {music_id!r} territory {allowed_terrs} excludes campaign territory {territory}",
                                evidence=[f"contract:{music_id}", f"territory:{territory}"],
                                repairable=True,
                            )
                        )
                    # Check dates
                    vfrom = contract.get("valid_from", "")
                    vuntil = contract.get("valid_until", "")
                    if vfrom and vfrom > campaign_start:
                        errors.append(
                            ValidationError(
                                code="RIGHTS_NOT_YET_VALID",
                                rule_id="RIGHTS-MUS-005",
                                segment_id=sid,
                                message=f"Music asset {music_id!r} valid_from ({vfrom}) is after campaign_start ({campaign_start})",
                                evidence=[f"contract:{music_id}"],
                                repairable=True,
                            )
                        )
                    if vuntil and vuntil < campaign_end:
                        errors.append(
                            ValidationError(
                                code="RIGHTS_EXPIRED",
                                rule_id="RIGHTS-MUS-006",
                                segment_id=sid,
                                message=f"Music asset {music_id!r} valid_until ({vuntil}) is before campaign_end ({campaign_end})",
                                evidence=[f"contract:{music_id}"],
                                repairable=True,
                            )
                        )

        # 2. Actor Rights (conservative on-screen presence from scene)
        actors = SCENE_ACTOR_MAP.get(video, [])
        for act in actors:
            contract = contracts_idx.get(act)
            if not contract:
                # Fail closed on missing contract!
                errors.append(
                    ValidationError(
                        code="RIGHTS_CONTRACT_MISSING",
                        rule_id="RIGHTS-ACT-001",
                        segment_id=sid,
                        message=f"Missing appearance contract for actor {act!r} in scene {video}",
                        evidence=[f"actor:{act}", f"scene:{video}"],
                        repairable=True,
                    )
                )
            else:
                evidence.append(f"contract:{act}")
                if not contract.get("promotional_use", True):
                    errors.append(
                        ValidationError(
                            code="RIGHTS_PROMO_NOT_PERMITTED",
                            rule_id="RIGHTS-ACT-002",
                            segment_id=sid,
                            message=f"Actor {act!r} has promotional_use=False",
                            evidence=[f"contract:{act}"],
                            repairable=True,
                        )
                    )
                allowed_terrs = contract.get("territories", [])
                if allowed_terrs and territory not in allowed_terrs:
                    errors.append(
                        ValidationError(
                            code="RIGHTS_TERRITORY",
                            rule_id="RIGHTS-ACT-003",
                            segment_id=sid,
                            message=f"Actor {act!r} contract excludes territory {territory}",
                            evidence=[f"contract:{act}", f"territory:{territory}"],
                            repairable=True,
                        )
                    )
                vuntil = contract.get("valid_until", "")
                if vuntil and vuntil < campaign_end:
                    errors.append(
                        ValidationError(
                            code="RIGHTS_EXPIRED",
                            rule_id="RIGHTS-ACT-004",
                            segment_id=sid,
                            message=f"Actor {act!r} contract expired before campaign_end",
                            evidence=[f"contract:{act}"],
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
        campaign_start: str = DEFAULT_CAMPAIGN_START,
        campaign_end: str = DEFAULT_CAMPAIGN_END,
        territory: str = DEFAULT_TERRITORY,
    ) -> dict[str, ValidatorResult]:
        """
        Run per-segment rights validation for an entire trailer plan.
        Returns {segment_id: ValidatorResult}.
        """
        results: dict[str, ValidatorResult] = {}
        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(
                seg_dict, constraint_map, evidence_index, campaign_start, campaign_end, territory
            )
        return results
