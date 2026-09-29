"""
models.py — Complete Pydantic v2 models for all input fixtures and output artifacts.
Authority: DATA_SPEC.md (primary), SUMMARY.md §16, ARCHITECTURE.md §4, PROTOTYPE_SPEC.md §0.

Field names, types, enums and nested shapes follow DATA_SPEC.md exactly.
No business logic is implemented here; models are pure schemas.

⚠️  ALL DATA IS SYNTHETIC — see DATA_SPEC.md §0 notice.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


# ══════════════════════════════════════════════════════════════════════════════
# §0  Shared validators and helpers
# ══════════════════════════════════════════════════════════════════════════════

# HH:MM:SS.mmm — the canonical timecode format (DATA_SPEC.md §1)
_TC_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}$")

# Valid audience IDs (PROTOTYPE_SPEC.md §0)
VALID_AUDIENCE_IDS = frozenset({"family", "young_adult", "dialect_region"})

# Valid trailer IDs (PROTOTYPE_SPEC.md §0)
VALID_TRAILER_IDS = frozenset({"family_v1", "young_adult_v1", "dialect_region_v1"})

# Valid subtitle tracks (DATA_SPEC.md §7)
VALID_SUBTITLE_TRACKS = frozenset({"hi", "bgc", "raj"})


def _validate_timecode(tc: str) -> str:
    """Return tc unchanged if valid; raise ValueError otherwise."""
    if not _TC_RE.match(tc):
        raise ValueError(
            f"Timecode {tc!r} does not match required format HH:MM:SS.mmm"
        )
    return tc


# ══════════════════════════════════════════════════════════════════════════════
# §1  Enumerations
# ══════════════════════════════════════════════════════════════════════════════

class SpoilerLevel(str, Enum):
    """DATA_SPEC.md §10 / SUMMARY.md §12."""
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    MAJOR = "MAJOR"


class ValidatorStatus(str, Enum):
    """Per-validator status — VALIDATION_AND_TESTING.md §2."""
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"


class TrailerStatus(str, Enum):
    """Per-trailer / run status — VALIDATION_AND_TESTING.md §2, PROTOTYPE_SPEC.md §0."""
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REJECTED = "REJECTED"


class RunStatus(str, Enum):
    """Alias of TrailerStatus used at the run level (same vocabulary)."""
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    REJECTED = "REJECTED"


class ConstraintCategory(str, Enum):
    """Constraint map rule categories — SUMMARY.md §13, PD-13."""
    RATING = "RATING"
    RIGHTS = "RIGHTS"
    TERRITORY = "TERRITORY"
    ACTOR_PROMOTIONAL_USE = "ACTOR_PROMOTIONAL_USE"
    MUSIC_PROMOTIONAL_USE = "MUSIC_PROMOTIONAL_USE"
    SPOILER = "SPOILER"
    STORY_TRUTH = "STORY_TRUTH"
    DIALECT = "DIALECT"
    CULTURAL_RESPECT = "CULTURAL_RESPECT"
    ACCESSIBILITY = "ACCESSIBILITY"
    BUDGET = "BUDGET"
    TIMECODE = "TIMECODE"   # PD-13


class ChangeEventType(str, Enum):
    """Change event types — DATA_SPEC.md §19."""
    CONTRACT_UPDATE = "CONTRACT_UPDATE"
    POLICY_UPDATE = "POLICY_UPDATE"
    AUDIENCE_UPDATE = "AUDIENCE_UPDATE"
    EVIDENCE_UPDATE = "EVIDENCE_UPDATE"
    COST_UPDATE = "COST_UPDATE"


class AudioMode(str, Enum):
    """Audio mode for a trailer segment — DATA_SPEC.md §14."""
    DIALOGUE_ONLY = "dialogue_only"
    DIALOGUE_AND_MUSIC = "dialogue_and_music"
    MUSIC_ONLY = "music_only"
    SILENT = "silent"


class Confidence(str, Enum):
    """Categorical confidence — AI_SYSTEM_SPEC.md §3, §10."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class NativeReviewStatus(str, Enum):
    """Status of native-speaker review for dialect cues — DATA_SPEC.md §7."""
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    WAIVED = "WAIVED"


class Visibility(str, Enum):
    """Relationship visibility in the story map — DATA_SPEC.md §8."""
    PUBLIC = "public"
    PROTECTED = "protected"


# ══════════════════════════════════════════════════════════════════════════════
# §2  Episode manifest — DATA_SPEC.md §4
# ══════════════════════════════════════════════════════════════════════════════

class Campaign(BaseModel):
    """Campaign window and territory — DATA_SPEC.md §4."""
    territory: str
    start: str      # YYYY-MM-DD
    end: str        # YYYY-MM-DD


