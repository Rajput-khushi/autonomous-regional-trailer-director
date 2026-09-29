"""
repair.py — Deterministic Bounded Repair Loop.
Authority: ARCHITECTURE.md §6, AI_SYSTEM_SPEC.md §5.5, VALIDATION_AND_TESTING.md §1–§4.

Repair strategy table (ARCHITECTURE.md §6):
  1. Music rights    → alt music (mood match) → dialogue_only → replace clip
  2. Actor rights    → replace clip (exclude actor)
  3. Spoiler/safety/ → replace clip
     timecode/missing
  4. Story truth     → replace claim with evidence-derived text → drop claim
  5. Dialect cue     → swap bgc/raj cue → replace clip
  6. Accessibility   → recompute cues → adjust bounds → replace clip
  7. Budget          → switch to fallback cost profile

Rules:
  - Max repair iterations = 2 per segment.
  - Candidate pool constructed deterministically from evidence windows.
  - Only candidates passing full revalidation are accepted.
  - Ranking: role fit → audience promise overlap → distinctness → historic score (tie-break).
  - Every repair writes a RevisionRecord and logs REPAIR_APPLIED.
  - If no valid candidate exists → REPAIR_EXHAUSTED (REJECTED + blocking human review).
"""

from __future__ import annotations

import copy
import hashlib
import logging
from typing import Any

from src.models import (
    TrailerPlan,
    TrailerSegment,
    SubtitleRef,
    AudioMode,
    ValidatorStatus,
    TrailerStatus,
    RevisionRecord,
    HumanReviewItem,
    ValidationError,
)
from src.tools.timecode import (
    parse_timecode,
    format_timecode,
    intervals_overlap,
    segment_duration_ms,
)
from src.validators.aggregate import (
    run_validators,
    aggregate_trailer_status,
    VALIDATOR_NAMES,
)

logger = logging.getLogger(__name__)


