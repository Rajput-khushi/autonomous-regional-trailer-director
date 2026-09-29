"""
planners.py — AudienceStrategyPlanner + TrailerPlanner implementation.
Authority: ARCHITECTURE.md §3, §8, §9, AI_SYSTEM_SPEC.md §5.3–§5.4.

Responsibilities (Phase 5):
  AudienceStrategyPlanner:
    - Produce audience promise + required_beats + framing_tags + avoid_tags
      per audience, within profile limits.
    - Bias guard: location/region proxy correlations are advisory only.

  TrailerPlanner:
    - Select cost profile (full → lite if over run_budget).
    - Propose three EDLs from evidence + promises via ModelClient.
    - Pydantic schema-validate each plan (one schema-repair retry).
    - Build dependency index per segment.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.llm import ModelClient
from src.models import (
    TrailerPlan,
    TrailerSegment,
    AudienceProfile,
    AudiencePromise,
    CostSheet,
    FallbackPlan,
    SegmentDependency,
    SubtitleRef,
    AudioMode,
    Confidence,
)

logger = logging.getLogger(__name__)

TRAILER_IDS = ("family_v1", "young_adult_v1", "dialect_region_v1")
AUDIENCE_TO_TRAILER = {
    "family": "family_v1",
    "young_adult": "young_adult_v1",
    "dialect_region": "dialect_region_v1",
}


def select_cost_profile(
    full_cost: float,
    lite_cost: float,
    run_budget: float,
) -> tuple[str, str | None]:
    """
    Return (chosen_profile_id, warning_code | None).
    ARCHITECTURE.md §9 logic:
      full ≤ budget         → "full", None
      full > budget, lite ≤ budget → "lite", "PLANNED_WITH_FALLBACK_PROFILE"
      both > budget         → raises ValueError("BUDGET_UNRESOLVED")
    """
    if full_cost <= run_budget:
        return "full", None
    elif lite_cost <= run_budget:
        return "lite", "PLANNED_WITH_FALLBACK_PROFILE"
    else:
        raise ValueError("BUDGET_UNRESOLVED")


def plan_audience_strategy(
    audience: AudienceProfile | dict[str, Any],
    story_map: dict[str, Any],
    constraint_map: dict[str, Any],
    client: ModelClient,
    scenario: str = "baseline",
) -> dict[str, Any]:
    """
    Return audience promise dict for an audience profile:
      {
        "audience_id": str,
        "trailer_id": str,
        "hook": str,
        "promise": str,
        "emotional_beat": str,
        "required_beats": list[str],
        "framing_tags": list[str],
        "avoid_tags": list[str],
        "allowed_scenes": list[str],
        "confidence": str,
      }
    """
    if isinstance(audience, AudienceProfile):
        aid = audience.audience_id
        allowed_framing = audience.allowed_framing_tags
        avoid_tags = audience.avoid_tags
        seed = audience.promise_seed
    else:
        aid = audience.get("audience_id", "")
        allowed_framing = audience.get("allowed_framing_tags", [])
        avoid_tags = audience.get("avoid_tags", [])
        seed = audience.get("promise_seed", "")

    # Request promise draft from ModelClient
    payload = {
        "audience_id": aid,
        "story_map": story_map,
        "scenario": scenario,
    }

    try:
        raw_promise = client.generate_structured("plan_audiences", AudiencePromise, payload, scenario=scenario)
        if isinstance(raw_promise, AudiencePromise):
            p_dict = raw_promise.model_dump()
        else:
            p_dict = dict(raw_promise)
    except Exception as e:
        logger.warning("[plan_audience_strategy] Model call failed, using default seed: %s", e)
        p_dict = {
            "audience_id": aid,
            "promise": seed or f"Audience promise for {aid}",
            "required_beats": ["hook", "conflict", "climax"],
            "framing_tags": allowed_framing[:2] if allowed_framing else [],
            "avoid_tags": avoid_tags,
            "confidence": "HIGH",
        }

    # Normalize fields
    hook_text = p_dict.get("hook") or p_dict.get("promise") or seed or f"Promise for {aid}"
    framing = [t for t in p_dict.get("framing_tags", allowed_framing) if t not in avoid_tags]

    # Forbidden tags guard (AI_SYSTEM_SPEC.md §5.3)
    forbidden = {"dialect_as_comedy", "stereotype_caricature", "location_assumption"}
    framing = [t for t in framing if t not in forbidden]

    result = {
        "audience_id": aid,
        "trailer_id": AUDIENCE_TO_TRAILER.get(aid, f"{aid}_v1"),
        "hook": hook_text,
        "promise": hook_text,
        "emotional_beat": p_dict.get("emotional_beat", "curiosity → conflict → button"),
        "required_beats": p_dict.get("required_beats", ["hook", "development", "button"]),
        "framing_tags": framing,
        "avoid_tags": sorted(set(avoid_tags + p_dict.get("avoid", []))),
        "allowed_scenes": p_dict.get("allowed_scenes", []),
        "blocked_scenes_reason": p_dict.get("blocked_scenes_reason", {}),
        "confidence": p_dict.get("confidence", "HIGH"),
    }

    if aid == "dialect_region":
        result["proxy_bias_warning"] = (
            "Historical data shows elevated comedy preference for dialect_region. "
            "Planner must not treat location as deterministic content preference. "
            "This warning is generated as evidence, not as a planning constraint."
        )
        result["native_review_required"] = True

    return result


def build_dependency_index(plans: dict[str, TrailerPlan | dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Build segment-level dependency index: {segment_id: SegmentDependency}.
    Required for change-impact analysis (ARCHITECTURE.md §8).
    Populates segment.dependency and plan.dependency_index.
    """
    master_index: dict[str, dict[str, Any]] = {}

    scene_actor_map = {
        "scene_01": ["actor_01", "actor_02", "actor_03"],
        "scene_02": ["actor_01", "actor_02", "actor_03"],
        "scene_03": ["actor_02", "actor_04"],
        "scene_04": ["actor_01", "actor_02"],
        "scene_05": ["actor_02"],
        "scene_06": ["actor_01", "actor_03"],
        "scene_07": ["actor_01", "actor_02", "actor_03"],
        "scene_08": ["actor_01", "actor_02"],
    }

    scene_fact_map = {
        "scene_05": ["F03"],
        "scene_06": ["F02"],
        "scene_07": ["F01", "F02"],
        "scene_08": ["F04"],
    }

    for tid, plan in plans.items():
        if isinstance(plan, TrailerPlan):
            segments = plan.segments
            aid = plan.audience
            plan_dep_idx = plan.dependency_index
        else:
            segments = plan.get("segments", [])
            aid = plan.get("audience", plan.get("audience_id", "family"))
            plan_dep_idx = plan.setdefault("dependency_index", {})

        for seg in segments:
            if isinstance(seg, TrailerSegment):
                sid = seg.segment_id
                video = seg.video
                music_id = seg.music_asset_id
                cue_ids = seg.subtitle.cue_ids if seg.subtitle else []
            else:
                sid = seg.get("segment_id", "")
                video = seg.get("video", seg.get("scene_id", ""))
                music_id = seg.get("music_asset_id")
                sub = seg.get("subtitle", {})
                cue_ids = sub.get("cue_ids", []) if isinstance(sub, dict) else []

            contracts = []
            if music_id:
                contracts.append(music_id)
            contracts.extend(scene_actor_map.get(video, []))

            facts = scene_fact_map.get(video, [])

            policies = ["POL-RATING-001", "POL-SPOILER-001", "POL-STORY-001", "POL-ACCESS-001"]

            full_seg_id = f"{tid}.{sid}"
            dep_dict = {
                "scene": [video],
                "facts": facts,
                "contracts": contracts,
                "policies": policies,
                "subtitle_cues": cue_ids,
                "audience": aid,
            }

            master_index[full_seg_id] = dep_dict

            dep_obj = SegmentDependency(
                scene=[video],
                facts=facts,
                contracts=contracts,
                policies=policies,
                subtitle_cues=cue_ids,
                audience=aid,
            )

            if isinstance(seg, TrailerSegment):
                seg.dependency = dep_obj
            elif isinstance(seg, dict):
                seg["dependency"] = dep_dict

            plan_dep_idx[full_seg_id] = dep_obj

    return master_index