class TrailerDurationWindow(BaseModel):
    """Hard and target duration constraints — DATA_SPEC.md §4."""
    hard_min_s: float
    hard_max_s: float
    target_min_s: float
    target_max_s: float


class Episode(BaseModel):
    """
    Episode manifest — DATA_SPEC.md §4.
    Required: synthetic, episode_id, duration, source_language, content_rating,
              evaluation_date, campaign, trailer_duration_window.
    """
    synthetic: bool
    synthetic_notice: str = ""
    episode_id: str
    series_title: str = ""
    episode_title: str = ""
    duration: str           # HH:MM:SS.mmm
    source_language: str
    content_rating: str
    media_path: Optional[str] = None
    evaluation_date: str    # YYYY-MM-DD (fixed for determinism)
    campaign: Campaign
    trailer_duration_window: TrailerDurationWindow

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: str) -> str:
        return _validate_timecode(v)


# ══════════════════════════════════════════════════════════════════════════════
# §3  Scenes — DATA_SPEC.md §5
# ══════════════════════════════════════════════════════════════════════════════

class SensitivityWindow(BaseModel):
    """
    A time-windowed sensitivity flag inside a scene — DATA_SPEC.md §5.
    Fields use 'in'/'out' to match the JSON fixture exactly.
    """
    flag: str
    # DATA_SPEC uses "in" / "out" as keys; Python forbids 'in' as identifier
    # so we alias. Serialisation uses the alias so JSON round-trips cleanly.
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class Scene(BaseModel):
    """
    One scene record — DATA_SPEC.md §5.
    Field names: scene_id, in, out, description, visual_facts, characters,
    actors, emotion, music_asset_id, audio_stems, spoiler_level,
    sensitivity_flags, audio_only_key_info, synthetic.
    """
    synthetic: bool
    scene_id: str
    # "in" / "out" aliased to source_in / source_out
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")
    description: str = ""
    visual_facts: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    emotion: str = ""
    music_asset_id: Optional[str] = None
    audio_stems: list[str] = Field(default_factory=list)
    spoiler_level: SpoilerLevel = SpoilerLevel.NONE
    # Each entry is either a bare flag string or a SensitivityWindow dict.
    # We store them as dicts to allow both forms; parsing is done by callers.
    sensitivity_flags: list[Any] = Field(default_factory=list)
    audio_only_key_info: bool = False
    # Set by EvidenceBuilder after injection scan (not in raw fixture)
    injection_scan_flag: bool = False

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class ScenesFile(BaseModel):
    """Top-level wrapper for scenes.json."""
    synthetic: bool
    synthetic_notice: str = ""
    scenes: list[Scene]


# ══════════════════════════════════════════════════════════════════════════════
# §4  Dialogue — DATA_SPEC.md §6
# ══════════════════════════════════════════════════════════════════════════════

class DialogueLine(BaseModel):
    """
    One dialogue line — DATA_SPEC.md §6.
    Fields: line_id, scene_id, speaker, in, out, text, gloss_en, synthetic.
    """
    line_id: str
    scene_id: str
    speaker: str
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")
    text: str
    gloss_en: str = ""
    synthetic: bool = True

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class DialogueFile(BaseModel):
    """Top-level wrapper — dialogue.json is a bare list, so this wraps it."""
    synthetic: bool = True
    synthetic_notice: str = ""
    lines: list[DialogueLine]


# ══════════════════════════════════════════════════════════════════════════════
# §5  Subtitles — DATA_SPEC.md §7
# ══════════════════════════════════════════════════════════════════════════════

class SourceCue(BaseModel):
    """
    One cue in the source (hi) subtitle track — DATA_SPEC.md §7.
    """
    cue_id: str
    scene_id: str
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")
    text: str
    gloss_en: str = ""
    meaning_tags: list[str] = Field(default_factory=list)
    source_line_id: Optional[str] = None

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class DialectCue(BaseModel):
    """
    One cue in a dialect (bgc / raj) subtitle track — DATA_SPEC.md §7.
    """
    cue_id: str
    scene_id: str
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")
    text: str
    gloss_en: str = ""
    aligns_with: str        # cue_id of the aligned hi cue
    meaning_tags: list[str] = Field(default_factory=list)
    stereotype_flags: list[str] = Field(default_factory=list)
    native_review: NativeReviewStatus = NativeReviewStatus.PENDING

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class SubtitleTracks(BaseModel):
    """
    The three subtitle tracks — DATA_SPEC.md §7.
    hi = source; bgc = Haryanvi dialect; raj = Rajasthani dialect.
    """
    hi: list[SourceCue] = Field(default_factory=list)
    bgc: list[DialectCue] = Field(default_factory=list)
    raj: list[DialectCue] = Field(default_factory=list)


