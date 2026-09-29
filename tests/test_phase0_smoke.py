"""
Phase 0 smoke tests — verify imports and structural invariants.
All tests must pass at Phase 0 without any business logic implemented.
"""

from __future__ import annotations

import importlib
import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Import smoke tests
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED_MODULES = [
    "src",
    "src.state",
    "src.models",
    "src.graph",
    "src.llm",
    "src.evidence",
    "src.story",
    "src.constraints",
    "src.planners",
    "src.repair",
    "src.impact",
    "src.logs",
    "src.report",
    "src.validators",
    "src.validators.scene_existence",
    "src.validators.timecode",
    "src.validators.rights",
    "src.validators.spoiler",
    "src.validators.story_truth",
    "src.validators.audience_safety",
    "src.validators.dialect",
    "src.validators.accessibility",
    "src.validators.budget",
    "src.validators.aggregate",
    "src.tools.timecode",
    "src.tools.injection_scan",
    "src.tools.ffprobe",
]


@pytest.mark.parametrize("module_path", REQUIRED_MODULES)
def test_module_imports(module_path: str) -> None:
    """Every required module must import without errors."""
    mod = importlib.import_module(module_path)
    assert mod is not None


# ══════════════════════════════════════════════════════════════════════════════
# TrailerState field count
# ══════════════════════════════════════════════════════════════════════════════

def test_trailer_state_has_exactly_17_fields() -> None:
    """TrailerState must contain exactly the documented 17 fields."""
    from src.state import TrailerState
    import typing
    hints = typing.get_type_hints(TrailerState)
    assert len(hints) == 17, (
        f"Expected 17 TrailerState fields, found {len(hints)}: {list(hints.keys())}"
    )