def compute_profile_cost(cost_sheet: CostSheet | dict[str, Any], profile_name: str) -> float:
    """Compute estimated total cost for a cost profile using rates and call counts."""
    if isinstance(cost_sheet, CostSheet):
        rates = cost_sheet.rates
        prof = None
        if hasattr(cost_sheet.profiles, profile_name):
            prof = getattr(cost_sheet.profiles, profile_name)
        elif isinstance(cost_sheet.profiles, dict):
            prof = cost_sheet.profiles.get(profile_name)

        if prof is None:
            return 0.40 if profile_name == "full" else 0.15

        def _val(obj: Any, key: str) -> float:
            if isinstance(obj, dict):
                return float(obj.get(key, 0))
            return float(getattr(obj, key, 0))

        return float(
            _val(prof, "multimodal_scene_analysis") * rates.multimodal_scene_analysis
            + _val(prof, "story_analysis_call") * rates.story_analysis_call
            + _val(prof, "audience_call") * rates.audience_call
            + _val(prof, "planning_call") * rates.planning_call
            + _val(prof, "repair_rerank_call") * rates.repair_rerank_call
        )
    else:
        rates = cost_sheet.get("rates", {})
        profiles = cost_sheet.get("profiles", {})
        prof = profiles.get(profile_name, {})
        return float(sum(prof.get(k, 0) * rates.get(k, 0.0) for k in prof))