class SubtitlesFile(BaseModel):
    """Top-level subtitles.json wrapper — DATA_SPEC.md §7."""
    synthetic: bool
    synthetic_notice: str = ""
    tracks: SubtitleTracks


# ══════════════════════════════════════════════════════════════════════════════
# §6  Story facts — DATA_SPEC.md §8
# ══════════════════════════════════════════════════════════════════════════════

class CharacterRecord(BaseModel):
    """Character entry in story_facts.json — DATA_SPEC.md §8."""
    char_id: str
    name: str
    actor_id: str
    role: str = ""


class RelationshipRecord(BaseModel):
    """Relationship entry in story_facts.json — DATA_SPEC.md §8."""
    a: str              # char_id
    b: str              # char_id
    relation: str
    visibility: Visibility = Visibility.PUBLIC
    fact_id: Optional[str] = None   # set for protected relationships


class RevealWindow(BaseModel):
    """One reveal window for a protected fact — DATA_SPEC.md §8."""
    scene_id: str
    source_in: str = Field(alias="in")
    source_out: str = Field(alias="out")

    model_config = {"populate_by_name": True}

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)


class ProtectedFact(BaseModel):
    """
    One editorial protected story fact — DATA_SPEC.md §8.
    fact_id: F01–F04.
    """
    fact_id: str
    spoiler_level: SpoilerLevel
    fact: str
    reveal_windows: list[RevealWindow]
    trigger_terms: list[str] = Field(default_factory=list)


class MajorEvent(BaseModel):
    """Major event record in story_facts.json — DATA_SPEC.md §8."""
    event_id: str
    text: str
    scene_id: str


class StoryFacts(BaseModel):
    """
    Editorial spoiler / story-truth sheet — DATA_SPEC.md §8 (PD-2).
    This file is authoritative; StoryAnalyzer output cannot contradict it.
    """
    synthetic: bool
    synthetic_notice: str = ""
    characters: list[CharacterRecord] = Field(default_factory=list)
    relationships: list[RelationshipRecord] = Field(default_factory=list)
    protected_facts: list[ProtectedFact] = Field(default_factory=list)
    permitted_genres: list[str] = Field(default_factory=list)
    forbidden_claim_patterns: list[str] = Field(default_factory=list)
    major_events: list[MajorEvent] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §7  Contracts — DATA_SPEC.md §11
# ══════════════════════════════════════════════════════════════════════════════

class Contract(BaseModel):
    """
    One rights contract — DATA_SPEC.md §11.
    asset_type: "music" | "actor"
    """
    contract_id: str            # C-MUS-* | C-ACT-*
    asset_type: str             # music | actor
    asset_id: str               # music_03, actor_01 …
    title: str = ""
    mood_tags: list[str] = Field(default_factory=list)   # music contracts only
    promotional_use: bool
    territories: list[str]
    valid_from: str             # YYYY-MM-DD
    valid_until: str            # YYYY-MM-DD


class ContractsFile(BaseModel):
    """Top-level contracts.json wrapper — DATA_SPEC.md §11."""
    synthetic: bool
    synthetic_notice: str = ""
    contracts: list[Contract]


# ══════════════════════════════════════════════════════════════════════════════
# §8  Policies — DATA_SPEC.md §12
# ══════════════════════════════════════════════════════════════════════════════

class Policy(BaseModel):
    """
    One structured policy rule — DATA_SPEC.md §12 (PD-12).
    The `rule` field is a free-form dict whose shape depends on `category`.
    """
    policy_id: str              # POL-*
    category: ConstraintCategory
    severity: str = "HARD"      # HARD | SOFT
    text: str = ""              # human-readable description
    rule: dict[str, Any] = Field(default_factory=dict)


class PoliciesFile(BaseModel):
    """Top-level policies.json wrapper — DATA_SPEC.md §12."""
    synthetic: bool
    synthetic_notice: str = ""
    rating_order: list[str] = Field(default_factory=list)
    policies: list[Policy]


# ══════════════════════════════════════════════════════════════════════════════
# §9  Audience profiles — DATA_SPEC.md §13
# ══════════════════════════════════════════════════════════════════════════════

