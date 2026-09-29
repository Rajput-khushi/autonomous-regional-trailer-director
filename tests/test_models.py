"""
test_models.py — Phase 1 model tests.
Authority: IMPLEMENTATION_PLAN.md §1, VALIDATION_AND_TESTING.md §6.

Coverage:
  - Valid construction of every major model (positive tests)
  - Rejection of malformed/invalid inputs (negative tests)
  - Enum vocabulary completeness
  - Timecode format validation
  - Interval order validation (source_in < source_out)
  - Audience ID and Trailer ID validation
  - music_asset_id required for music audio modes

No business logic or validator behavior is tested here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.models import (
    Audience,
    AudiencePromise,
    Campaign,
    ChangeEvent,
    ChangeEventType,
    ChangeTarget,
    CharacterRecord,
    Confidence,
    Contract,
    ContractsFile,
    CostProfile,
    CostRates,
    CostSheet,
    DecisionLogEntry,
    DialectCue,
    DialogueLine,
    Episode,
    FallbackPlan,
    HistoricPerformance,
    HumanReviewItem,
    MajorEvent,
    NativeReviewStatus,
    Policy,
    PoliciesFile,
    ProtectedFact,
    RelationshipRecord,
    RevealWindow,
    RevisionRecord,
    RunState,
    Scene,
    ScenesFile,
    SegmentClaim,
    SensitivityWindow,
    SourceCue,
    SpoilerFact,
    SpoilerLevel,
    SpoilerMap,
    StoryFacts,
    StoryMap,
    SubtitleRef,
    SubtitlesFile,
    SubtitleTracks,
    TrailerDurationWindow,
    TrailerPlan,
    TrailerSegment,
    TrailerStatus,
    TrailerValidationResult,
    ValidationError,
    ValidationWarning,
    ValidatorResult,
    ValidatorStatus,
    Visibility,
    AudioMode,
    ConstraintCategory,
)

# ══════════════════════════════════════════════════════════════════════════════
# Fixtures (shared objects for positive tests)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def min_episode() -> dict:
    return {
        "synthetic": True,
        "episode_id": "ep_01",
        "duration": "00:06:00.000",
        "source_language": "hi",
        "content_rating": "UA13+",
        "evaluation_date": "2026-09-29",
        "campaign": {"territory": "IN", "start": "2026-10-05", "end": "2026-11-05"},
        "trailer_duration_window": {
            "hard_min_s": 20, "hard_max_s": 60,
            "target_min_s": 30, "target_max_s": 45,
        },
    }


@pytest.fixture
def min_scene() -> dict:
    return {
        "synthetic": True,
        "scene_id": "scene_01",
        "in": "00:00:00.000",
        "out": "00:00:40.000",
        "description": "Opening scene",
        "emotion": "warmth",
        "spoiler_level": "NONE",
    }


@pytest.fixture
def min_subtitle_cue() -> dict:
    """A minimal valid source (hi) cue."""
    return {
        "cue_id": "sub_hi_004_01",
        "scene_id": "scene_04",
        "in": "00:02:13.000",
        "out": "00:02:17.000",
        "text": "Chitthi kahan hai, Bhaiya?",
        "gloss_en": "Where is the letter, brother?",
        "meaning_tags": ["question", "missing_letter", "sibling_address"],
        "source_line_id": "line_004_01",
    }


@pytest.fixture
def min_segment() -> dict:
    return {
        "segment_id": "segment_01",
        "role": "hook_humour",
        "source_in": "00:00:50.000",
        "source_out": "00:01:00.000",
        "video": "scene_02",
        "audio_mode": "dialogue_only",
        "subtitle": {"track": "hi", "cue_ids": ["sub_hi_002_03"], "text": "Sample dialogue."},
        "reason": "Opens with warmth and humour",
        "evidence": ["scene:scene_02", "cue:sub_hi_002_03"],
    }


@pytest.fixture
def min_trailer_plan(min_segment: dict) -> dict:
    return {
        "synthetic": True,
        "trailer_id": "family_v1",
        "audience": "family",
        "revision": 0,
        "duration_seconds": 38.0,
        "audience_promise": "Warmth, stakes and broad entertainment value",
        "emotional_journey": ["warmth", "curiosity", "conflict"],
        "tagline": "One family. One secret.",
        "transitions": ["CUT", "CUT", "DISSOLVE"],
        "segments": [min_segment],
    }


@pytest.fixture
def min_validator_result() -> dict:
    return {
        "validator": "SceneExistenceValidator",
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "evidence": ["scene:scene_01"],
    }


@pytest.fixture
def min_change_event() -> dict:
    return {
        "synthetic": True,
        "event_id": "chg_001",
        "type": "CONTRACT_UPDATE",
        "target": {"kind": "contract", "id": "music_03"},
        "patch": {"valid_until": "2026-09-01"},
        "description": "Synthetic: rights for music_03 expired.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# §1  Positive tests — valid construction
# ══════════════════════════════════════════════════════════════════════════════

class TestValidEpisode:
    def test_basic_construction(self, min_episode: dict):
        ep = Episode(**min_episode)
        assert ep.episode_id == "ep_01"
        assert ep.synthetic is True
        assert ep.duration == "00:06:00.000"

    def test_campaign_nested(self, min_episode: dict):
        ep = Episode(**min_episode)
        assert ep.campaign.territory == "IN"
        assert ep.campaign.start == "2026-10-05"

    def test_trailer_duration_window(self, min_episode: dict):
        ep = Episode(**min_episode)
        assert ep.trailer_duration_window.hard_min_s == 20
        assert ep.trailer_duration_window.hard_max_s == 60

    def test_optional_fields_default(self, min_episode: dict):
        ep = Episode(**min_episode)
        assert ep.media_path is None
        assert ep.series_title == ""


class TestValidScene:
    def test_basic_construction(self, min_scene: dict):
        s = Scene(**min_scene)
        assert s.scene_id == "scene_01"
        assert s.source_in == "00:00:00.000"
        assert s.source_out == "00:00:40.000"

    def test_spoiler_level_enum(self, min_scene: dict):
        s = Scene(**min_scene)
        assert s.spoiler_level == SpoilerLevel.NONE

    def test_sensitivity_flags_empty(self, min_scene: dict):
        s = Scene(**min_scene)
        assert s.sensitivity_flags == []

    def test_full_scene_with_flags(self, min_scene: dict):
        min_scene["sensitivity_flags"] = [
            {"flag": "PHYSICAL_AGGRESSION_MODERATE", "in": "00:04:00.000", "out": "00:04:15.000"}
        ]
        s = Scene(**min_scene)
        assert len(s.sensitivity_flags) == 1

    def test_audio_only_key_info_default_false(self, min_scene: dict):
        s = Scene(**min_scene)
        assert s.audio_only_key_info is False


class TestValidSubtitleCue:
    def test_source_cue_construction(self, min_subtitle_cue: dict):
        cue = SourceCue(**min_subtitle_cue)
        assert cue.cue_id == "sub_hi_004_01"
        assert cue.scene_id == "scene_04"
        assert cue.source_in == "00:02:13.000"
        assert cue.source_out == "00:02:17.000"

    def test_meaning_tags(self, min_subtitle_cue: dict):
        cue = SourceCue(**min_subtitle_cue)
        assert "question" in cue.meaning_tags
        assert "missing_letter" in cue.meaning_tags

    def test_dialect_cue_construction(self):
        cue = DialectCue(
            cue_id="sub_bgc_004_01",
            scene_id="scene_04",
            **{"in": "00:02:13.000", "out": "00:02:17.000"},
            text="[bgc placeholder] Chitthi kit se, Bhaiya?",
            aligns_with="sub_hi_004_01",
            meaning_tags=["question", "missing_letter", "sibling_address"],
            stereotype_flags=[],
            native_review="PENDING",
        )
        assert cue.cue_id == "sub_bgc_004_01"
        assert cue.aligns_with == "sub_hi_004_01"
        assert cue.native_review == NativeReviewStatus.PENDING

    def test_subtitles_file_all_tracks(self, min_subtitle_cue: dict):
        sf = SubtitlesFile(
            synthetic=True,
            tracks=SubtitleTracks(
                hi=[SourceCue(**min_subtitle_cue)],
                bgc=[],
                raj=[],
            )
        )
        assert len(sf.tracks.hi) == 1
        assert sf.tracks.bgc == []
        assert sf.tracks.raj == []


class TestValidTrailerPlan:
    def test_construction(self, min_trailer_plan: dict):
        plan = TrailerPlan(**min_trailer_plan)
        assert plan.trailer_id == "family_v1"
        assert plan.audience == "family"
        assert len(plan.segments) == 1

    def test_all_three_trailer_ids(self, min_trailer_plan: dict):
        for tid, aud in [
            ("family_v1", "family"),
            ("young_adult_v1", "young_adult"),
            ("dialect_region_v1", "dialect_region"),
        ]:
            plan = TrailerPlan(**{**min_trailer_plan, "trailer_id": tid, "audience": aud})
            assert plan.trailer_id == tid

    def test_optional_fields_defaults(self, min_trailer_plan: dict):
        plan = TrailerPlan(**min_trailer_plan)
        assert plan.voice_over is None
        assert plan.text_cards == []
        assert plan.fallback_plan is None

    def test_with_fallback_plan(self, min_trailer_plan: dict):
        min_trailer_plan["fallback_plan"] = {"profile": "lite", "estimated_cost": 0.13}
        plan = TrailerPlan(**min_trailer_plan)
        assert plan.fallback_plan is not None
        assert plan.fallback_plan.profile == "lite"

    def test_with_music_segment(self, min_trailer_plan: dict):
        seg = min_trailer_plan["segments"][0].copy()
        seg["audio_mode"] = "dialogue_and_music"
        seg["music_asset_id"] = "music_03"
        seg["segment_id"] = "segment_02"
        seg["source_in"] = "00:00:20.000"
        seg["source_out"] = "00:00:30.000"
        min_trailer_plan["segments"] = [seg]
        plan = TrailerPlan(**min_trailer_plan)
        assert plan.segments[0].music_asset_id == "music_03"


class TestValidSegment:
    def test_basic_construction(self, min_segment: dict):
        seg = TrailerSegment(**min_segment)
        assert seg.segment_id == "segment_01"
        assert seg.audio_mode == AudioMode.DIALOGUE_ONLY
        assert seg.confidence == Confidence.HIGH

    def test_all_audio_modes(self, min_segment: dict):
        for mode in ["dialogue_only", "silent"]:
            s = TrailerSegment(**{**min_segment, "audio_mode": mode, "segment_id": "seg_x"})
            assert s.audio_mode.value == mode

    def test_dialogue_and_music_with_asset(self, min_segment: dict):
        seg = TrailerSegment(**{
            **min_segment,
            "audio_mode": "dialogue_and_music",
            "music_asset_id": "music_03",
        })
        assert seg.music_asset_id == "music_03"

    def test_with_claims(self, min_segment: dict):
        min_segment["claims"] = [{
            "type": "relationship",
            "subject": "char_dharam",
            "object": "char_sunita",
            "relation": "sibling",
            "supported_by": ["scene:scene_04"],
        }]
        seg = TrailerSegment(**min_segment)
        assert len(seg.claims) == 1
        assert seg.claims[0].relation == "sibling"

    def test_risk_flags_and_framing_tags(self, min_segment: dict):
        min_segment["risk_flags"] = ["INJECTION_DETECTED"]
        min_segment["framing_tags"] = ["warm_family"]
        seg = TrailerSegment(**min_segment)
        assert "INJECTION_DETECTED" in seg.risk_flags
        assert "warm_family" in seg.framing_tags

    def test_subtitle_ref_construction(self):
        ref = SubtitleRef(track="bgc", cue_ids=["sub_bgc_004_03"], text="[bgc placeholder] …")
        assert ref.track == "bgc"
        assert ref.cue_ids == ["sub_bgc_004_03"]


class TestValidValidationResult:
    def test_pass_result(self, min_validator_result: dict):
        result = ValidatorResult(**min_validator_result)
        assert result.status == ValidatorStatus.PASS
        assert result.errors == []

    def test_fail_result_with_error(self):
        result = ValidatorResult(
            validator="SpoilerValidator",
            status=ValidatorStatus.FAIL,
            errors=[ValidationError(
                code="SPOILER_MAJOR",
                rule_id="POL-SPOILER-001",
                segment_id="segment_03",
                message="Segment overlaps reveal window of F01.",
                evidence=["fact:F01", "scene:scene_07"],
                repairable=True,
            )],
            warnings=[],
            evidence=["fact:F01"],
        )
        assert result.status == ValidatorStatus.FAIL
        assert result.errors[0].code == "SPOILER_MAJOR"
        assert result.errors[0].repairable is True

    def test_skipped_result(self):
        result = ValidatorResult(
            validator="RightsValidator",
            status=ValidatorStatus.SKIPPED,
            blocked_by="SceneExistenceValidator",
        )
        assert result.status == ValidatorStatus.SKIPPED
        assert result.blocked_by == "SceneExistenceValidator"

    def test_warn_result(self):
        result = ValidatorResult(
            validator="TimecodeValidator",
            status=ValidatorStatus.WARN,
            warnings=[ValidationWarning(
                code="DURATION_OUTSIDE_TARGET",
                message="Duration is outside 30-45s target.",
            )],
        )
        assert result.status == ValidatorStatus.WARN

    def test_trailer_validation_result(self, min_validator_result: dict):
        tvr = TrailerValidationResult(
            trailer_id="family_v1",
            status=TrailerStatus.PASS,
            validators=[ValidatorResult(**min_validator_result)],
            human_review_required=False,
            repair_attempts={},
        )
        assert tvr.trailer_id == "family_v1"
        assert tvr.status == TrailerStatus.PASS


class TestValidChangeEvent:
    def test_contract_update(self, min_change_event: dict):
        ev = ChangeEvent(**min_change_event)
        assert ev.event_id == "chg_001"
        assert ev.type == ChangeEventType.CONTRACT_UPDATE
        assert ev.target.kind == "contract"
        assert ev.target.id == "music_03"
        assert ev.patch == {"valid_until": "2026-09-01"}

    def test_all_change_event_types(self):
        for etype in ChangeEventType:
            ev = ChangeEvent(
                synthetic=True,
                event_id="chg_test",
                type=etype,
                target=ChangeTarget(kind="contract", id="music_03"),
                patch={},
            )
            assert ev.type == etype

    def test_policy_update(self):
        ev = ChangeEvent(
            synthetic=True,
            event_id="chg_002",
            type=ChangeEventType.POLICY_UPDATE,
            target=ChangeTarget(kind="policy", id="POL-SPOILER-001"),
            patch={"rule": {"MEDIUM": "FAIL"}},
        )
        assert ev.type == ChangeEventType.POLICY_UPDATE


# ══════════════════════════════════════════════════════════════════════════════
# §2  Negative tests — rejection of invalid inputs
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingRequiredFields:
    def test_episode_missing_episode_id(self, min_episode: dict):
        del min_episode["episode_id"]
        with pytest.raises(PydanticValidationError):
            Episode(**min_episode)

    def test_scene_missing_scene_id(self, min_scene: dict):
        del min_scene["scene_id"]
        with pytest.raises(PydanticValidationError):
            Scene(**min_scene)

    def test_segment_missing_role(self, min_segment: dict):
        del min_segment["role"]
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_segment_missing_video(self, min_segment: dict):
        del min_segment["video"]
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_trailer_plan_missing_audience_promise(self, min_trailer_plan: dict):
        del min_trailer_plan["audience_promise"]
        with pytest.raises(PydanticValidationError):
            TrailerPlan(**min_trailer_plan)

    def test_trailer_plan_missing_segments(self, min_trailer_plan: dict):
        del min_trailer_plan["segments"]
        with pytest.raises(PydanticValidationError):
            TrailerPlan(**min_trailer_plan)

    def test_change_event_missing_type(self, min_change_event: dict):
        del min_change_event["type"]
        with pytest.raises(PydanticValidationError):
            ChangeEvent(**min_change_event)

    def test_validator_result_missing_validator_name(self):
        with pytest.raises(PydanticValidationError):
            ValidatorResult(status="PASS")   # missing 'validator'

    def test_contract_missing_territories(self):
        with pytest.raises(PydanticValidationError):
            Contract(
                contract_id="C-MUS-03",
                asset_type="music",
                asset_id="music_03",
                promotional_use=True,
                valid_from="2025-01-01",
                valid_until="2027-12-31",
                # territories is required
            )


class TestInvalidEnumValues:
    def test_invalid_spoiler_level(self, min_scene: dict):
        min_scene["spoiler_level"] = "CRITICAL"  # not a valid SpoilerLevel
        with pytest.raises(PydanticValidationError):
            Scene(**min_scene)

    def test_invalid_validator_status(self, min_validator_result: dict):
        min_validator_result["status"] = "UNKNOWN"
        with pytest.raises(PydanticValidationError):
            ValidatorResult(**min_validator_result)

    def test_invalid_trailer_status(self):
        with pytest.raises(PydanticValidationError):
            TrailerValidationResult(
                trailer_id="family_v1",
                status="PENDING",   # not a valid TrailerStatus
            )

    def test_invalid_audio_mode(self, min_segment: dict):
        min_segment["audio_mode"] = "background_only"   # not a valid AudioMode
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_invalid_change_event_type(self, min_change_event: dict):
        min_change_event["type"] = "SCENE_UPDATE"   # not valid
        with pytest.raises(PydanticValidationError):
            ChangeEvent(**min_change_event)

    def test_invalid_native_review_status(self, min_subtitle_cue: dict):
        with pytest.raises(PydanticValidationError):
            DialectCue(
                cue_id="sub_bgc_001",
                scene_id="scene_01",
                **{"in": "00:00:09.000", "out": "00:00:13.000"},
                text="[bgc placeholder]",
                aligns_with="sub_hi_001_01",
                native_review="APPROVED",  # not valid
            )


class TestMalformedTimecode:
    def test_episode_bad_duration_format(self, min_episode: dict):
        min_episode["duration"] = "06:00"   # missing seconds and ms
        with pytest.raises(PydanticValidationError, match="HH:MM:SS.mmm"):
            Episode(**min_episode)

    def test_scene_bad_in_timecode(self, min_scene: dict):
        min_scene["in"] = "00:00:00"  # missing ms
        with pytest.raises(PydanticValidationError):
            Scene(**min_scene)

    def test_scene_bad_out_timecode(self, min_scene: dict):
        min_scene["out"] = "invalid"
        with pytest.raises(PydanticValidationError):
            Scene(**min_scene)

    def test_segment_bad_source_in(self, min_segment: dict):
        min_segment["source_in"] = "1:00.000"   # missing fields
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_source_cue_bad_in_format(self, min_subtitle_cue: dict):
        min_subtitle_cue["in"] = "02:13.000"   # missing hours
        with pytest.raises(PydanticValidationError):
            SourceCue(**min_subtitle_cue)

    def test_reveal_window_bad_timecode(self):
        with pytest.raises(PydanticValidationError):
            RevealWindow(**{"scene_id": "scene_07", "in": "4:50.000", "out": "05:10.000"})


class TestInvalidSourceInterval:
    def test_segment_in_equals_out(self, min_segment: dict):
        """source_in == source_out must fail (half-open interval must have content)."""
        min_segment["source_in"] = "00:01:00.000"
        min_segment["source_out"] = "00:01:00.000"
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_segment_in_greater_than_out(self, min_segment: dict):
        """source_in > source_out must fail."""
        min_segment["source_in"] = "00:01:10.000"
        min_segment["source_out"] = "00:01:00.000"
        with pytest.raises(PydanticValidationError):
            TrailerSegment(**min_segment)

    def test_segment_valid_touching_boundary_passes(self, min_segment: dict):
        """
        source_out of one segment == source_in of next is NOT a segment error
        (PD-4 governs interval OVERLAP, not the individual segment shape).
        """
        min_segment["source_in"] = "00:04:25.000"
        min_segment["source_out"] = "00:04:30.000"
        seg = TrailerSegment(**min_segment)
        assert seg.source_out == "00:04:30.000"


class TestInvalidAudienceId:
    def test_invalid_audience_id_in_audience_model(self):
        with pytest.raises(PydanticValidationError, match="audience_id"):
            Audience(
                audience_id="kids",   # not valid
                rating_ceiling="U",
                subtitle_track="hi",
            )

    def test_invalid_audience_in_trailer_plan(self, min_trailer_plan: dict):
        min_trailer_plan["audience"] = "premium"   # not valid
        with pytest.raises(PydanticValidationError, match="audience"):
            TrailerPlan(**min_trailer_plan)


class TestInvalidTrailerId:
    def test_invalid_trailer_id(self, min_trailer_plan: dict):
        min_trailer_plan["trailer_id"] = "kids_v1"   # not valid
        with pytest.raises(PydanticValidationError, match="trailer_id"):
            TrailerPlan(**min_trailer_plan)

    def test_trailer_id_empty_string(self, min_trailer_plan: dict):
        min_trailer_plan["trailer_id"] = ""
        with pytest.raises(PydanticValidationError):
            TrailerPlan(**min_trailer_plan)


class TestMusicAssetRequirement:
    def test_dialogue_and_music_without_asset_fails(self, min_segment: dict):
        min_segment["audio_mode"] = "dialogue_and_music"
        # music_asset_id not set → must fail
        with pytest.raises(PydanticValidationError, match="music_asset_id"):
            TrailerSegment(**min_segment)

    def test_music_only_without_asset_fails(self, min_segment: dict):
        min_segment["audio_mode"] = "music_only"
        with pytest.raises(PydanticValidationError, match="music_asset_id"):
            TrailerSegment(**min_segment)

    def test_dialogue_only_without_asset_passes(self, min_segment: dict):
        # Already the case in the fixture
        seg = TrailerSegment(**min_segment)
        assert seg.audio_mode == AudioMode.DIALOGUE_ONLY
        assert seg.music_asset_id is None

    def test_silent_without_asset_passes(self, min_segment: dict):
        min_segment["audio_mode"] = "silent"
        seg = TrailerSegment(**min_segment)
        assert seg.audio_mode == AudioMode.SILENT
        assert seg.music_asset_id is None


class TestInvalidSubtitleTrack:
    def test_subtitle_ref_invalid_track(self):
        with pytest.raises(PydanticValidationError, match="track"):
            SubtitleRef(track="fr", cue_ids=[], text="")

    def test_audience_invalid_subtitle_track(self):
        with pytest.raises(PydanticValidationError, match="subtitle_track"):
            Audience(
                audience_id="family",
                rating_ceiling="U",
                subtitle_track="fr",   # not valid
            )


# ══════════════════════════════════════════════════════════════════════════════
# §3  Enum vocabulary completeness tests
# ══════════════════════════════════════════════════════════════════════════════

class TestEnumVocabulary:
    def test_spoiler_level_values(self):
        assert {s.value for s in SpoilerLevel} == {"NONE", "LOW", "MEDIUM", "MAJOR"}

    def test_trailer_status_values(self):
        assert {s.value for s in TrailerStatus} == {
            "PASS", "PASS_WITH_WARNINGS", "REPAIR_REQUIRED", "REJECTED"
        }

    def test_validator_status_values(self):
        assert {s.value for s in ValidatorStatus} == {"PASS", "WARN", "FAIL", "SKIPPED"}

    def test_change_event_type_values(self):
        assert {t.value for t in ChangeEventType} == {
            "CONTRACT_UPDATE", "POLICY_UPDATE", "AUDIENCE_UPDATE",
            "EVIDENCE_UPDATE", "COST_UPDATE",
        }

    def test_audio_mode_values(self):
        assert {m.value for m in AudioMode} == {
            "dialogue_only", "dialogue_and_music", "music_only", "silent"
        }

    def test_confidence_values(self):
        assert {c.value for c in Confidence} == {"LOW", "MEDIUM", "HIGH"}

    def test_constraint_category_includes_timecode(self):
        """PD-13: TIMECODE is required."""
        assert ConstraintCategory.TIMECODE.value == "TIMECODE"

    def test_all_constraint_categories(self):
        expected = {
            "RATING", "RIGHTS", "TERRITORY", "ACTOR_PROMOTIONAL_USE",
            "MUSIC_PROMOTIONAL_USE", "SPOILER", "STORY_TRUTH", "DIALECT",
            "CULTURAL_RESPECT", "ACCESSIBILITY", "BUDGET", "TIMECODE",
        }
        assert {c.value for c in ConstraintCategory} == expected

    def test_visibility_values(self):
        assert {v.value for v in Visibility} == {"public", "protected"}

    def test_native_review_status_values(self):
        assert {n.value for n in NativeReviewStatus} == {"PENDING", "REVIEWED", "WAIVED"}


# ══════════════════════════════════════════════════════════════════════════════
# §4  Additional model construction tests
# ══════════════════════════════════════════════════════════════════════════════

class TestContractModel:
    def test_music_contract(self):
        c = Contract(
            contract_id="C-MUS-03",
            asset_type="music",
            asset_id="music_03",
            title="Harmonium Theme",
            mood_tags=["warm", "folk", "reflective"],
            promotional_use=True,
            territories=["IN"],
            valid_from="2025-01-01",
            valid_until="2027-12-31",
        )
        assert c.contract_id == "C-MUS-03"
        assert c.promotional_use is True

    def test_actor_contract(self):
        c = Contract(
            contract_id="C-ACT-01",
            asset_type="actor",
            asset_id="actor_01",
            promotional_use=True,
            territories=["IN"],
            valid_from="2025-01-01",
            valid_until="2027-06-30",
        )
        assert c.asset_type == "actor"
        assert "IN" in c.territories


class TestStoryFactsModel:
    def test_construction_with_all_fields(self):
        sf = StoryFacts(
            synthetic=True,
            characters=[
                CharacterRecord(char_id="char_sunita", name="Sunita", actor_id="actor_02", role="protagonist")
            ],
            relationships=[
                RelationshipRecord(a="char_dharam", b="char_sunita", relation="sibling", visibility="public")
            ],
            protected_facts=[
                ProtectedFact(
                    fact_id="F01",
                    spoiler_level=SpoilerLevel.MAJOR,
                    fact="The letter reveals Randhir is Sunita's biological father.",
                    reveal_windows=[
                        RevealWindow(**{"scene_id": "scene_07", "in": "00:04:50.000", "out": "00:05:10.000"})
                    ],
                    trigger_terms=["biological father", "her real father", "asli baap"],
                )
            ],
            permitted_genres=["family_drama", "mystery"],
            forbidden_claim_patterns=["murder", "killed"],
            major_events=[MajorEvent(event_id="E1", text="Sunita learns letter is missing", scene_id="scene_03")],
        )
        assert len(sf.protected_facts) == 1
        assert sf.protected_facts[0].fact_id == "F01"
        assert sf.protected_facts[0].spoiler_level == SpoilerLevel.MAJOR


class TestSpoilerMapModel:
    def test_spoiler_map_construction(self):
        sm = SpoilerMap(
            synthetic=True,
            facts=[
                SpoilerFact(
                    fact_id="F01",
                    fact="The letter reveals Randhir is Sunita's biological father.",
                    spoiler_level=SpoilerLevel.MAJOR,
                    source="editorial",
                    confidence=Confidence.HIGH,
                    reveal_windows=[
                        RevealWindow(**{"scene_id": "scene_07", "in": "00:04:50.000", "out": "00:05:10.000"})
                    ],
                    trigger_terms=["biological father"],
                )
            ],
            llm_added_candidates=[],
        )
        assert sm.facts[0].fact_id == "F01"
        assert sm.facts[0].source == "editorial"
        assert sm.llm_added_candidates == []


class TestRevisionRecord:
    def test_construction(self):
        r = RevisionRecord(
            revision=1,
            trigger="spoiler candidate in dialect_region_v1.segment_03",
            affected=["dialect_region_v1.segment_03"],
            unchanged=["family_v1.*", "young_adult_v1.*"],
            action="replace clip scene_07 00:04:48.000-00:04:56.000 -> scene_04 00:02:30.000-00:02:40.000",
            validators_rerun=["SceneExistence", "Spoiler"],
            validation="PASS_WITH_WARNINGS",
        )
        assert r.revision == 1
        assert "dialect_region_v1.segment_03" in r.affected


class TestDecisionLogEntry:
    def test_construction(self):
        entry = DecisionLogEntry(
            seq=17,
            type="REPAIR_APPLIED",
            node="repair",
            trailer_id="dialect_region_v1",
            segment_id="segment_03",
            reason="SPOILER_MAJOR (F01 window overlap)",
            evidence=["fact:F01", "scene:scene_07"],
            detail={"replaced_with": {"video": "scene_04"}},
        )
        assert entry.seq == 17
        assert entry.type == "REPAIR_APPLIED"
        assert entry.trailer_id == "dialect_region_v1"


class TestHumanReviewItem:
    def test_construction(self):
        item = HumanReviewItem(
            item_id="hr_001",
            trailer_id="dialect_region_v1",
            reason_code="NATIVE_REVIEW_PENDING",
            description="Dialect cue sub_bgc_004_03 has native_review: PENDING.",
            blocking=False,
        )
        assert item.blocking is False
        assert item.reason_code == "NATIVE_REVIEW_PENDING"

    def test_blocking_item(self):
        item = HumanReviewItem(
            item_id="hr_002",
            reason_code="REPAIR_EXHAUSTED",
            description="No valid replacement found for segment_03.",
            blocking=True,
        )
        assert item.blocking is True


class TestCostSheet:
    def test_full_and_lite_profiles(self):
        cs = CostSheet(
            synthetic=True,
            currency_unit="USD_synthetic",
            run_budget=2.00,
            rates=CostRates(),
            profiles={
                "full": CostProfile(
                    multimodal_scene_analysis=8,
                    story_analysis_call=1,
                    audience_call=3,
                    planning_call=3,
                    repair_rerank_call=6,
                ),
                "lite": CostProfile(
                    multimodal_scene_analysis=0,
                    story_analysis_call=1,
                    audience_call=1,
                    planning_call=1,
                    repair_rerank_call=0,
                ),
            },
            fallback_profile="lite",
        )
        assert cs.run_budget == 2.00
        assert cs.profiles["full"].multimodal_scene_analysis == 8
        assert cs.profiles["lite"].multimodal_scene_analysis == 0


class TestAudiencePromise:
    def test_construction(self):
        ap = AudiencePromise(
            audience_id="dialect_region",
            promise="A tense family mystery told in a familiar voice",
            required_beats=["familiar_voice", "mystery_hook", "conflict", "heart"],
            framing_tags=["familiar_voice", "family_relationships"],
            avoid_tags=["dialect_as_comedy", "stereotype_caricature", "location_assumption"],
            confidence=Confidence.MEDIUM,
        )
        assert ap.audience_id == "dialect_region"
        assert ap.confidence == Confidence.MEDIUM