def test_trailer_state_field_names() -> None:
    """TrailerState must have exactly the documented field names."""
    from src.state import TrailerState
    import typing
    hints = typing.get_type_hints(TrailerState)
    expected = {
        "episode", "evidence", "story_map", "spoiler_map", "constraint_map",
        "audience", "candidate_plan", "validation", "revisions",
        "affected_decisions", "status", "estimated_cost",
        # PD-8 extensions
        "run_config", "change_event", "repair_attempts", "decision_log",
        "human_review",
    }
    assert set(hints.keys()) == expected, (
        f"Field mismatch.\nExpected: {sorted(expected)}\nGot: {sorted(hints.keys())}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Graph node count
# ══════════════════════════════════════════════════════════════════════════════

def test_graph_has_exactly_9_nodes() -> None:
    """The compiled LangGraph must contain exactly 9 physical nodes."""
    from src.graph import graph

    # LangGraph compiled graph exposes its nodes via .nodes or the underlying
    # StateGraph builder. We inspect the graph's node mapping.
    # The graph also includes __start__ and __end__ internal nodes;
    # we count only our application nodes.
    all_nodes = set(graph.nodes.keys())
    internal = {"__start__", "__end__"}
    app_nodes = all_nodes - internal

    expected_nodes = {
        "ingest_evidence",
        "analyze_story",
        "map_constraints",
        "plan_audiences",
        "plan_trailers",
        "validate",
        "repair",
        "analyze_change",
        "finalize",
    }
    assert app_nodes == expected_nodes, (
        f"Node mismatch.\nExpected: {sorted(expected_nodes)}\nGot: {sorted(app_nodes)}"
    )


def test_graph_node_names() -> None:
    """Verify each expected node name is present."""
    from src.graph import graph
    expected = [
        "ingest_evidence", "analyze_story", "map_constraints",
        "plan_audiences", "plan_trailers", "validate",
        "repair", "analyze_change", "finalize",
    ]
    for name in expected:
        assert name in graph.nodes, f"Node {name!r} not found in graph"


# ══════════════════════════════════════════════════════════════════════════════
# Validator package count and names
# ══════════════════════════════════════════════════════════════════════════════

def test_validator_package_has_9_primary_validators() -> None:
    """validators/__init__.py must export exactly 9 primary validator classes."""
    from src import validators
    primary_validator_classes = [
        validators.SceneExistenceValidator,
        validators.TimecodeValidator,
        validators.RightsValidator,
        validators.SpoilerValidator,
        validators.StoryTruthValidator,
        validators.AudienceSafetyValidator,
        validators.DialectConsistencyValidator,
        validators.AccessibilityValidator,
        validators.BudgetValidator,
    ]
    assert len(primary_validator_classes) == 9


def test_all_9_validators_importable() -> None:
    """Each of the 9 validators must be importable and have a .name attribute."""
    from src.validators import (
        SceneExistenceValidator, TimecodeValidator, RightsValidator,
        SpoilerValidator, StoryTruthValidator, AudienceSafetyValidator,
        DialectConsistencyValidator, AccessibilityValidator, BudgetValidator,
    )
    validators = [
        SceneExistenceValidator(), TimecodeValidator(), RightsValidator(),
        SpoilerValidator(), StoryTruthValidator(), AudienceSafetyValidator(),
        DialectConsistencyValidator(), AccessibilityValidator(), BudgetValidator(),
    ]
    names = [v.name for v in validators]
    assert len(set(names)) == 9, f"Expected 9 unique validator names, got: {names}"


# ══════════════════════════════════════════════════════════════════════════════
# Model client smoke tests
# ══════════════════════════════════════════════════════════════════════════════

def test_model_client_classes_importable() -> None:
    """ReplayClient, LiveGeminiClient, and HostileMockClient must be importable."""
    from src.llm import ReplayClient, LiveGeminiClient, HostileMockClient, ModelClient
    assert issubclass(ReplayClient, ModelClient)
    assert issubclass(LiveGeminiClient, ModelClient)
    assert issubclass(HostileMockClient, ModelClient)


def test_replay_client_instantiates() -> None:
    """ReplayClient must instantiate without errors."""
    from src.llm import ReplayClient
    client = ReplayClient(replay_dir="data/replay", strict=False)
    assert client is not None


def test_hostile_mock_client_instantiates() -> None:
    """HostileMockClient must instantiate without errors."""
    from src.llm import HostileMockClient
    client = HostileMockClient(responses={})
    assert client is not None


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic model smoke tests
# ══════════════════════════════════════════════════════════════════════════════

def test_pydantic_models_importable() -> None:
    """All key Pydantic models must be importable from src.models."""
    from src.models import (
        Episode, Scene, DialogueLine, SubtitleCue, StoryFacts,
        Contract, Policy, AudienceProfile, CostSheet, CostProfile,
        TrailerSegment, TrailerPlan, ValidatorResult, TrailerValidation,
        SegmentValidation, RevisionRecord, DecisionLogEntry,
        HumanReviewItem, ChangeEvent, SegmentDependency, SubtitleRef,
        SpoilerLevel, ValidatorStatus, TrailerStatus, RunStatus,
        ConstraintCategory, ChangeEventType,
    )


def test_trailer_status_enum_values() -> None:
    """TrailerStatus must have exactly the documented values."""
    from src.models import TrailerStatus
    assert set(TrailerStatus) == {
        TrailerStatus.PASS,
        TrailerStatus.PASS_WITH_WARNINGS,
        TrailerStatus.REPAIR_REQUIRED,
        TrailerStatus.REJECTED,
    }


def test_spoiler_level_enum_values() -> None:
    """SpoilerLevel must have NONE, LOW, MEDIUM, MAJOR."""
    from src.models import SpoilerLevel
    assert set(s.value for s in SpoilerLevel) == {"NONE", "LOW", "MEDIUM", "MAJOR"}


# ══════════════════════════════════════════════════════════════════════════════
# Structural: no forbidden files
# ══════════════════════════════════════════════════════════════════════════════

def test_no_frontend_files() -> None:
    """No frontend/UI files should exist in the project."""
    import os
    root = __file__
    project_root = str(__file__).split("tests")[0]
    forbidden_extensions = {".html", ".css", ".jsx", ".tsx", ".vue"}
    for dirpath, dirnames, filenames in os.walk(project_root):
        # Skip .git and node_modules
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__"}]
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            assert ext not in forbidden_extensions, (
                f"Frontend file found: {os.path.join(dirpath, fname)}"
            )


def test_no_database_files() -> None:
    """No database files (*.db, *.sqlite) should exist."""
    import os
    project_root = str(__file__).split("tests")[0]
    forbidden_extensions = {".db", ".sqlite", ".sqlite3"}
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
        for fname in filenames:
            ext = os.path.splitext(fname)[1]
            assert ext not in forbidden_extensions, (
                f"Database file found: {os.path.join(dirpath, fname)}"
            )