class Audience(BaseModel):
    """
    One audience profile — DATA_SPEC.md §13.
    audience_id must be one of: family, young_adult, dialect_region.
    """
    audience_id: str
    label: str = ""
    rating_ceiling: str         # U | UA7+ | UA13+ | UA16+ | A
    subtitle_track: str         # hi | bgc | raj
    alternate_subtitle_tracks: list[str] = Field(default_factory=list)
    promise_seed: str = ""
    preferred_emotions: list[str] = Field(default_factory=list)
    allowed_framing_tags: list[str] = Field(default_factory=list)
    avoid_tags: list[str] = Field(default_factory=list)
    note: str = ""

    @field_validator("audience_id")
    @classmethod
    def validate_audience_id(cls, v: str) -> str:
        if v not in VALID_AUDIENCE_IDS:
            raise ValueError(
                f"audience_id {v!r} is not valid. Must be one of {sorted(VALID_AUDIENCE_IDS)}"
            )
        return v

    @field_validator("subtitle_track")
    @classmethod
    def validate_subtitle_track(cls, v: str) -> str:
        if v not in VALID_SUBTITLE_TRACKS:
            raise ValueError(
                f"subtitle_track {v!r} is not valid. Must be one of {sorted(VALID_SUBTITLE_TRACKS)}"
            )
        return v


class AudiencesFile(BaseModel):
    """Top-level audiences.json wrapper — DATA_SPEC.md §13."""
    synthetic: bool
    synthetic_notice: str = ""
    audiences: list[Audience]


class AudiencePromise(BaseModel):
    """
    Generated audience promise (state field audience.promises[id]) — DATA_SPEC.md §13.
    """
    audience_id: str
    promise: str
    required_beats: list[str] = Field(default_factory=list)
    framing_tags: list[str] = Field(default_factory=list)
    avoid_tags: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.MEDIUM


# ══════════════════════════════════════════════════════════════════════════════
# §10  Historical performance — DATA_SPEC.md §15
# ══════════════════════════════════════════════════════════════════════════════

class HistoricPerformance(BaseModel):
    """
    scene_engagement table — DATA_SPEC.md §15.
    scene_engagement: {scene_id: {audience_id: float (0-1)}}.
    Hypothesis input only; never a hard selection rule (SUMMARY.md §15).
    """
    synthetic: bool
    synthetic_notice: str = ""
    signal: str = ""
    bias_note: str = ""
    scene_engagement: dict[str, dict[str, float]] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# §11  Cost sheet — DATA_SPEC.md §16
# ══════════════════════════════════════════════════════════════════════════════

class CostRates(BaseModel):
    """Per-call cost rates — DATA_SPEC.md §16."""
    multimodal_scene_analysis: float = 0.05
    story_analysis_call: float = 0.05
    audience_call: float = 0.03
    planning_call: float = 0.05
    repair_rerank_call: float = 0.02
    mock_call: float = 0.0


class CostProfile(BaseModel):
    """
    One cost profile (full / lite) — DATA_SPEC.md §16.
    Values are call counts; multiply by rates to get cost.
    """
    multimodal_scene_analysis: int = 0
    story_analysis_call: int = 1
    audience_call: int = 1
    planning_call: int = 1
    repair_rerank_call: int = 0


class CostSheet(BaseModel):
    """
    Cost sheet — DATA_SPEC.md §16.
    profiles: {"full": CostProfile, "lite": CostProfile}
    """
    synthetic: bool
    synthetic_notice: str = ""
    currency_unit: str = "USD_synthetic"
    run_budget: float = 2.00
    rates: CostRates = Field(default_factory=CostRates)
    profiles: dict[str, CostProfile] = Field(default_factory=dict)
    fallback_profile: str = "lite"


# ══════════════════════════════════════════════════════════════════════════════
# §12  Trailer plan — DATA_SPEC.md §14, SUMMARY.md §16
# ══════════════════════════════════════════════════════════════════════════════

class SubtitleRef(BaseModel):
    """
    Subtitle reference inside a trailer segment — DATA_SPEC.md §14.
    text must equal the joined referenced cue texts.
    """
    track: str          # hi | bgc | raj
    cue_ids: list[str]
    text: str

    @field_validator("track")
    @classmethod
    def validate_track(cls, v: str) -> str:
        if v not in VALID_SUBTITLE_TRACKS:
            raise ValueError(
                f"Subtitle track {v!r} not valid. Must be one of {sorted(VALID_SUBTITLE_TRACKS)}"
            )
        return v


class SegmentClaim(BaseModel):
    """
    A structured story-truth claim in a segment — DATA_SPEC.md §14.
    Used by StoryTruthValidator to verify relationship/promise claims.
    """
    type: str               # "relationship" | "genre" | "event"
    subject: Optional[str] = None
    object: Optional[str] = None
    relation: Optional[str] = None
    supported_by: list[str] = Field(default_factory=list)  # evidence refs


class SegmentDependency(BaseModel):
    """
    Segment-level dependency index entry — ARCHITECTURE.md §8.
    Built by plan_trailers; used by ChangeImpactAnalyzer.
    """
    scene: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    subtitle_cues: list[str] = Field(default_factory=list)
    audience: str = ""