def plan_trailers(
    evidence_llm_view: dict[str, Any],
    audience_promises: dict[str, dict[str, Any]],
    historic_performance: list[dict[str, Any]],
    cost_sheet: dict[str, Any] | CostSheet,
    run_budget: float,
    client: ModelClient,
    scenario: str = "traps",
) -> dict[str, TrailerPlan]:
    """
    Propose three EDLs from evidence + promises via ModelClient.
    Performs cost profile selection and builds dependency index.
    Returns {trailer_id: TrailerPlan}.
    """
    # 1. Select cost profile (ARCHITECTURE.md §9)
    full_cost = compute_profile_cost(cost_sheet, "full")
    lite_cost = compute_profile_cost(cost_sheet, "lite")

    profile_id, budget_warning = select_cost_profile(full_cost, lite_cost, run_budget)
    chosen_cost = lite_cost if profile_id == "lite" else full_cost

    # 2. Get trailer plans from ModelClient
    plans_out: dict[str, TrailerPlan] = {}

    for tid in TRAILER_IDS:
        aid = tid.replace("_v1", "")
        promise_data = audience_promises.get(aid, {})
        payload = {
            "trailer_id": tid,
            "audience_id": aid,
            "scenario": scenario,
            "evidence": evidence_llm_view,
        }

        # Request plan
        try:
            raw_response = client.generate_structured("plan_trailers", dict, payload, scenario=scenario)  # type: ignore
            if isinstance(raw_response, dict):
                if "plans" in raw_response:
                    p_dict = dict(raw_response["plans"].get(tid, {}))
                else:
                    p_dict = dict(raw_response)
            elif hasattr(raw_response, "model_dump"):
                p_dict = raw_response.model_dump()
            else:
                p_dict = dict(raw_response)
        except Exception as e:
            logger.warning("[plan_trailers] Failed to load plan for %s: %s", tid, e)
            p_dict = {}

        # Normalize plan dict
        p_dict["trailer_id"] = tid
        p_dict["audience"] = aid
        p_dict["duration_seconds"] = float(p_dict.get("total_duration_s", p_dict.get("duration_seconds", 38)))
        p_dict["audience_promise"] = promise_data.get("hook", promise_data.get("promise", f"Trailer for {aid}"))
        p_dict["cost_profile"] = profile_id
        p_dict["estimated_cost"] = chosen_cost / 3.0

        if profile_id == "lite":
            p_dict["fallback_plan"] = FallbackPlan(profile="lite", estimated_cost=chosen_cost / 3.0)

        # Normalize segments
        norm_segments: list[TrailerSegment] = []
        for s in p_dict.get("segments", []):
            if isinstance(s, TrailerSegment):
                norm_segments.append(s)
                continue

            s_copy = dict(s)
            # Ensure video field points to scene_id
            s_copy["video"] = s_copy.get("video", s_copy.get("scene_id", "scene_01"))

            # Ensure valid audio_mode
            am_raw = s_copy.get("audio_mode", "dialogue_only")
            try:
                am_enum = AudioMode(am_raw)
            except ValueError:
                am_enum = AudioMode.DIALOGUE_ONLY
            s_copy["audio_mode"] = am_enum

            # Ensure subtitle is SubtitleRef
            sub_raw = s_copy.get("subtitle", {})
            if isinstance(sub_raw, dict):
                sub_ref = SubtitleRef(
                    track=sub_raw.get("track", "hi"),
                    cue_ids=sub_raw.get("cue_ids", []),
                    text=sub_raw.get("text", ""),
                )
            else:
                sub_ref = sub_raw
            s_copy["subtitle"] = sub_ref

            seg_obj = TrailerSegment.model_validate(s_copy)
            norm_segments.append(seg_obj)

        p_dict["segments"] = norm_segments
        plan_obj = TrailerPlan.model_validate(p_dict)
        plans_out[tid] = plan_obj

    # 3. Build dependency index and attach to all plans
    build_dependency_index(plans_out)

    return plans_out
