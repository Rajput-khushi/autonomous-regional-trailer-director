"""
tests/conftest.py — Shared fixtures and helpers for the test suite.
Authority: VALIDATION_AND_TESTING.md §6, IMPLEMENTATION_PLAN.md §8.

Phase 0: scaffolding only.
Business fixtures (baseline_plans, hostile_client) are Phase 3/9 TODOs.
"""

from __future__ import annotations

import pytest
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data"
REPLAY_DIR = DATA_DIR / "replay"
CHANGE_EVENTS_DIR = DATA_DIR / "change_events"

TRAILER_IDS = ("family_v1", "young_adult_v1", "dialect_region_v1")

# ── Minimal run_config fixture ────────────────────────────────────────────────

@pytest.fixture
def base_run_config() -> dict:
    """Minimal run_config for unit tests (replay mode, traps scenario)."""
    return {
        "mode": "replay",
        "scenario": "traps",
        "strict_replay": False,
        "output_dir": "sample_run",
        "evaluation_date": "2026-09-29",
        "max_repair_iterations": 2,
        "run_budget": 2.00,
        "model": {"primary_model": "gemini-2.0-flash", "fallback_model": "mock"},
        "campaign": {"territory": "IN", "start": "2026-10-05", "end": "2026-11-05"},
        "resume_path": None,
        "change_event_path": None,
    }


# ── TODO Phase 3: baseline_plans fixture ──────────────────────────────────────
# @pytest.fixture
# def baseline_plans():
#     """Load trailer_plans.clean.json for use in tests that mutate a copy."""
#     import json
#     with (REPLAY_DIR / "trailer_plans.clean.json").open() as f:
#         return json.load(f)


# ── TODO Phase 9: hostile_client fixture ──────────────────────────────────────
# @pytest.fixture
# def hostile_client():
#     """HostileMockClient pre-configured with plans that violate constraints."""
#     from src.llm import HostileMockClient
#     return HostileMockClient(responses={...})


# ── TODO Phase 3: minimal_state fixture ──────────────────────────────────────
# @pytest.fixture
# def minimal_state(base_run_config):
#     """Minimal valid TrailerState for smoke tests."""
#     from src.state import TrailerState
#     return TrailerState(
#         episode={}, evidence={}, story_map={}, spoiler_map={},
#         constraint_map={"version": 0, "rules": []}, audience={},
#         candidate_plan={}, validation={}, revisions=[], affected_decisions=[],
#         status="PASS", estimated_cost=0.0, run_config=base_run_config,
#         change_event=None, repair_attempts={}, decision_log=[], human_review=[],
#     )