class TrailerSegment(BaseModel):
    """
    One segment in a trailer edit decision list — DATA_SPEC.md §14, SUMMARY.md §16.

    Required: segment_id, role, source_in, source_out, video, audio_mode,
              subtitle, reason, evidence.
    """
    segment_id: str             # segment_01, segment_02 …
    role: str                   # beat role: hook_humour | warmth | conflict | …
    source_in: str              # HH:MM:SS.mmm  (half-open interval start)
    source_out: str             # HH:MM:SS.mmm  (half-open interval end, exclusive)
    video: str                  # scene_id reference
    audio_mode: AudioMode
    music_asset_id: Optional[str] = None
    subtitle: SubtitleRef
    reason: str
    evidence: list[str] = Field(default_factory=list)  # "scene:scene_04" etc.
    claims: list[SegmentClaim] = Field(default_factory=list)
    framing_tags: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    confidence: Confidence = Confidence.HIGH
    # Dependency index is populated by plan_trailers; may be absent in drafts
    dependency: Optional[SegmentDependency] = None

    @field_validator("source_in", "source_out")
    @classmethod
    def validate_tc(cls, v: str) -> str:
        return _validate_timecode(v)

    @model_validator(mode="after")
    def validate_interval_order(self) -> "TrailerSegment":
        """source_in must be strictly less than source_out (half-open interval)."""
        in_parts = self.source_in.replace(":", ".").split(".")
        out_parts = self.source_out.replace(":", ".").split(".")
        # Parse to milliseconds for comparison
        def _ms(parts: list[str]) -> int:
            h, m, s, ms = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            return ((h * 60 + m) * 60 + s) * 1000 + ms
        # Re-split properly on ":" and "."
        def _parse(tc: str) -> int:
            h, m, rest = tc.split(":")
            s, ms = rest.split(".")
            return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)
        if _parse(self.source_in) >= _parse(self.source_out):
            raise ValueError(
                f"source_in ({self.source_in}) must be strictly less than "
                f"source_out ({self.source_out}); intervals are half-open [in, out)"
            )
        return self

    @model_validator(mode="after")
    def validate_music_asset_required_for_music_mode(self) -> "TrailerSegment":
        """music_asset_id is required when audio_mode includes music."""
        if self.audio_mode == AudioMode.DIALOGUE_AND_MUSIC and self.music_asset_id is None:
            raise ValueError(
                "music_asset_id is required when audio_mode is 'dialogue_and_music'"
            )
        if self.audio_mode == AudioMode.MUSIC_ONLY and self.music_asset_id is None:
            raise ValueError(
                "music_asset_id is required when audio_mode is 'music_only'"
            )
        return self


class FallbackPlan(BaseModel):
    """Lite-profile fallback plan reference — DATA_SPEC.md §14."""
    profile: str = "lite"
    estimated_cost: float = 0.0


class TrailerPlan(BaseModel):
    """
    One audience trailer edit decision list — the primary artifact.
    DATA_SPEC.md §14, SUMMARY.md §16, PROTOTYPE_SPEC.md §0.

    trailer_id must be one of: family_v1, young_adult_v1, dialect_region_v1.
    audience must be one of: family, young_adult, dialect_region.
    """
    synthetic: bool = True
    synthetic_notice: str = "Trailer plan generated from synthetic fixture. Not STAGE content."
    trailer_id: str
    audience: str
    revision: int = 0
    duration_seconds: float
    creative_brief: str = ""
    audience_promise: str
    emotional_journey: list[str] = Field(default_factory=list)
    tagline: str = ""
    transitions: list[str] = Field(default_factory=list)
    voice_over: Optional[str] = None
    text_cards: list[str] = Field(default_factory=list)
    cost_profile: str = "full"
    estimated_cost: float = 0.0
    fallback_plan: Optional[FallbackPlan] = None
    segments: list[TrailerSegment]
    # dependency_index: {segment_id: SegmentDependency}, set by plan_trailers
    dependency_index: dict[str, SegmentDependency] = Field(default_factory=dict)
    # Per-segment and trailer-level validation result (set by validate node)
    validation: Optional[dict[str, Any]] = None

    @field_validator("trailer_id")
    @classmethod
    def validate_trailer_id(cls, v: str) -> str:
        if v not in VALID_TRAILER_IDS:
            raise ValueError(
                f"trailer_id {v!r} is not valid. Must be one of {sorted(VALID_TRAILER_IDS)}"
            )
        return v

    @field_validator("audience")
    @classmethod
    def validate_audience(cls, v: str) -> str:
        if v not in VALID_AUDIENCE_IDS:
            raise ValueError(
                f"audience {v!r} is not valid. Must be one of {sorted(VALID_AUDIENCE_IDS)}"
            )
        return v


