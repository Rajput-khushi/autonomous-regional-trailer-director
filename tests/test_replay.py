"""
test_replay_mode.py — Replay determinism and fallback tests (VALIDATION_AND_TESTING.md §7).
Phase 10: Replay hardening, determinism verification, and fallback handling.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from src.graph import graph
from src.models import (
    TrailerPlan,
    StoryMap,
    SpoilerMap,
    ConstraintMap,
)


def test_replay_byte_identical_across_runs(tmp_path):
    """
    Run twice with no API key → byte-identical outputs (excluding nothing;
    no wall-clock in outputs). NFR-01 determinism invariant.
    """
    target_out = tmp_path / "replay_run"

    init_state_1 = {
        "run_config": {
            "mode": "replay",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 5.0,
            "output_dir": str(target_out),
        },
        "decision_log": [],
    }
    init_state_2 = {
        "run_config": {
            "mode": "replay",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 5.0,
            "output_dir": str(target_out),
        },
        "decision_log": [],
    }

    res1 = graph.invoke(init_state_1)
    hashes_1 = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in target_out.iterdir() if f.is_file()
    }

    # Clean directory and run second pass
    import shutil
    shutil.rmtree(target_out)

    res2 = graph.invoke(init_state_2)
    hashes_2 = {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in target_out.iterdir() if f.is_file()
    }

    assert res1["status"] == res2["status"]
    assert set(hashes_1.keys()) == set(hashes_2.keys())
    assert len(hashes_1) >= 9

    for fname in sorted(hashes_1.keys()):
        assert hashes_1[fname] == hashes_2[fname], (
            f"Artifact {fname} differs across replay runs: "
            f"hash1={hashes_1[fname]}, hash2={hashes_2[fname]}"
        )


def test_replay_bogus_live_key_falls_back(tmp_path, monkeypatch):
    """
    Run with bogus key + --mode live → fallback to replay with logged
    MODE_FALLBACK_REPLAY; all required output files exist and validate against schema.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "bogus_test_key_invalid_abc123")

    out_dir = tmp_path / "fallback_run"
    init_state = {
        "run_config": {
            "mode": "live",
            "scenario": "clean",
            "data_dir": "data",
            "run_budget": 5.0,
            "output_dir": str(out_dir),
        },
        "decision_log": [],
    }

    res = graph.invoke(init_state)

    # 1. Verify fallback is logged in decision_log
    dlog = res.get("decision_log", [])
    assert any(
        entry.get("entry_type") == "MODE_FALLBACK_REPLAY"
        for entry in dlog
    ), "Expected MODE_FALLBACK_REPLAY in decision_log"

    # 2. Workflow still completes safely
    assert res["status"] in ("PASS", "PASS_WITH_WARNINGS")

    # 3. Output files exist and are valid against schema
    required_files = [
        "story_map.json",
        "spoiler_map.json",
        "constraint_map.json",
        "family_trailer.json",
        "young_adult_trailer.json",
        "dialect_region_trailer.json",
        "validation_report.md",
        "decision_log.json",
        "run_state.json",
    ]
    for rf in required_files:
        p = out_dir / rf
        assert p.exists(), f"Expected output file {rf} missing"

    # Schema validate sample output files
    with open(out_dir / "story_map.json", "r", encoding="utf-8") as f:
        StoryMap.model_validate(json.load(f))

    with open(out_dir / "constraint_map.json", "r", encoding="utf-8") as f:
        ConstraintMap.model_validate(json.load(f))

    with open(out_dir / "family_trailer.json", "r", encoding="utf-8") as f:
        TrailerPlan.model_validate(json.load(f))