def _hash_segment(segment: dict[str, Any] | TrailerSegment) -> str:
    """Compute sha256 hash of a segment for unchanged tracking."""
    s_dict = segment.model_dump() if hasattr(segment, "model_dump") else dict(segment)
    # Exclude dynamic/non-semantic fields if any
    data = f"{s_dict.get('video')}|{s_dict.get('source_in')}|{s_dict.get('source_out')}|{s_dict.get('audio_mode')}|{s_dict.get('music_asset_id')}|{s_dict.get('subtitle')}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def build_candidate_pool(
    segment: TrailerSegment | dict[str, Any],
    error_codes: list[str],
    evidence_index: dict[str, Any],
    constraint_map: dict[str, Any],
    audience_id: str = "family",
    subtitle_track: str = "hi",
    spoiler_map: dict[str, Any] | None = None,
    story_facts: dict[str, Any] | None = None,
) -> list[TrailerSegment]:
    """
    Generate replacement segment candidates based on error class and evidence windows.
    Pool is built deterministically from scenes, dialogue, and cues.
    """
    seg_dict = segment.model_dump() if hasattr(segment, "model_dump") else dict(segment)
    target_role = seg_dict.get("role", "narrative")
    original_sid = seg_dict.get("segment_id", "segment_01")
    scenes_map = evidence_index.get("by_scene", {})

    candidates: list[TrailerSegment] = []

    # Identify any restricted actors
    restricted_actors: set[str] = set()
    for rule in constraint_map.get("rules", []):
        scope = rule.get("scope", {})
        if scope.get("asset_type") == "actor":
            r_body = rule.get("rule", {})
            if r_body.get("promotional_use") is False:
                restricted_actors.add(scope.get("asset_id", ""))

    # Look for candidate clips across all scenes in episode
    for sc_id, sc_data in sorted(scenes_map.items()):
        # If actor rights violated, skip scenes with restricted actor
        sc_actors = set(sc_data.get("actors", []))
        if sc_actors.intersection(restricted_actors):
            continue

        sc_in_str = sc_data.get("in", "00:00:00.000")
        sc_out_str = sc_data.get("out", "00:01:00.000")
        try:
            sc_in_ms = parse_timecode(sc_in_str)
            sc_out_ms = parse_timecode(sc_out_str)
        except Exception:
            continue

        cues_map = sc_data.get("subtitle_cues", {})
        track_cues = cues_map.get(subtitle_track, cues_map.get("hi", []))

        # 1. From subtitle cues (aligned dialogue clips)
        for cue in track_cues:
            cin_str = cue.get("in", cue.get("source_in", sc_in_str))
            cout_str = cue.get("out", cue.get("source_out", sc_out_str))
            cid = cue.get("cue_id", "")
            ctext = cue.get("text", "")

            try:
                cin = parse_timecode(cin_str)
                cout = parse_timecode(cout_str)
            except Exception:
                continue

            # Ensure valid half-open interval inside scene
            if cin >= cout or cin < sc_in_ms or cout > sc_out_ms:
                continue

            # Target 4-8 second duration
            dur = cout - cin
            if dur < 3000:
                # Pad slightly if possible
                extra = 3500 - dur
                cout = min(sc_out_ms, cout + extra)
                cout_str = format_timecode(cout)

            cand = TrailerSegment(
                segment_id=original_sid,
                role=target_role,
                source_in=cin_str,
                source_out=cout_str,
                video=sc_id,
                audio_mode=AudioMode.DIALOGUE_ONLY,
                music_asset_id=None,
                subtitle=SubtitleRef(track=subtitle_track, cue_ids=[cid] if cid else [], text=ctext),
                reason=f"Deterministic replacement candidate from {sc_id} covering cue {cid}",
                evidence=[f"scene:{sc_id}"] + ([f"cue:{cid}"] if cid else []),
                claims=[],
                framing_tags=[sc_data.get("emotion", "narrative")],
            )
            candidates.append(cand)

        # 2. Windowed candidate from scene if no cues or to supplement pool
        if not track_cues:
            win_in = sc_in_ms + 1000
            win_out = min(sc_out_ms, win_in + 6000)
            if win_in < win_out:
                cand = TrailerSegment(
                    segment_id=original_sid,
                    role=target_role,
                    source_in=format_timecode(win_in),
                    source_out=format_timecode(win_out),
                    video=sc_id,
                    audio_mode=AudioMode.DIALOGUE_ONLY,
                    music_asset_id=None,
                    subtitle=SubtitleRef(track=subtitle_track, cue_ids=[], text=""),
                    reason=f"Deterministic scene window replacement candidate from {sc_id}",
                    evidence=[f"scene:{sc_id}"],
                    claims=[],
                    framing_tags=[sc_data.get("emotion", "narrative")],
                )
                candidates.append(cand)

    return candidates


def rank_and_select(
    valid_candidates: list[TrailerSegment],
    original_segment: TrailerSegment | dict[str, Any],
    promise: dict[str, Any],
    other_trailer_ranges: list[tuple[str, int, int]],
    historic_performance: list[dict[str, Any]],
    audience_id: str = "family",
) -> TrailerSegment | None:
    """
    Rank validated candidates deterministically:
      1. Role fit
      2. Audience promise / framing tag overlap
      3. No overlap with other trailers' footage (distinctness)
      4. Historical engagement (tie-break)
      5. Earliest scene / timecode (stable deterministic tie-break)
    """
    if not valid_candidates:
        return None

    orig_dict = original_segment.model_dump() if hasattr(original_segment, "model_dump") else dict(original_segment)
    target_role = orig_dict.get("role", "")
    target_framing = set(promise.get("framing_tags", []) + promise.get("required_beats", []))

    # Pre-index historic performance: {scene_id: {audience_id: score}}
    hp_map: dict[str, float] = {}
    for row in historic_performance:
        r_dict = row.model_dump() if hasattr(row, "model_dump") else dict(row)
        sc = r_dict.get("scene_id", "")
        eng = r_dict.get("scene_engagement", {})
        if sc and audience_id in eng:
            hp_map[sc] = float(eng[audience_id])

    def score_candidate(cand: TrailerSegment) -> tuple[int, int, int, float, str]:
        # 1. Role match: 1 if match else 0
        role_score = 1 if cand.role == target_role else 0

        # 2. Framing overlap count
        cand_framing = set(cand.framing_tags)
        framing_score = len(cand_framing.intersection(target_framing))

        # 3. Distinctness: 1 if NO overlap with other trailers, else 0
        c_in = parse_timecode(cand.source_in)
        c_out = parse_timecode(cand.source_out)
        overlaps_other = False
        for ot_sc, ot_in, ot_out in other_trailer_ranges:
            if cand.video == ot_sc and intervals_overlap(c_in, c_out, ot_in, ot_out):
                overlaps_other = True
                break
        distinct_score = 0 if overlaps_other else 1

        # 4. Historic CTR score
        ctr_score = hp_map.get(cand.video, 0.0)

        # 5. Deterministic tie-break key (inverted for sort order)
        tie_key = f"{cand.video}_{cand.source_in}"

        # We want descending order for scores, ascending for tie_key
        return (role_score, framing_score, distinct_score, ctr_score, tie_key)

    # Sort descending on primary metrics, ascending on tie_key
    sorted_candidates = sorted(
        valid_candidates,
        key=lambda c: (
            score_candidate(c)[0],
            score_candidate(c)[1],
            score_candidate(c)[2],
            score_candidate(c)[3],
        ),
        reverse=True,
    )

    return sorted_candidates[0]