# ══════════════════════════════════════════════════════════════════════════════
# §13  Validation results — DATA_SPEC.md §17, VALIDATION_AND_TESTING.md §1–§2
# ══════════════════════════════════════════════════════════════════════════════

class ValidationError(BaseModel):
    """
    One structured validation error entry — DATA_SPEC.md §17.
    """
    code: str           # e.g. SPOILER_MAJOR, RIGHTS_EXPIRED
    rule_id: str = ""   # e.g. POL-SPOILER-001
    segment_id: Optional[str] = None
    message: str = ""
    evidence: list[str] = Field(default_factory=list)
    repairable: bool = True


class ValidationWarning(BaseModel):
    """One structured validation warning entry."""
    code: str
    rule_id: str = ""
    segment_id: Optional[str] = None
    message: str = ""
    evidence: list[str] = Field(default_factory=list)


class ValidatorResult(BaseModel):
    """
    Result returned by one validator — DATA_SPEC.md §17.
    Per-validator status: PASS | WARN | FAIL | SKIPPED.
    """
    validator: str
    status: ValidatorStatus
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[ValidationWarning] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    # Set when status == SKIPPED
    blocked_by: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class TrailerValidationResult(BaseModel):
    """
    Aggregate validation result for one trailer — DATA_SPEC.md §17.
    Matches the JSON shape: trailer_id, status, validators[], human_review_required,
    repair_attempts.
    """
    trailer_id: str
    status: TrailerStatus
    validators: list[ValidatorResult] = Field(default_factory=list)
    human_review_required: bool = False
    repair_attempts: dict[str, int] = Field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
# §14  Story map output — DATA_SPEC.md §9
# ══════════════════════════════════════════════════════════════════════════════

class StoryCharacter(BaseModel):
    """Character record in the generated story map — DATA_SPEC.md §9."""
    char_id: str
    name: str
    source: str = "editorial"   # "editorial" | "llm" | "editorial+llm"


class StoryRelationship(BaseModel):
    """Relationship in the generated story map — DATA_SPEC.md §9."""
    a: str
    b: str
    relation: str
    visibility: Visibility = Visibility.PUBLIC
    confidence: Confidence = Confidence.HIGH


class EmotionalTurn(BaseModel):
    """Emotional turn entry in the story map — DATA_SPEC.md §9."""
    scene_id: str
    emotion: str


class SensitiveContentEntry(BaseModel):
    """Sensitive content entry in the story map — DATA_SPEC.md §9."""
    scene_id: str
    flag: str
    source_in: Optional[str] = Field(default=None, alias="in")
    source_out: Optional[str] = Field(default=None, alias="out")

    model_config = {"populate_by_name": True}


class StoryMap(BaseModel):
    """
    Generated story map output — DATA_SPEC.md §9, SUMMARY.md §11.
    Written to sample_run/story_map.json.
    """
    synthetic: bool = True
    synthetic_notice: str = ""
    characters: list[StoryCharacter] = Field(default_factory=list)
    relationships: list[StoryRelationship] = Field(default_factory=list)
    major_events: list[MajorEvent] = Field(default_factory=list)
    emotional_turns: list[EmotionalTurn] = Field(default_factory=list)
    spoilers: dict[str, Any] = Field(default_factory=dict)  # embedded spoiler_map
    sensitive_content: list[SensitiveContentEntry] = Field(default_factory=list)
    disagreements: list[dict[str, Any]] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §15  Spoiler map output — DATA_SPEC.md §10, §18
# ══════════════════════════════════════════════════════════════════════════════

class SpoilerFact(BaseModel):
    """
    One fact in the spoiler map — DATA_SPEC.md §10.
    source: "editorial" | "llm"
    """
    fact_id: str
    fact: str
    spoiler_level: SpoilerLevel
    source: str = "editorial"       # "editorial" | "llm"
    confidence: Confidence = Confidence.HIGH
    reveal_windows: list[RevealWindow] = Field(default_factory=list)
    trigger_terms: list[str] = Field(default_factory=list)


class SpoilerMap(BaseModel):
    """
    Spoiler map output — DATA_SPEC.md §10, §18 (PD-15).
    Emitted separately from story_map.json for independent auditability.
    """
    synthetic: bool = True
    synthetic_notice: str = ""
    facts: list[SpoilerFact] = Field(default_factory=list)
    llm_added_candidates: list[SpoilerFact] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §16  Constraint map (in-memory state, written as output) — ARCHITECTURE.md §5
# ══════════════════════════════════════════════════════════════════════════════

class ConstraintRule(BaseModel):
    """
    One rule in the compiled constraint map — ARCHITECTURE.md §4, SUMMARY.md §13.
    """
    rule_id: str
    category: ConstraintCategory
    severity: str = "HARD"      # HARD | SOFT
    scope: dict[str, Any] = Field(default_factory=dict)
    rule: dict[str, Any] = Field(default_factory=dict)
    source_ref: str = ""        # e.g. "POL-SPOILER-001" or "C-MUS-03"


