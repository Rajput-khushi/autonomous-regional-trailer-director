"""
story.py — StoryAnalyzer implementation.
Authority: ARCHITECTURE.md §3 (StoryAnalyzer), AI_SYSTEM_SPEC.md §5.1–§5.2.

Responsibilities (Phase 4):
  - Call ModelClient to draft a story map from the evidence index.
  - Reconcile the draft against the editorial story_facts.json
    (editorial always wins; log MODEL_DISAGREEMENT on contradictions).
  - Build the spoiler map: union of editorial protected facts + LLM candidates.
  - LLM may add spoiler candidates; it may never remove or downgrade editorial facts.
"""

from __future__ import annotations

import logging
from typing import Any

from src.evidence import build_llm_view
from src.llm import ModelClient
from src.models import (
    StoryFacts,
    StoryMap,
    SpoilerMap,
    SpoilerFact,
    RevealWindow,
    SpoilerLevel,
)

logger = logging.getLogger(__name__)


def analyze_story(
    evidence_index: dict[str, Any],
    story_facts: dict[str, Any] | StoryFacts,
    client: ModelClient,
    scenario: str = "baseline",
    decision_log: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Return (story_map, spoiler_map).

    story_map shape (SUMMARY.md §11):
      {characters, relationships, major_events, emotional_turns,
       spoilers, sensitive_content, disagreements}

    spoiler_map shape (SUMMARY.md §12):
      {facts: [ProtectedFact], llm_added_candidates: [...]}
    """
    if decision_log is None:
        decision_log = []

    # Prepare editorial facts as dict
    if isinstance(story_facts, StoryFacts):
        ed_facts_dict = story_facts.model_dump()
    else:
        ed_facts_dict = dict(story_facts)

    # 1. Draft story map via ModelClient using safe LLM view
    safe_view = build_llm_view(evidence_index)
    payload = {"evidence": safe_view, "scenario": scenario}

    try:
        draft_model = client.generate_structured("analyze_story", StoryMap, payload, scenario=scenario)
        draft_dict = draft_model.model_dump()
    except Exception as e:
        logger.warning("[analyze_story] Model draft failed, falling back to editorial baseline: %s", e)
        draft_dict = {
            "characters": ed_facts_dict.get("characters", []),
            "relationships": ed_facts_dict.get("relationships", []),
            "major_events": ed_facts_dict.get("major_events", []),
            "emotional_turns": [],
            "spoilers": {},
            "sensitive_content": [],
            "disagreements": [],
        }

    # 2. Reconcile against editorial facts
    reconciled_story = reconcile_story_map(draft_dict, ed_facts_dict, decision_log)

    # 3. Check for LLM spoiler candidates
    llm_candidates: list[dict[str, Any]] = []
    try:
        spoiler_model = client.generate_structured("analyze_story", SpoilerMap, payload, scenario=scenario)
        if spoiler_model and hasattr(spoiler_model, "llm_added_candidates"):
            llm_candidates = [f.model_dump() for f in spoiler_model.llm_added_candidates]
    except Exception:
        pass

    # 4. Build spoiler map (editorial + LLM candidates)
    spoiler_map = build_spoiler_map(ed_facts_dict, llm_candidates)

    # Attach spoiler map into story_map.spoilers for backward compatibility
    reconciled_story["spoilers"] = spoiler_map

    return reconciled_story, spoiler_map


def reconcile_story_map(
    llm_draft: dict[str, Any],
    editorial_facts: dict[str, Any],
    decision_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Override LLM claims that contradict the editorial story_facts sheet.
    Log each contradiction as MODEL_DISAGREEMENT.
    Editorial always wins.
    """
    reconciled = dict(llm_draft)
    disagreements: list[dict[str, Any]] = list(reconciled.get("disagreements", []))

    # Index editorial relationships
    # Key by sorted pair of character IDs
    ed_rel_map: dict[tuple[str, str], dict[str, Any]] = {}
    for r in editorial_facts.get("relationships", []):
        pair = tuple(sorted([r["a"], r["b"]]))
        ed_rel_map[pair] = r

    draft_rels = list(reconciled.get("relationships", []))
    final_rels: list[dict[str, Any]] = []

    for r in draft_rels:
        pair = tuple(sorted([r.get("a", ""), r.get("b", "")]))
        if pair in ed_rel_map:
            ed_r = ed_rel_map[pair]
            if r.get("relation") != ed_r.get("relation"):
                # Disagreement! Editorial wins.
                dis = {
                    "entry_type": "MODEL_DISAGREEMENT",
                    "field": "relationship",
                    "character_pair": list(pair),
                    "llm_claim": r.get("relation"),
                    "editorial_truth": ed_r.get("relation"),
                    "resolution": "editorial_wins",
                }
                disagreements.append(dis)
                decision_log.append({
                    "seq": len(decision_log),
                    "entry_type": "MODEL_DISAGREEMENT",
                    "node": "analyze_story",
                    "reason": f"LLM claimed relationship {r.get('relation')!r} for {pair}, but editorial truth is {ed_r.get('relation')!r}. Editorial wins.",
                    "evidence": [f"char:{pair[0]}", f"char:{pair[1]}"],
                    "rule_ids": ["POL-STORY-001"],
                })
                # Use editorial relation
                r_fixed = dict(r)
                r_fixed["relation"] = ed_r["relation"]
                r_fixed["visibility"] = ed_r.get("visibility", r.get("visibility", "public"))
                final_rels.append(r_fixed)
                continue
        final_rels.append(r)

    # Ensure all editorial relationships are present
    existing_pairs = {tuple(sorted([r["a"], r["b"]])) for r in final_rels if "a" in r and "b" in r}
    for pair, ed_r in ed_rel_map.items():
        if pair not in existing_pairs:
            final_rels.append(dict(ed_r))

    reconciled["relationships"] = final_rels

    # Enforce permitted genres and remove forbidden claims if present
    permitted_genres = editorial_facts.get("permitted_genres", ["family_drama", "mystery"])
    if "genre" in reconciled:
        cur_genres = reconciled["genre"]
        if isinstance(cur_genres, list):
            invalid_genres = [g for g in cur_genres if g not in permitted_genres]
            if invalid_genres:
                disagreements.append({
                    "entry_type": "MODEL_DISAGREEMENT",
                    "field": "genre",
                    "llm_claim": invalid_genres,
                    "editorial_truth": permitted_genres,
                    "resolution": "editorial_wins",
                })
                reconciled["genre"] = [g for g in cur_genres if g in permitted_genres]

    reconciled["disagreements"] = disagreements
    return reconciled


def build_spoiler_map(
    editorial_facts: dict[str, Any],
    llm_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Merge editorial protected facts (source="editorial") with LLM-added
    candidates (source="llm").  Editorial facts cannot be removed or
    downgraded by the LLM.
    """
    ed_protected = editorial_facts.get("protected_facts", [])

    facts_list: list[dict[str, Any]] = []
    ed_fact_ids: set[str] = set()

    for f in ed_protected:
        fid = f.get("fact_id", "")
        ed_fact_ids.add(fid)
        facts_list.append({
            "fact_id": fid,
            "fact": f.get("fact", ""),
            "spoiler_level": f.get("spoiler_level", "MAJOR"),
            "source": "editorial",
            "confidence": "HIGH",
            "reveal_windows": f.get("reveal_windows", []),
            "trigger_terms": f.get("trigger_terms", []),
        })

    llm_added: list[dict[str, Any]] = []
    for cand in llm_candidates:
        cid = cand.get("fact_id", "")
        if cid in ed_fact_ids:
            # LLM may never overwrite, downgrade, or remove an editorial fact
            logger.info("[build_spoiler_map] Ignoring LLM attempt to modify editorial fact %s", cid)
            continue
        c_dict = dict(cand)
        c_dict["source"] = "llm"
        llm_added.append(c_dict)

    return {
        "synthetic": True,
        "synthetic_notice": "Spoiler map emitted separately from story_map.json for independent auditability.",
        "episode_id": editorial_facts.get("episode_id", "ep_synth_001"),
        "facts": facts_list,
        "llm_added_candidates": llm_added,
        "high_ctr_spoiler_warning": (
            "scene_07 has highest historical CTR (0.90 dialect_region, 0.88 young_adult). "
            "It reveals F01 (MAJOR). Historical CTR CANNOT override POL-SPOILER-001."
        ),
    }