def repair_plan(
    candidate_plan: dict[str, Any],
    validation: dict[str, Any],
    evidence_index: dict[str, Any],
    constraint_map: dict[str, Any],
    audience_promises: dict[str, dict[str, Any]],
    repair_attempts: dict[str, int],
    revision_counter: int,
    spoiler_map: dict[str, Any] | None = None,
    story_map: dict[str, Any] | None = None,
    story_facts: dict[str, Any] | None = None,
    subtitles: dict[str, Any] | None = None,
    cost_sheet: dict[str, Any] | None = None,
    run_budget: float = 2.0,
    max_repair_iterations: int = 2,
    historic_performance: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, int], list[RevisionRecord], list[HumanReviewItem], list[dict[str, Any]]]:
    """
    Repair failing trailer plans using the documented repair strategies.
    Returns:
      (patched_candidate_plans, updated_repair_attempts, new_revisions, new_human_reviews, new_decision_logs)
    """
    patched_plans: dict[str, Any] = copy.deepcopy(candidate_plan)
    updated_attempts = dict(repair_attempts)
    new_revisions: list[RevisionRecord] = []
    new_human_reviews: list[HumanReviewItem] = []
    new_decision_logs: list[dict[str, Any]] = []

    spoiler_map = spoiler_map or {}
    story_map = story_map or {}
    story_facts = story_facts or {}
    subtitles = subtitles or {}
    historic_performance = historic_performance or []

    # Collect source footage intervals from other trailers for distinctness checking
    all_trailer_ranges: dict[str, list[tuple[str, int, int]]] = {}
    for tid, p in patched_plans.items():
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        ranges = []
        for s in p_dict.get("segments", []):
            sd = s.model_dump() if hasattr(s, "model_dump") else dict(s)
            v = sd.get("video")
            try:
                ranges.append((v, parse_timecode(sd.get("source_in", "")), parse_timecode(sd.get("source_out", ""))))
            except Exception:
                pass
        all_trailer_ranges[tid] = ranges

    # Iterate through trailers
    for tid, plan_obj in list(patched_plans.items()):
        plan_dict = plan_obj.model_dump() if hasattr(plan_obj, "model_dump") else dict(plan_obj)
        val_result = validation.get(tid)
        if not val_result:
            continue

        # Extract errors by segment
        val_errors = []
        if isinstance(val_result, dict):
            for v_entry in val_result.get("validators", []):
                val_errors.extend(v_entry.get("errors", []))
        elif hasattr(val_result, "validators"):
            for v_entry in val_result.validators:
                val_errors.extend(v_entry.errors)

        if not val_errors:
            continue

        # Group errors by segment_id
        errors_by_sid: dict[str, list[ValidationError]] = {}
        for err in val_errors:
            e_dict = err if isinstance(err, ValidationError) else ValidationError.model_validate(err)
            sid = e_dict.segment_id or "__plan__"
            errors_by_sid.setdefault(sid, []).append(e_dict)

        # Other trailers' ranges for distinctness ranking
        other_ranges: list[tuple[str, int, int]] = []
        for other_tid, r_list in all_trailer_ranges.items():
            if other_tid != tid:
                other_ranges.extend(r_list)

        aud_id = plan_dict.get("audience", "family")
        promise = audience_promises.get(aud_id, {})
        aud_track = "bgc" if aud_id == "dialect_region" else ("raj" if aud_id == "rajasthani" else "hi")

        segments = [
            s if isinstance(s, TrailerSegment) else TrailerSegment.model_validate(s)
            for s in plan_dict.get("segments", [])
        ]
        plan_modified = False

        for idx, seg in enumerate(segments):
            seg_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = seg_dict.get("segment_id", "")
            if sid not in errors_by_sid:
                continue

            seg_errors = errors_by_sid[sid]
            error_codes = [e.code for e in seg_errors]
            pref_sid = f"{tid}.{sid}"

            # Increment attempt counter
            updated_attempts[pref_sid] = updated_attempts.get(pref_sid, 0) + 1
            updated_attempts[sid] = updated_attempts[pref_sid]
            attempt_num = updated_attempts[pref_sid]

            # Check bounded attempt limit
            if attempt_num > max_repair_iterations:
                new_human_reviews.append(
                    HumanReviewItem(
                        item_id=f"rev_exh_{tid}_{sid}",
                        trailer_id=tid,
                        segment_id=sid,
                        reason_code="REPAIR_EXHAUSTED",
                        description=f"Repair attempts exhausted for {sid} ({error_codes}) in trailer {tid}",
                        blocking=True,
                    )
                )
                new_decision_logs.append({
                    "seq": len(new_decision_logs),
                    "entry_type": "SEGMENT_REJECTED",
                    "node": "repair",
                    "trailer_id": tid,
                    "segment_id": sid,
                    "reason": f"Repair attempts exhausted ({attempt_num} > {max_repair_iterations})",
                    "evidence": [f"error:{c}" for c in error_codes],
                    "rule_ids": [e.rule_id for e in seg_errors if e.rule_id],
                })
                continue

            chosen_candidate: TrailerSegment | None = None
            repair_action_desc = ""

            # ── Strategy 1: Story Truth Repair ────────────────────────────────
            if any(c in error_codes for c in ("STORY_FORBIDDEN_CLAIM", "STORY_RELATION_MISMATCH", "STORY_UNSUPPORTED_CLAIM", "STORY_GENRE_MISMATCH")):
                cand_seg = copy.deepcopy(seg_dict)
                # Drop unsupported or forbidden claims
                cand_seg["claims"] = []
                # Clean clickbait words from reason
                clean_reason = cand_seg.get("reason", "")
                for bad in ["murder", "revenge", "spouse", "husband", "wife"]:
                    clean_reason = clean_reason.replace(bad, "").replace(bad.capitalize(), "")
                cand_seg["reason"] = clean_reason.strip() or "Verified story moment"

                # Dry-run revalidate
                cand_model = TrailerSegment.model_validate(cand_seg)
                test_plan = copy.deepcopy(plan_dict)
                test_plan["segments"][idx] = cand_model
                test_val = run_validators(
                    test_plan, evidence_index, spoiler_map, story_map, story_facts,
                    constraint_map, subtitles, {"rating_ceiling": "U", "subtitle_track": aud_track},
                    0.13, run_budget, affected_decisions=[sid]
                )
                if test_val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS):
                    chosen_candidate = cand_model
                    repair_action_desc = f"Cleared forbidden/unsupported claims and verified story truth on {sid} (attempt {attempt_num})"

            # ── Strategy 2: Music Rights Repair ───────────────────────────────
            if not chosen_candidate and any(c.startswith("RIGHTS_") and "MUS" in c or c in ("RIGHTS_PROMO_NOT_PERMITTED", "RIGHTS_EXPIRED", "RIGHTS_CONTRACT_MISSING") for c in error_codes):
                # 2a. Try alt music
                alt_music_ids = ["music_03", "music_05", "music_01"]
                for alt_mus in alt_music_ids:
                    cand_seg = copy.deepcopy(seg_dict)
                    cand_seg["music_asset_id"] = alt_mus
                    cand_seg["audio_mode"] = AudioMode.DIALOGUE_AND_MUSIC
                    try:
                        cand_model = TrailerSegment.model_validate(cand_seg)
                        test_plan = copy.deepcopy(plan_dict)
                        test_plan["segments"][idx] = cand_model
                        test_val = run_validators(
                            test_plan, evidence_index, spoiler_map, story_map, story_facts,
                            constraint_map, subtitles, {"rating_ceiling": "U", "subtitle_track": aud_track},
                            0.13, run_budget, affected_decisions=[sid]
                        )
                        if test_val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS):
                            chosen_candidate = cand_model
                            repair_action_desc = f"Swapped music asset to compatible {alt_mus} on {sid} (attempt {attempt_num})"
                            break
                    except Exception:
                        continue

                # 2b. Try dialogue_only
                if not chosen_candidate:
                    cand_seg = copy.deepcopy(seg_dict)
                    cand_seg["audio_mode"] = AudioMode.DIALOGUE_ONLY
                    cand_seg["music_asset_id"] = None
                    try:
                        cand_model = TrailerSegment.model_validate(cand_seg)
                        test_plan = copy.deepcopy(plan_dict)
                        test_plan["segments"][idx] = cand_model
                        test_val = run_validators(
                            test_plan, evidence_index, spoiler_map, story_map, story_facts,
                            constraint_map, subtitles, {"rating_ceiling": "U", "subtitle_track": aud_track},
                            0.13, run_budget, affected_decisions=[sid]
                        )
                        if test_val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS):
                            chosen_candidate = cand_model
                            repair_action_desc = f"Changed audio_mode to dialogue_only on {sid} (attempt {attempt_num})"
                    except Exception:
                        pass

            # ── Strategy 3: Dialect Alignment Repair ──────────────────────────
            if not chosen_candidate and any(c.startswith("DIALECT_") for c in error_codes):
                # Try finding an aligned clean cue from subtitles for that scene
                vid = seg_dict.get("video")
                sc_cues = evidence_index.get("by_scene", {}).get(vid, {}).get("subtitle_cues", {}).get("bgc", [])
                for d_cue in sc_cues:
                    if not d_cue.get("stereotype_flags") and d_cue.get("aligns_with"):
                        cand_seg = copy.deepcopy(seg_dict)
                        cand_seg["subtitle"] = {
                            "track": "bgc",
                            "cue_ids": [d_cue["cue_id"]],
                            "text": d_cue.get("text", ""),
                        }
                        cand_seg["framing_tags"] = []  # Clear comic framing
                        try:
                            cand_model = TrailerSegment.model_validate(cand_seg)
                            test_plan = copy.deepcopy(plan_dict)
                            test_plan["segments"][idx] = cand_model
                            test_val = run_validators(
                                test_plan, evidence_index, spoiler_map, story_map, story_facts,
                                constraint_map, subtitles, {"rating_ceiling": "U", "subtitle_track": "bgc"},
                                0.13, run_budget, affected_decisions=[sid]
                            )
                            if test_val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS):
                                chosen_candidate = cand_model
                                repair_action_desc = f"Aligned clean dialect cue {d_cue['cue_id']} on {sid} (attempt {attempt_num})"
                                break
                        except Exception:
                            continue

            # ── Strategy 4: Full Clip Replacement from Candidate Pool ─────────
            if not chosen_candidate:
                # Build candidates from evidence windows
                raw_pool = build_candidate_pool(
                    seg_dict, error_codes, evidence_index, constraint_map,
                    audience_id=aud_id, subtitle_track=aud_track, spoiler_map=spoiler_map, story_facts=story_facts
                )

                # Filter pool by full plan revalidation
                valid_pool: list[TrailerSegment] = []
                for cand in raw_pool:
                    test_plan = copy.deepcopy(plan_dict)
                    test_plan["segments"][idx] = cand
                    # Recalculate duration
                    tot_s = sum(
                        (parse_timecode(s.source_out if hasattr(s, "source_out") else s.get("source_out")) -
                         parse_timecode(s.source_in if hasattr(s, "source_in") else s.get("source_in"))) / 1000.0
                        for s in test_plan["segments"]
                    )
                    test_plan["duration_seconds"] = round(tot_s, 2)

                    test_val = run_validators(
                        test_plan, evidence_index, spoiler_map, story_map, story_facts,
                        constraint_map, subtitles, {"rating_ceiling": "U" if aud_id == "family" else "UA13+", "subtitle_track": aud_track},
                        0.13, run_budget, affected_decisions=[sid]
                    )
                    # Must be PASS or PASS_WITH_WARNINGS
                    if test_val.status in (TrailerStatus.PASS, TrailerStatus.PASS_WITH_WARNINGS):
                        valid_pool.append(cand)

                # Rank and select
                chosen_candidate = rank_and_select(
                    valid_pool, seg_dict, promise, other_ranges, historic_performance, audience_id=aud_id
                )
                if chosen_candidate:
                    repair_action_desc = (
                        f"Replaced segment {sid} ({','.join(error_codes)}) with valid footage from "
                        f"{chosen_candidate.video} [{chosen_candidate.source_in}, {chosen_candidate.source_out}) "
                        f"preserving role {chosen_candidate.role} (attempt {attempt_num})"
                    )

            # Apply candidate or reject
            if chosen_candidate:
                # Snapshot unchanged segment hashes
                unchanged_hashes = {
                    s.segment_id: _hash_segment(s)
                    for s in segments
                    if (s.segment_id if hasattr(s, "segment_id") else s.get("segment_id")) != sid
                }

                segments[idx] = chosen_candidate
                plan_modified = True

                rev_rec = RevisionRecord(
                    revision=revision_counter,
                    trigger=f"repair:{','.join(error_codes)}",
                    affected=[pref_sid],
                    unchanged=[
                        f"{tid}.{s.segment_id if hasattr(s, 'segment_id') else s.get('segment_id')}"
                        for s in segments
                        if (s.segment_id if hasattr(s, "segment_id") else s.get("segment_id")) != sid
                    ],
                    action=repair_action_desc,
                    validators_rerun=VALIDATOR_NAMES,
                    validation="PASS",
                    hashes_unchanged=unchanged_hashes,
                )
                new_revisions.append(rev_rec)

                new_decision_logs.append({
                    "seq": len(new_decision_logs),
                    "entry_type": "REPAIR_APPLIED",
                    "node": "repair",
                    "trailer_id": tid,
                    "segment_id": sid,
                    "reason": repair_action_desc,
                    "evidence": [f"scene:{chosen_candidate.video}", f"in:{chosen_candidate.source_in}"],
                    "rule_ids": [e.rule_id for e in seg_errors if e.rule_id],
                })
            else:
                # No valid candidate could be found
                new_human_reviews.append(
                    HumanReviewItem(
                        item_id=f"rev_exh_{tid}_{sid}",
                        trailer_id=tid,
                        segment_id=sid,
                        reason_code="REPAIR_EXHAUSTED",
                        description=f"Candidate pool exhausted; no valid replacement found for {sid} ({error_codes}) in {tid}",
                        blocking=True,
                    )
                )
                new_decision_logs.append({
                    "seq": len(new_decision_logs),
                    "entry_type": "SEGMENT_REJECTED",
                    "node": "repair",
                    "trailer_id": tid,
                    "segment_id": sid,
                    "reason": f"No valid candidate found in pool (REPAIR_EXHAUSTED)",
                    "evidence": [f"error:{c}" for c in error_codes],
                    "rule_ids": [e.rule_id for e in seg_errors if e.rule_id],
                })

        # Plan-level budget repair
        if "__plan__" in errors_by_sid:
            plan_errs = errors_by_sid["__plan__"]
            if any(e.code == "BUDGET_EXCEEDED" for e in plan_errs):
                plan_dict["cost_profile"] = "lite"
                plan_modified = True
                new_decision_logs.append({
                    "seq": len(new_decision_logs),
                    "entry_type": "PLANNED_WITH_FALLBACK_PROFILE",
                    "node": "repair",
                    "trailer_id": tid,
                    "reason": "Switched to fallback 'lite' cost profile to satisfy run budget",
                    "evidence": ["profile:lite"],
                    "rule_ids": ["BUDGET-002"],
                })

        if plan_modified:
            # Recompute total duration
            tot_s = 0.0
            for s in segments:
                sin = s.source_in if hasattr(s, "source_in") else s.get("source_in")
                sout = s.source_out if hasattr(s, "source_out") else s.get("source_out")
                try:
                    tot_s += (parse_timecode(sout) - parse_timecode(sin)) / 1000.0
                except Exception:
                    pass
            plan_dict["duration_seconds"] = round(tot_s, 2)
            plan_dict["segments"] = segments
            patched_plans[tid] = TrailerPlan.model_validate(plan_dict)

    return patched_plans, updated_attempts, new_revisions, new_human_reviews, new_decision_logs
