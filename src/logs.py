"""
logs.py — Decision log and revision log writers.
Authority: ARCHITECTURE.md §10, DATA_SPEC.md §19–§20.

Entry types: PACKAGE_LOADED, INJECTION_DETECTED, MODEL_CALL,
MODEL_DISAGREEMENT, AUDIENCE_PROMISE, PLAN_PROPOSED, VALIDATION_RESULT,
REPAIR_APPLIED, SEGMENT_REJECTED, CHANGE_EVENT, IMPACT_ANALYSIS,
HUMAN_REVIEW_FLAG, RUN_FINALIZED.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import DecisionLogEntry, RevisionRecord


def append_log_entry(
    decision_log: list[dict[str, Any]],
    entry_type: str,
    node: str,
    reason: str = "",
    trailer_id: str | None = None,
    segment_id: str | None = None,
    evidence: list[str] | None = None,
    rule_ids: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Return a new list with the entry appended (immutable update pattern).
    seq is assigned as len(decision_log) so it is always monotonically
    increasing and deterministic (never uses wall-clock time).
    """
    new_log = list(decision_log)
    entry = {
        "seq": len(new_log),
        "entry_type": entry_type,
        "type": entry_type,
        "node": node,
        "trailer_id": trailer_id,
        "segment_id": segment_id,
        "reason": reason,
        "evidence": evidence or [],
        "rule_ids": rule_ids or [],
        "details": details or {},
    }
    new_log.append(entry)
    return new_log


def write_decision_log(log: list[dict[str, Any] | DecisionLogEntry], output_dir: Path) -> Path:
    """
    Write decision_log.json to output_dir.
    Ensures deterministic sorted output without wall-clock timestamps.
    """
    out_path = Path(output_dir) / "decision_log.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_entries = []
    for e in log:
        if hasattr(e, "model_dump"):
            d = e.model_dump(by_alias=True)
        elif isinstance(e, dict):
            d = dict(e)
        else:
            d = dict(e)
        normalized_entries.append(d)

    wrapper = {
        "synthetic": True,
        "synthetic_notice": "Deterministic audit decision log.",
        "entries": normalized_entries,
    }

    out_path.write_text(json.dumps(wrapper, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return out_path


def write_revision_log(revisions: list[dict[str, Any] | RevisionRecord], output_dir: Path) -> Path:
    """
    Write revision_log.json to output_dir.
    """
    out_path = Path(output_dir) / "revision_log.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_revs = []
    for r in revisions:
        if hasattr(r, "model_dump"):
            d = r.model_dump()
        elif isinstance(r, dict):
            d = dict(r)
        else:
            d = dict(r)
        normalized_revs.append(d)

    wrapper = {
        "synthetic": True,
        "synthetic_notice": "Deterministic revision log tracking segment repairs.",
        "revisions": normalized_revs,
    }

    out_path.write_text(json.dumps(wrapper, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return out_path
