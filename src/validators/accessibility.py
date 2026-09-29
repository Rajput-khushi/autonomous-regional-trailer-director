"""
Validator 8 — AccessibilityValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.8, ARCHITECTURE.md §7.

Checks:
  - Subtitle track matches audience profile → ACCESS_TRACK_MISMATCH (fail)
  - Referenced cues lie fully inside segment bounds → ACCESS_CUE_OUTSIDE_SEGMENT (fail)
  - subtitle.text equals joined cue text → ACCESS_SUBTITLE_TEXT_MISMATCH (fail)
  - Audio-only key info scenes MUST have subtitle coverage → ACCESS_AUDIO_ONLY_INFO (fail)
  - Dialogue lines overlapping segment have covering cues → ACCESS_SUBTITLE_MISSING (fail)
  - Warnings: reading speed > 25 chars/s, line > 45 chars.
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


class AccessibilityValidator:
    """
    Deterministic. Imports no planner or LLM code.
    """

    name = "AccessibilityValidator"

    def validate_segment(
        self,
        segment: dict[str, Any],
        evidence_index: dict[str, Any],
        audience_profile: dict[str, Any],
    ) -> ValidatorResult:
        """
        Validate one segment for accessibility and subtitle compliance.
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
            in_ms, out_ms = 0, 0

        scenes_map = evidence_index.get("by_scene", {})
        sc_data = scenes_map.get(video, {})

        sub = segment.get("subtitle", {})
        track = sub.get("track", "hi") if isinstance(sub, dict) else getattr(sub, "track", "hi")
        cue_ids = sub.get("cue_ids", []) if isinstance(sub, dict) else getattr(sub, "cue_ids", [])
        sub_text = sub.get("text", "") if isinstance(sub, dict) else getattr(sub, "text", "")

        # 1. Track match
        expected_track = audience_profile.get("subtitle_track", "hi")
        alt_tracks = audience_profile.get("alternate_subtitle_tracks", [])
        allowed_tracks = {expected_track} | set(alt_tracks)
        if track not in allowed_tracks:
            errors.append(
                ValidationError(
                    code="ACCESS_TRACK_MISMATCH",
                    rule_id="POL-ACCESS-001",
                    segment_id=sid,
                    message=f"Segment uses subtitle track {track!r}; expected one of {allowed_tracks}",
                    evidence=[f"track:{track}"],
                    repairable=True,
                )
            )

        # Look up cues for this scene
        track_cues = sc_data.get("subtitle_cues", {}).get(track, [])
        cues_map = {c.get("cue_id"): c for c in track_cues}

        matched_cue_texts: list[str] = []

        # 2. Cue bounds containment
        for cid in cue_ids:
            cue = cues_map.get(cid)
            if not cue:
                continue
            evidence.append(f"cue:{cid}")
            matched_cue_texts.append(cue.get("text", ""))

            c_in = cue.get("in") or cue.get("source_in", "")
            c_out = cue.get("out") or cue.get("source_out", "")
            try:
                c_in_ms = parse_timecode(c_in)
                c_out_ms = parse_timecode(c_out)
                # Cue must lie fully inside [in_ms, out_ms)
                if c_in_ms < in_ms or c_out_ms > out_ms:
                    errors.append(
                        ValidationError(
                            code="ACCESS_CUE_OUTSIDE_SEGMENT",
                            rule_id="POL-ACCESS-001",
                            segment_id=sid,
                            message=(
                                f"Subtitle cue {cid} [{c_in}, {c_out}) extends outside "
                                f"segment bounds [{sin}, {sout})"
                            ),
                            evidence=[f"cue:{cid}", f"segment:{sid}"],
                            repairable=True,
                        )
                    )
            except Exception:
                pass

        # 3. Text match check
        if matched_cue_texts:
            joined_cues = " ".join(matched_cue_texts).strip()
            # If subtitle text is significantly divergent
            if sub_text and joined_cues and sub_text.strip() != joined_cues:
                errors.append(
                    ValidationError(
                        code="ACCESS_SUBTITLE_TEXT_MISMATCH",
                        rule_id="POL-ACCESS-001",
                        segment_id=sid,
                        message=f"Segment subtitle text does not match referenced cue text",
                        evidence=[f"stated:{sub_text}", f"cues:{joined_cues}"],
                        repairable=True,
                    )
                )

        # 4. Audio-only key info requirement
        if sc_data.get("audio_only_key_info", False):
            if not cue_ids or not sub_text:
                errors.append(
                    ValidationError(
                        code="ACCESS_AUDIO_ONLY_INFO",
                        rule_id="POL-ACCESS-001",
                        segment_id=sid,
                        message=f"Scene {video} contains critical dialogue/audio-only information and requires subtitle coverage",
                        evidence=[f"scene:{video}"],
                        repairable=True,
                    )
                )

        # 5. Dialogue line coverage
        is_explicitly_silent = "silent" in str(segment.get("reason", "")).lower() or segment.get("audio_mode") == "music_only"
        if not is_explicitly_silent:
            for dline in sc_data.get("dialogue_lines", []):
                d_in = dline.get("in") or dline.get("source_in", "")
                d_out = dline.get("out") or dline.get("source_out", "")
                try:
                    d_in_ms = parse_timecode(d_in)
                    d_out_ms = parse_timecode(d_out)
                    # If dialogue overlaps segment by >= 1000ms
                    overlap_start = max(in_ms, d_in_ms)
                    overlap_end = min(out_ms, d_out_ms)
                    if (overlap_end - overlap_start) >= 1000:
                        if not cue_ids:
                            errors.append(
                                ValidationError(
                                    code="ACCESS_SUBTITLE_MISSING",
                                    rule_id="POL-ACCESS-001",
                                    segment_id=sid,
                                    message=f"Segment contains dialogue line {dline.get('line_id')} without subtitle coverage",
                                    evidence=[f"dialogue:{dline.get('line_id')}"],
                                    repairable=True,
                                )
                            )
                            break
                except Exception:
                    pass

        # 6. Reading speed and line length warnings
        seg_dur_s = max(1.0, (out_ms - in_ms) / 1000.0)
        if sub_text:
            cps = len(sub_text) / seg_dur_s
            if cps > 25.0:
                warnings.append(
                    ValidationWarning(
                        code="ACCESS_READING_SPEED",
                        rule_id="POL-ACCESS-002",
                        segment_id=sid,
                        message=f"Subtitle reading speed {cps:.1f} chars/sec exceeds recommended 25 cps",
                        evidence=[f"speed:{cps:.1f}"],
                    )
                )
            if len(sub_text) > 45:
                warnings.append(
                    ValidationWarning(
                        code="ACCESS_LINE_TOO_LONG",
                        rule_id="POL-ACCESS-002",
                        segment_id=sid,
                        message=f"Subtitle length {len(sub_text)} exceeds single-line recommended 45 chars",
                        evidence=[f"length:{len(sub_text)}"],
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
        Run per-segment accessibility validation for an entire trailer plan.
        """
        results: dict[str, ValidatorResult] = {}
        for seg in plan.get("segments", []):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            results[sid] = self.validate_segment(seg_dict, evidence_index, audience_profile)
        return results