class ConstraintMap(BaseModel):
    """
    Compiled constraint map — ARCHITECTURE.md §4.
    version increments whenever a change event is applied.
    """
    synthetic: bool = True
    version: int = 0
    evaluation_date: str = ""
    campaign: dict[str, Any] = Field(default_factory=dict)
    rating_order: list[str] = Field(default_factory=list)
    rules: list[ConstraintRule] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §17  Revision record — DATA_SPEC.md §19, SUMMARY.md §19, ARCHITECTURE.md §8
# ══════════════════════════════════════════════════════════════════════════════

class RevisionRecord(BaseModel):
    """
    One repair/change revision record — DATA_SPEC.md §19, SUMMARY.md §19.
    Written to sample_run/revision_log.json.
    """
    revision: int
    trigger: str
    affected: list[str]             # segment ids (e.g. "family_v1.segment_02")
    unchanged: list[str]            # segment ids that are byte-identical
    action: str
    validators_rerun: list[str] = Field(default_factory=list)
    validation: str                 # PASS | PASS_WITH_WARNINGS | REJECTED
    hashes_unchanged: dict[str, str] = Field(default_factory=dict)  # seg_id → sha256


class RevisionLog(BaseModel):
    """Top-level revision_log.json wrapper."""
    synthetic: bool = True
    synthetic_notice: str = ""
    revisions: list[RevisionRecord] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §18  Change event — DATA_SPEC.md §19
# ══════════════════════════════════════════════════════════════════════════════

class ChangeTarget(BaseModel):
    """
    The target of a change event — DATA_SPEC.md §19.
    kind: "contract" | "policy" | "scene" | "audience" | "cost"
    """
    kind: str
    id: str


class ChangeEvent(BaseModel):
    """
    A change event applied during a change-impact run — DATA_SPEC.md §19.
    type must be one of the ChangeEventType values.
    Supports both canonical schema format and fixture change_event JSON format.
    """
    synthetic: bool = True
    synthetic_notice: str = ""
    event_id: str
    type: ChangeEventType
    target: ChangeTarget
    patch: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    event_date: str = ""
    change: dict[str, Any] = Field(default_factory=dict)
    target_asset_id: Optional[str] = None
    target_contract_id: Optional[str] = None
    target_policy_id: Optional[str] = None
    target_scene_id: Optional[str] = None
    target_audience_id: Optional[str] = None
    affected_segments: list[dict[str, Any]] = Field(default_factory=list)
    unaffected_trailers: list[str] = Field(default_factory=list)
    suggested_replacement_asset_id: Optional[str] = None
    suggested_replacement_contract_id: Optional[str] = None
    change_impact_note: str = ""

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def normalize_fixture_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # 1. Map event_type -> type
        if "type" not in d and "event_type" in d:
            d["type"] = d["event_type"]

        # 2. Map target
        if "target" not in d:
            if "target_asset_id" in d and d["target_asset_id"]:
                d["target"] = {"kind": "contract", "id": d["target_asset_id"]}
            elif "target_contract_id" in d and d["target_contract_id"]:
                d["target"] = {"kind": "contract", "id": d["target_contract_id"]}
            elif "target_policy_id" in d and d["target_policy_id"]:
                d["target"] = {"kind": "policy", "id": d["target_policy_id"]}
            elif "target_scene_id" in d and d["target_scene_id"]:
                d["target"] = {"kind": "scene", "id": d["target_scene_id"]}
            elif "target_audience_id" in d and d["target_audience_id"]:
                d["target"] = {"kind": "audience", "id": d["target_audience_id"]}
            else:
                d["target"] = {"kind": "cost", "id": "cost_sheet"}

        # 3. Map patch from change
        if not d.get("patch") and "change" in d:
            ch = d["change"]
            if isinstance(ch, dict) and "field" in ch and "new_value" in ch:
                d["patch"] = {ch["field"]: ch["new_value"]}
            elif isinstance(ch, dict):
                d["patch"] = ch

        return d


# ══════════════════════════════════════════════════════════════════════════════
# §19  Decision log entry — DATA_SPEC.md §20, ARCHITECTURE.md §10
# ══════════════════════════════════════════════════════════════════════════════

