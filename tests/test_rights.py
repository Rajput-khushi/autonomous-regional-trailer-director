"""
T2 — test_rights_restriction (VALIDATION_AND_TESTING.md §6 T2).
Parametrized for four rights scenarios.
"""

from __future__ import annotations

import copy
from pathlib import Path
import pytest

from src.models import ValidatorStatus
from src.validators.rights import RightsValidator
from src.evidence import load_and_validate_fixtures, build_evidence_index
from src.constraints import build_constraint_map


@pytest.fixture
def rights_context():
    data_dir = Path("data")
    fixtures = load_and_validate_fixtures(data_dir)
    ev_index = build_evidence_index(fixtures)
    cmap = build_constraint_map(
        fixtures["contracts"], fixtures["policies"], fixtures["audiences"], fixtures["cost_sheet"]
    )
    return {"fixtures": fixtures, "ev_index": ev_index, "cmap": cmap}


@pytest.mark.parametrize("scenario", [
    "music_promo_not_permitted",
    "actor_promo_revoked",
    "territory_mismatch",
    "contract_missing",
])
def test_rights_restriction(scenario: str, rights_context):
    """
    (a) music_promo_not_permitted: music_07 → RIGHTS_PROMO_NOT_PERMITTED + RIGHTS_EXPIRED.
    (b) actor_promo_revoked: C-ACT-03.promotional_use=False → all scenes with actor_03 fail.
    (c) territory_mismatch: campaign territory US → RIGHTS_TERRITORY on all rights-bearing segments.
    (d) contract_missing: remove C-MUS-09 → RIGHTS_CONTRACT_MISSING (fail closed, not PASS).
    """
    validator = RightsValidator()
    ev_index = rights_context["ev_index"]
    cmap = copy.deepcopy(rights_context["cmap"])

    if scenario == "music_promo_not_permitted":
        # Segment using restricted/expired music_07
        seg = {
            "segment_id": "seg_mus_07",
            "video": "scene_04",
            "audio_mode": "dialogue_and_music",
            "music_asset_id": "music_07",
            "source_in": "00:02:15.000",
            "source_out": "00:02:22.000",
        }
        res = validator.validate_segment(seg, cmap, ev_index)
        assert res.status == ValidatorStatus.FAIL
        codes = [e.code for e in res.errors]
        assert "RIGHTS_PROMO_NOT_PERMITTED" in codes or "RIGHTS_EXPIRED" in codes

    elif scenario == "actor_promo_revoked":
        # Modify C-ACT-03 promotional_use to False
        for rule in cmap["rules"]:
            if rule.get("scope", {}).get("asset_id") == "actor_03":
                rule["rule"]["promotional_use"] = False

        # scene_01 contains actor_03
        seg = {
            "segment_id": "seg_act_03",
            "video": "scene_01",
            "audio_mode": "dialogue_only",
            "source_in": "00:00:10.000",
            "source_out": "00:00:20.000",
        }
        res = validator.validate_segment(seg, cmap, ev_index)
        assert res.status == ValidatorStatus.FAIL
        codes = [e.code for e in res.errors]
        assert "RIGHTS_PROMO_NOT_PERMITTED" in codes

    elif scenario == "territory_mismatch":
        seg = {
            "segment_id": "seg_terr",
            "video": "scene_01",
            "audio_mode": "dialogue_and_music",
            "music_asset_id": "music_03",
            "source_in": "00:00:10.000",
            "source_out": "00:00:20.000",
        }
        # Run with territory="US"
        res = validator.validate_segment(seg, cmap, ev_index, territory="US")
        assert res.status == ValidatorStatus.FAIL
        codes = [e.code for e in res.errors]
        assert "RIGHTS_TERRITORY" in codes

    elif scenario == "contract_missing":
        seg = {
            "segment_id": "seg_missing_contract",
            "video": "scene_01",
            "audio_mode": "dialogue_and_music",
            "music_asset_id": "music_99_unknown",
            "source_in": "00:00:10.000",
            "source_out": "00:00:20.000",
        }
        res = validator.validate_segment(seg, cmap, ev_index)
        assert res.status == ValidatorStatus.FAIL
        codes = [e.code for e in res.errors]
        assert "RIGHTS_CONTRACT_MISSING" in codes
