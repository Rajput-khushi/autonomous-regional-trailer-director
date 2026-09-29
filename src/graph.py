"""
graph.py — LangGraph graph definition with nine physical node stubs.
Authority: ARCHITECTURE.md §5, PROTOTYPE_SPEC.md §0.

Physical nodes (1:1 with logical components):
  1. ingest_evidence     ← EvidenceBuilder
  2. analyze_story       ← StoryAnalyzer
  3. map_constraints     ← ConstraintMapper
  4. plan_audiences      ← AudienceStrategyPlanner
  5. plan_trailers       ← TrailerPlanner
  6. validate            ← Validator (9 sub-validators)
  7. repair              ← RepairAgent
  8. analyze_change      ← ChangeImpactAnalyzer
  9. finalize            ← Finalizer

Routing:
  START → {analyze_change (if change_event set) | ingest_evidence} → … → validate
  validate → {repair | finalize} based on status
  repair → validate (bounded loop; max_repair_iterations=2)
  finalize → END

Phase 0: all node bodies are stubs that log and return empty partial updates.
Business logic is added in Phases 3–8.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from langgraph.graph import StateGraph, START, END

from src.state import TrailerState
from src.evidence import load_and_validate_fixtures, build_evidence_index, build_llm_view
from src.story import analyze_story as run_story_analyzer
from src.constraints import build_constraint_map
from src.planners import plan_audience_strategy, plan_trailers as run_trailer_planner
from src.llm import build_client
from src.models import StoryFacts, TrailerStatus, HumanReviewItem, ChangeEvent
from src.validators.aggregate import run_validators, aggregate_run_status
from src.repair import repair_plan
from src.tools.distinctness import compute_distinctness_report
from src.impact import analyze_change_impact, assert_unaffected_unchanged
from src.report import write_all_outputs

logger = logging.getLogger(__name__)

# Trailer IDs (PROTOTYPE_SPEC.md §0)
TRAILER_IDS = ("family_v1", "young_adult_v1", "dialect_region_v1")


# ══════════════════════════════════════════════════════════════════════════════
# Node 1 — ingest_evidence  (EvidenceBuilder)
# ══════════════════════════════════════════════════════════════════════════════

def ingest_evidence(state: TrailerState) -> dict[str, Any]:
    """
    Load and schema-validate all input fixtures.
    Build evidence index (scene/time-range facts, injection flags, LLM view).

    Writes: episode, evidence, decision_log entry (PACKAGE_LOADED).
    """
    run_cfg = state.get("run_config", {})
    data_dir = run_cfg.get("data_dir", "data")
    fixtures = load_and_validate_fixtures(Path(data_dir))
    index = build_evidence_index(fixtures)

    raw_episode = dict(fixtures["_raw"]["episode"])
    raw_episode["_validated_fixtures"] = fixtures

    decision_log = list(state.get("decision_log", []))
    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "PACKAGE_LOADED",
        "node": "ingest_evidence",
        "reason": f"Loaded and validated 10 fixtures. Indexed {len(index['by_scene'])} scenes.",
        "evidence": ["scene:all"],
        "rule_ids": [],
    })

    return {
        "episode": raw_episode,
        "evidence": index,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 2 — analyze_story  (StoryAnalyzer)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_story(state: TrailerState) -> dict[str, Any]:
    """
    Draft story map from evidence; reconcile with editorial story_facts.json
    to produce spoiler map (LLM may add; editorial sheet wins on conflicts).

    Reads: evidence, episode
    Writes: story_map, spoiler_map, estimated_cost, decision_log
    """
    run_cfg = state.get("run_config", {})
    client = run_cfg.get("model_client") or build_client(run_cfg)
    scenario = run_cfg.get("scenario", "baseline")

    ev_index = state.get("evidence", {})
    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    story_facts = fixtures.get("story_facts")
    if story_facts is None:
        data_dir = run_cfg.get("data_dir", "data")
        raw_story = json.loads((Path(data_dir) / "story_facts.json").read_text(encoding="utf-8"))
        story_facts = StoryFacts.model_validate(raw_story)

    decision_log = list(state.get("decision_log", []))
    story_map, spoiler_map = run_story_analyzer(
        ev_index, story_facts, client, scenario=scenario, decision_log=decision_log
    )

    call_cost = client.estimated_cost("analyze_story", {})

    if run_cfg.get("mode") == "live" or getattr(client, "fallback_used", False):
        if not any(d.get("entry_type") == "MODE_FALLBACK_REPLAY" for d in decision_log):
            decision_log.append({
                "seq": len(decision_log),
                "entry_type": "MODE_FALLBACK_REPLAY",
                "node": "analyze_story",
                "reason": "Live client fell back to ReplayClient",
                "evidence": ["client:LiveGeminiClient", "fallback:ReplayClient"],
                "rule_ids": [],
            })

    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "STORY_ANALYSIS_COMPLETED",
        "node": "analyze_story",
        "reason": f"Reconciled story map with {len(story_map.get('characters', []))} characters and {len(spoiler_map.get('facts', []))} protected facts.",
        "evidence": [f"fact:{f['fact_id']}" for f in spoiler_map.get("facts", [])],
        "rule_ids": ["POL-STORY-001", "POL-SPOILER-001"],
    })

    return {
        "story_map": story_map,
        "spoiler_map": spoiler_map,
        "estimated_cost": state.get("estimated_cost", 0.0) + call_cost,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 3 — map_constraints  (ConstraintMapper)
# ══════════════════════════════════════════════════════════════════════════════

def map_constraints(state: TrailerState) -> dict[str, Any]:
    """
    Compile policies.json + contracts.json (+ audience rating ceilings, cost
    sheet) into a flat, ID'd constraint map.  Pure deterministic function;
    no LLM call.  Fail-closed on missing contract.

    Reads: episode
    Writes: constraint_map, decision_log
    """
    run_cfg = state.get("run_config", {})
    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    data_dir = run_cfg.get("data_dir", "data")

    if not fixtures:
        fixtures = load_and_validate_fixtures(Path(data_dir))

    cmap = build_constraint_map(
        fixtures["contracts"],
        fixtures["policies"],
        fixtures["audiences"],
        fixtures["cost_sheet"],
        prior_version=0,
    )

    decision_log = list(state.get("decision_log", []))
    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "CONSTRAINTS_MAPPED",
        "node": "map_constraints",
        "reason": f"Compiled {len(cmap.get('rules', []))} rules into constraint map v{cmap.get('version', 1)}.",
        "evidence": [],
        "rule_ids": [r["rule_id"] for r in cmap.get("rules", [])[:5]],
    })

    return {
        "constraint_map": cmap,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 4 — plan_audiences  (AudienceStrategyPlanner)
# ══════════════════════════════════════════════════════════════════════════════

def plan_audiences(state: TrailerState) -> dict[str, Any]:
    """
    Produce audience promise + required beats + avoid-tags per audience,
    within profile limits.

    Reads: audience, story_map, constraint_map
    Writes: audience (with .promises populated), estimated_cost, decision_log
    """
    run_cfg = state.get("run_config", {})
    client = run_cfg.get("model_client") or build_client(run_cfg)
    scenario = run_cfg.get("scenario", "baseline")

    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    if not fixtures:
        fixtures = load_and_validate_fixtures(Path(run_cfg.get("data_dir", "data")))

    audiences = fixtures["audiences"]
    story_map = state.get("story_map", {})
    constraint_map = state.get("constraint_map", {})

    promises: dict[str, Any] = {}
    total_cost = 0.0

    for a in audiences:
        strat = plan_audience_strategy(a, story_map, constraint_map, client, scenario=scenario)
        promises[a.audience_id] = strat
        total_cost += client.estimated_cost("plan_audiences", {"audience_id": a.audience_id})

    decision_log = list(state.get("decision_log", []))
    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "AUDIENCE_STRATEGY_PLANNED",
        "node": "plan_audiences",
        "reason": f"Planned strategy and promises for {len(promises)} audience segments.",
        "evidence": [f"audience:{aid}" for aid in promises],
        "rule_ids": ["POL-RATING-001"],
    })

    aud_state = dict(state.get("audience", {}))
    aud_state["promises"] = promises
    aud_state["profiles"] = [a.model_dump() for a in audiences]

    return {
        "audience": aud_state,
        "estimated_cost": state.get("estimated_cost", 0.0) + total_cost,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 5 — plan_trailers  (TrailerPlanner)
# ══════════════════════════════════════════════════════════════════════════════

def plan_trailers(state: TrailerState) -> dict[str, Any]:
    """
    Choose cost profile; propose three EDLs from evidence + promises;
    schema-validate; build dependency index.

    Reads: evidence, audience.promises, episode.cost_sheet
    Writes: candidate_plan, estimated_cost, decision_log (PLAN_PROPOSED)
    """
    run_cfg = state.get("run_config", {})
    client = run_cfg.get("model_client") or build_client(run_cfg)
    scenario = run_cfg.get("scenario", "traps")

    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    if not fixtures:
        fixtures = load_and_validate_fixtures(Path(run_cfg.get("data_dir", "data")))

    evidence_view = build_llm_view(state.get("evidence", {}))
    promises = state.get("audience", {}).get("promises", {})
    run_budget = run_cfg.get("run_budget", 5.0)

    plans = run_trailer_planner(
        evidence_view,
        promises,
        fixtures.get("hp_rows", []),
        fixtures.get("cost_sheet", {}),
        run_budget,
        client,
        scenario=scenario,
    )

    decision_log = list(state.get("decision_log", []))
    for tid, p in plans.items():
        decision_log.append({
            "seq": len(decision_log),
            "entry_type": "PLAN_PROPOSED",
            "node": "plan_trailers",
            "reason": f"Proposed candidate trailer plan for {tid} with {len(p.segments)} segments.",
            "evidence": [f"trailer:{tid}"],
            "rule_ids": [],
        })

    total_cost = client.estimated_cost("plan_trailers", {})

    return {
        "candidate_plan": plans,
        "estimated_cost": state.get("estimated_cost", 0.0) + total_cost,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 6 — validate  (Validator: 9 sub-validators)
# ══════════════════════════════════════════════════════════════════════════════

def validate(state: TrailerState) -> dict[str, Any]:
    """
    Run all nine validators; aggregate to per-trailer and run status.
    Scope-aware: if affected_decisions is non-empty, segment-level validators
    run only for those segments; plan-level checks always run.

    Reads: candidate_plan, evidence, spoiler_map, constraint_map, episode, audience
    Writes: validation, status, affected_decisions, decision_log, human_review_items
    """
    plans = state.get("candidate_plan", {})
    ev_index = state.get("evidence", {})
    spoiler_map = state.get("spoiler_map", {})
    story_map = state.get("story_map", {})
    constraint_map = state.get("constraint_map", {})
    run_cfg = state.get("run_config", {})
    run_budget = run_cfg.get("run_budget", 2.0)
    max_attempts = run_cfg.get("max_repair_iterations", 2)
    repair_attempts = dict(state.get("repair_attempts", {}))
    affected_decisions = list(state.get("affected_decisions", []))
    estimated_cost = state.get("estimated_cost", 0.13)

    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    if not fixtures:
        fixtures = load_and_validate_fixtures(Path(run_cfg.get("data_dir", "data")))

    story_facts = fixtures.get("story_facts")
    if story_facts is None:
        data_dir = run_cfg.get("data_dir", "data")
        raw_story = json.loads((Path(data_dir) / "story_facts.json").read_text(encoding="utf-8"))
        story_facts = StoryFacts.model_validate(raw_story)

    subtitles = fixtures.get("subtitles", {})
    audiences = fixtures.get("audiences", [])
    aud_by_id = {a.audience_id: a for a in audiences}

    decision_log = list(state.get("decision_log", []))
    human_reviews = list(state.get("human_review_items", []))

    validation_dict: dict[str, Any] = {}
    failing_segments: list[str] = []

    for tid, p in plans.items():
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        aud_id = p_dict.get("audience", "family")
        aud_profile = aud_by_id.get(aud_id, {"rating_ceiling": "U", "subtitle_track": "hi"})

        t_val = run_validators(
            p_dict,
            evidence_index=ev_index,
            spoiler_map=spoiler_map,
            story_map=story_map,
            story_facts=story_facts.model_dump() if hasattr(story_facts, "model_dump") else story_facts,
            constraint_map=constraint_map,
            subtitles=subtitles.model_dump() if hasattr(subtitles, "model_dump") else subtitles,
            audience_profile=aud_profile,
            estimated_cost=estimated_cost,
            run_budget=run_budget,
            affected_decisions=affected_decisions,
            repair_attempts=repair_attempts,
            max_repair_iterations=max_attempts,
            human_review_items=human_reviews,
        )
        validation_dict[tid] = t_val

        # Collect failing segment ids
        for v in t_val.validators:
            for err in v.errors:
                if err.segment_id and err.segment_id != "__plan__":
                    failing_segments.append(f"{tid}.{err.segment_id}")
                    failing_segments.append(err.segment_id)

        decision_log.append({
            "seq": len(decision_log),
            "entry_type": "VALIDATION_RESULT",
            "node": "validate",
            "trailer_id": tid,
            "reason": f"Validated {tid} with status {t_val.status.value}",
            "evidence": [f"status:{t_val.status.value}"],
            "rule_ids": [e.rule_id for v in t_val.validators for e in v.errors if e.rule_id],
        })

    # Run status aggregation
    run_status = aggregate_run_status(validation_dict)
    run_status_str = run_status.value if hasattr(run_status, "value") else str(run_status)

    # Check if attempts exhausted for REPAIR_REQUIRED
    if run_status_str == "REPAIR_REQUIRED":
        failing_sids = [s for s in failing_segments if "." not in s]
        if failing_sids and all(repair_attempts.get(sid, 0) >= max_attempts for sid in failing_sids):
            run_status_str = "REJECTED"

    return {
        "validation": validation_dict,
        "status": run_status_str,
        "affected_decisions": sorted(set(failing_segments)),
        "decision_log": decision_log,
        "human_review_items": human_reviews,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 7 — repair  (RepairAgent)
# ══════════════════════════════════════════════════════════════════════════════

def repair(state: TrailerState) -> dict[str, Any]:
    """
    For failed segments: build candidate pool → filter by full revalidation
    → rank deterministically → apply; log revision record.

    Reads: candidate_plan, validation, evidence, constraint_map, audience, etc.
    Writes: candidate_plan (patched), revisions, repair_attempts, decision_log, human_review_items
    """
    plans = state.get("candidate_plan", {})
    validation = state.get("validation", {})
    ev_index = state.get("evidence", {})
    constraint_map = state.get("constraint_map", {})
    promises = state.get("audience", {}).get("promises", {})
    repair_attempts = dict(state.get("repair_attempts", {}))
    revisions = list(state.get("revisions", []))
    revision_counter = len(revisions) + 1
    decision_log = list(state.get("decision_log", []))
    human_reviews = list(state.get("human_review_items", []))

    run_cfg = state.get("run_config", {})
    run_budget = run_cfg.get("run_budget", 2.0)
    max_attempts = run_cfg.get("max_repair_iterations", 2)

    fixtures = state.get("episode", {}).get("_validated_fixtures", {})
    if not fixtures:
        fixtures = load_and_validate_fixtures(Path(run_cfg.get("data_dir", "data")))

    story_facts = fixtures.get("story_facts")
    subtitles = fixtures.get("subtitles", {})
    hp_rows = fixtures.get("hp_rows", [])

    patched_plans, updated_attempts, new_revs, new_hr, new_dlog = repair_plan(
        candidate_plan=plans,
        validation=validation,
        evidence_index=ev_index,
        constraint_map=constraint_map,
        audience_promises=promises,
        repair_attempts=repair_attempts,
        revision_counter=revision_counter,
        spoiler_map=state.get("spoiler_map", {}),
        story_map=state.get("story_map", {}),
        story_facts=story_facts.model_dump() if hasattr(story_facts, "model_dump") else story_facts,
        subtitles=subtitles.model_dump() if hasattr(subtitles, "model_dump") else subtitles,
        cost_sheet=fixtures.get("cost_sheet", {}),
        run_budget=run_budget,
        max_repair_iterations=max_attempts,
        historic_performance=hp_rows,
    )

    revisions.extend(new_revs)
    human_reviews.extend(new_hr)
    decision_log.extend(new_dlog)

    return {
        "candidate_plan": patched_plans,
        "revisions": revisions,
        "repair_attempts": updated_attempts,
        "decision_log": decision_log,
        "human_review_items": human_reviews,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 8 — analyze_change  (ChangeImpactAnalyzer)
# ══════════════════════════════════════════════════════════════════════════════

def analyze_change(state: TrailerState) -> dict[str, Any]:
    """
    Apply change event to constraint map; recompute dependency index;
    compute affected segments; snapshot unaffected hashes.

    Reads: run_state (loaded from prior run_state.json), change_event
    Writes: constraint_map (new version), affected_decisions, decision_log
    """
    change_evt_raw = state.get("change_event")
    if isinstance(change_evt_raw, (str, Path)):
        change_evt = json.loads(Path(change_evt_raw).read_text(encoding="utf-8"))
    else:
        change_evt = change_evt_raw or {}

    candidate_plan = state.get("candidate_plan", {})
    dep_idx = state.get("dependency_index")
    constraint_map = state.get("constraint_map", {})
    decision_log = list(state.get("decision_log", []))

    new_cmap, affected_sids, unaffected_hashes = analyze_change_impact(
        change_event=change_evt,
        candidate_plan=candidate_plan,
        dependency_index=dep_idx,
        constraint_map=constraint_map,
    )

    evt_obj = ChangeEvent.model_validate(change_evt) if isinstance(change_evt, dict) else change_evt
    evt_id = getattr(evt_obj, "event_id", "CE-001")
    evt_desc = getattr(evt_obj, "description", "")
    evt_type = getattr(evt_obj, "type", "CONTRACT_UPDATE")
    if hasattr(evt_type, "value"):
        evt_type = evt_type.value

    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "CHANGE_EVENT",
        "node": "analyze_change",
        "reason": f"Applied change event {evt_id}: {evt_desc}",
        "evidence": [f"event_id:{evt_id}", f"type:{evt_type}"],
        "rule_ids": [f"version:{new_cmap.get('version')}"],
    })

    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "IMPACT_ANALYSIS",
        "node": "analyze_change",
        "reason": f"Reverse lookup identified {len(affected_sids)} affected decisions",
        "evidence": affected_sids,
        "rule_ids": [],
    })

    # Store unaffected hashes in run_config for downstream invariant check
    run_cfg = dict(state.get("run_config", {}))
    run_cfg["_unaffected_hashes"] = unaffected_hashes

    return {
        "constraint_map": new_cmap,
        "affected_decisions": affected_sids,
        "decision_log": decision_log,
        "run_config": run_cfg,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Node 9 — finalize  (Finalizer)
# Three modes: finalize / finalize_with_warnings / log_and_human_review
# ══════════════════════════════════════════════════════════════════════════════

def finalize(state: TrailerState) -> dict[str, Any]:
    """
    Compute final status; write all outputs to output_dir:
      story_map.json, spoiler_map.json, constraint_map.json,
      family_trailer.json, young_adult_trailer.json, dialect_region_trailer.json,
      validation_report.md, decision_log.json, revision_log.json, run_state.json.

    Mode selected from status:
      PASS              → finalize
      PASS_WITH_WARNINGS → finalize_with_warnings
      REJECTED          → log_and_human_review

    Reads: everything
    Writes: output files, decision_log (RUN_FINALIZED)
    """
    decision_log = list(state.get("decision_log", []))
    status = state.get("status", "PASS")
    run_cfg = state.get("run_config", {})

    # Invariant verification: if change-impact run had unaffected hashes, verify byte-identical
    unaffected_hashes = run_cfg.get("_unaffected_hashes")
    if unaffected_hashes:
        violations = assert_unaffected_unchanged(
            unaffected_hashes,
            state.get("candidate_plan", {}),
            list(unaffected_hashes.keys()),
        )
        if violations:
            logger.error("[finalize] Invariant violation: unaffected segments modified: %s", violations)
            raise AssertionError(f"Unaffected segments modified during change run: {violations}")

    decision_log.append({
        "seq": len(decision_log),
        "entry_type": "RUN_FINALIZED",
        "node": "finalize",
        "reason": f"Workflow run finalized with status {status}",
        "evidence": [f"status:{status}"],
        "rule_ids": [],
    })

    output_dir = run_cfg.get("output_dir", "sample_run")
    state_to_write = dict(state)
    state_to_write["decision_log"] = decision_log

    try:
        write_all_outputs(state_to_write, Path(output_dir))
    except Exception as e:
        logger.warning("[finalize] Failed to write output files to %s: %s", output_dir, e)

    return {
        "status": status,
        "decision_log": decision_log,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Routing functions
# ══════════════════════════════════════════════════════════════════════════════

def _route_entry(state: TrailerState) -> Literal["ingest_evidence", "analyze_change"]:
    """
    Choose workflow entry point:
    - If change_event is set (and we have a prior run state) → analyze_change
    - Otherwise → ingest_evidence (fresh run)
    """
    if state.get("change_event") is not None:
        return "analyze_change"
    return "ingest_evidence"


def _route_after_validation(
    state: TrailerState,
) -> Literal["repair", "finalize"]:
    """
    Decision table (ARCHITECTURE.md §5):

    | Condition                                           | Next    |
    |-----------------------------------------------------|---------|
    | REPAIR_REQUIRED + attempts remain                   | repair  |
    | REPAIR_REQUIRED + attempts exhausted                | finalize|
    | REJECTED                                            | finalize|
    | PASS / PASS_WITH_WARNINGS                           | finalize|
    """
    status = state.get("status", "PASS")
    if status != "REPAIR_REQUIRED":
        return "finalize"

    max_attempts = state.get("run_config", {}).get("max_repair_iterations", 2)
    repair_attempts: dict[str, int] = state.get("repair_attempts", {})

    # If any failing segment still has attempts remaining, go to repair.
    # affected_decisions holds the currently failing segment ids.
    affected = state.get("affected_decisions", [])
    if any(repair_attempts.get(sid, 0) < max_attempts for sid in affected):
        return "repair"

    return "finalize"


# ══════════════════════════════════════════════════════════════════════════════
# Graph builder
# ══════════════════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    """
    Wire the nine-node LangGraph graph.
    Returns the compiled graph ready to invoke.
    """
    builder = StateGraph(TrailerState)

    # ── Register nodes ────────────────────────────────────────────────────────
    builder.add_node("ingest_evidence", ingest_evidence)
    builder.add_node("analyze_story",   analyze_story)
    builder.add_node("map_constraints", map_constraints)
    builder.add_node("plan_audiences",  plan_audiences)
    builder.add_node("plan_trailers",   plan_trailers)
    builder.add_node("validate",        validate)
    builder.add_node("repair",          repair)
    builder.add_node("analyze_change",  analyze_change)
    builder.add_node("finalize",        finalize)

    # ── Entry routing ─────────────────────────────────────────────────────────
    builder.add_conditional_edges(
        START,
        _route_entry,
        {
            "ingest_evidence": "ingest_evidence",
            "analyze_change":  "analyze_change",
        },
    )

    # ── Fresh-run linear path ─────────────────────────────────────────────────
    builder.add_edge("ingest_evidence", "analyze_story")
    builder.add_edge("analyze_story",   "map_constraints")
    builder.add_edge("map_constraints", "plan_audiences")
    builder.add_edge("plan_audiences",  "plan_trailers")
    builder.add_edge("plan_trailers",   "validate")

    # ── Change-impact path ────────────────────────────────────────────────────
    builder.add_edge("analyze_change", "validate")

    # ── Post-validation routing ───────────────────────────────────────────────
    builder.add_conditional_edges(
        "validate",
        _route_after_validation,
        {
            "repair":   "repair",
            "finalize": "finalize",
        },
    )

    # ── Repair loops back to validate (bounded by _route_after_validation) ────
    builder.add_edge("repair", "validate")

    # ── Terminal edge ─────────────────────────────────────────────────────────
    builder.add_edge("finalize", END)

    return builder.compile()


# ── Module-level compiled graph (import this in main.py and tests) ────────────
graph = build_graph()