# Valid entry types (ARCHITECTURE.md §10)
DECISION_LOG_ENTRY_TYPES = frozenset({
    "PACKAGE_LOADED", "INJECTION_DETECTED", "MODEL_CALL", "MODEL_DISAGREEMENT",
    "AUDIENCE_PROMISE", "PLAN_PROPOSED", "VALIDATION_RESULT", "REPAIR_APPLIED",
    "SEGMENT_REJECTED", "CHANGE_EVENT", "IMPACT_ANALYSIS", "HUMAN_REVIEW_FLAG",
    "RUN_FINALIZED", "REPLAY_INPUT_DRIFT", "MODE_FALLBACK_REPLAY",
    "PLANNED_WITH_FALLBACK_PROFILE", "REPLAY_MISS",
})


class DecisionLogEntry(BaseModel):
    """
    One append-only decision log entry — DATA_SPEC.md §20, ARCHITECTURE.md §10.
    seq is assigned monotonically (never wall-clock time for determinism).
    """
    seq: int
    # The field in DATA_SPEC.md §20 JSON example is "type" not "entry_type"
    type: str = Field(alias="type")
    node: str
    trailer_id: Optional[str] = None
    segment_id: Optional[str] = None
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class DecisionLog(BaseModel):
    """Top-level decision_log.json wrapper."""
    synthetic: bool = True
    synthetic_notice: str = ""
    entries: list[DecisionLogEntry] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# §20  Human review item — ARCHITECTURE.md §12
# ══════════════════════════════════════════════════════════════════════════════

# Valid human-review reason codes (ARCHITECTURE.md §12)
HUMAN_REVIEW_REASON_CODES = frozenset({
    "LEGAL_AMBIGUITY", "CULTURAL_EDGE_CASE", "RATING_AMBIGUOUS",
    "MARKETING_WORDING_UNCERTAIN", "STORY_PROMISE_CHANGE", "REPAIR_EXHAUSTED",
    "INJECTION_SUSPECTED", "BUDGET_UNRESOLVED", "NATIVE_REVIEW_PENDING",
    "LLM_ADVISORY_CONCERN", "AUDIENCE_PROXY_BIAS",
})


class HumanReviewItem(BaseModel):
    """
    One human-approval requirement — ARCHITECTURE.md §12.
    blocking=True forces trailer to REJECTED until resolved outside the prototype.
    """
    item_id: str
    trailer_id: Optional[str] = None
    segment_id: Optional[str] = None
    reason_code: str
    description: str
    blocking: bool = False


# ══════════════════════════════════════════════════════════════════════════════
# §21  Replay file wrapper — DATA_SPEC.md §20, ARCHITECTURE.md §11
# ══════════════════════════════════════════════════════════════════════════════

class ReplayMetadata(BaseModel):
    """Metadata block inside a replay fixture file — DATA_SPEC.md §20."""
    fixture_version: str = "1.0"
    scenario: str = "baseline"
    input_hash: str = ""
    note: str = ""


class ReplayFile(BaseModel):
    """
    Top-level shape of a replay fixture file — DATA_SPEC.md §20, ARCHITECTURE.md §11.
    response contains the structured model output for the relevant node.
    """
    recorded_for: ReplayMetadata
    response: dict[str, Any]


# ══════════════════════════════════════════════════════════════════════════════
# §22  Run state — ARCHITECTURE.md §8.1, PROTOTYPE_SPEC.md §0
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# §23  Backward-compatibility aliases (referenced by Phase 0 stubs)
# ══════════════════════════════════════════════════════════════════════════════

# Phase 0 stubs were written with provisional names; these aliases keep them
# importable without requiring stubs to be edited before Phase 6.

#: Alias for Audience — Phase 0 stubs import AudienceProfile.
AudienceProfile = Audience

#: Alias for TrailerValidationResult — Phase 0 stubs import TrailerValidation.
TrailerValidation = TrailerValidationResult

#: Alias for SourceCue — Phase 0 stubs import SubtitleCue.
SubtitleCue = SourceCue

#: Alias for TrailerSegment — used in graph.py / repair.py stubs.
Segment = TrailerSegment

#: Alias for RevisionRecord — Phase 0 stubs import Revision.
Revision = RevisionRecord

#: Alias for ValidatorResult — older naming.
SegmentValidation = ValidatorResult


class RunState(BaseModel):
    """
    Serialized run state written to sample_run/run_state.json.
    Used for change-impact resume (ARCHITECTURE.md §8.1).
    The actual TrailerState fields are stored as a flat JSON-serializable dict.
    """
    synthetic: bool = True
    run_config: dict[str, Any] = Field(default_factory=dict)
    candidate_plan: dict[str, Any] = Field(default_factory=dict)
    dependency_index: dict[str, Any] = Field(default_factory=dict)
    constraint_map: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    revisions: list[dict[str, Any]] = Field(default_factory=list)
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "PASS"
    estimated_cost: float = 0.0
    # Segment hashes for the unaffected-hash invariant (ARCHITECTURE.md §8)
    segment_hashes: dict[str, str] = Field(default_factory=dict)
