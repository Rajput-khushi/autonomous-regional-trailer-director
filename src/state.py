"""
state.py — TrailerState TypedDict
Authority: ARCHITECTURE.md §4, SUMMARY.md §8
Exactly 17 fields. Fields 1–12 are from SUMMARY.md §8.
Fields 13–17 are prototype extensions (PD-8) required for logging, config,
resume and bounded repair loops.

Rule: nodes return *partial* state updates; nothing mutates fixtures in place.
"""

from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class TrailerState(TypedDict):
    # ── 1 ─────────────────────────────────────────────────────────────────────
    # Manifest, scenes, dialogue, subtitles, contracts, policies, audiences,
    # history, cost sheet (raw, schema-validated).
    episode: dict[str, Any]

    # ── 2 ─────────────────────────────────────────────────────────────────────
    # Evidence index keyed by scene_id; per-scene windows; injection flags;
    # evidence_ids.
    evidence: dict[str, Any]

    # ── 3 ─────────────────────────────────────────────────────────────────────
    # characters, relationships, major_events, emotional_turns, spoilers,
    # sensitive_content.
    story_map: dict[str, Any]

    # ── 4 ─────────────────────────────────────────────────────────────────────
    # Protected facts, levels, reveal windows, trigger terms
    # (editorial ∪ LLM-added).
    spoiler_map: dict[str, Any]

    # ── 5 ─────────────────────────────────────────────────────────────────────
    # Structured rules with ids, category, severity, scope; plus version.
    constraint_map: dict[str, Any]

    # ── 6 ─────────────────────────────────────────────────────────────────────
    # Profiles + generated audience promises.
    audience: dict[str, Any]

    # ── 7 ─────────────────────────────────────────────────────────────────────
    # {trailer_id: TrailerPlan} for the three trailers, incl. segment-level
    # dependency index.
    candidate_plan: dict[str, Any]

    # ── 8 ─────────────────────────────────────────────────────────────────────
    # {trailer_id: TrailerValidation} with per-validator results.
    validation: dict[str, Any]

    # ── 9 ─────────────────────────────────────────────────────────────────────
    # Revision records (SUMMARY.md §19 shape).
    revisions: list[dict[str, Any]]

    # ── 10 ────────────────────────────────────────────────────────────────────
    # Segment ids (e.g. "family_v1.segment_02") in scope for the next
    # validation pass. Empty list = full validation (all segments).
    affected_decisions: list[str]

    # ── 11 ────────────────────────────────────────────────────────────────────
    # Run status: PASS / PASS_WITH_WARNINGS / REPAIR_REQUIRED / REJECTED
    status: str

    # ── 12 ────────────────────────────────────────────────────────────────────
    # Accumulated model/media cost (synthetic currency unit USD_synthetic).
    estimated_cost: float

    # ── 13 (PD-8) ────────────────────────────────────────────────────────────
    # mode, scenario, cost profile, max_repair_iterations (2),
    # output_dir, evaluation_date, optional change-event path.
    run_config: dict[str, Any]

    # ── 14 (PD-8) ────────────────────────────────────────────────────────────
    # The applied change event (None for a fresh run).
    change_event: dict[str, Any] | None

    # ── 15 (PD-8) ────────────────────────────────────────────────────────────
    # {segment_id: int} — counts repair attempts per segment.
    repair_attempts: dict[str, int]

    # ── 16 (PD-8) ────────────────────────────────────────────────────────────
    # Ordered, append-only log entries (ARCHITECTURE.md §10).
    decision_log: list[dict[str, Any]]

    # ── 17 (PD-8) ────────────────────────────────────────────────────────────
    # Items needing human approval (ARCHITECTURE.md §12).
    human_review: list[dict[str, Any]]
