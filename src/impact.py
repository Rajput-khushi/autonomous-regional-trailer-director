"""
impact.py — ChangeImpactAnalyzer.
Authority: ARCHITECTURE.md §8, PROTOTYPE_SPEC.md §0, VALIDATION_AND_TESTING.md §6 T5.

Responsibilities:
  - Apply a change event to the constraint map (producing a new incremented version).
  - Reverse lookup through the dependency index (ARCHITECTURE.md §8).
  - Compute affected segments deterministically.
  - Snapshot hashes for unaffected segments (testable invariant: byte-identical before and after).
  - Abort with ValueError on unknown assets/policies (fail-closed, no silent no-ops).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from typing import Any

from src.models import ChangeEvent, ChangeEventType, TrailerPlan, TrailerSegment
from src.constraints import patch_constraint_map
from src.planners import build_dependency_index

logger = logging.getLogger(__name__)


def compute_segment_hash(segment: dict[str, Any] | TrailerSegment) -> str:
    """
    Compute a stable SHA-256 hash for a segment dict or model.
    Wall-clock time must never be included (NFR-01 determinism).
    Transient/nested non-semantic fields are excluded.
    """
    if hasattr(segment, "model_dump"):
        s_dict = segment.model_dump()
    elif isinstance(segment, dict):
        s_dict = copy.deepcopy(segment)
    else:
        s_dict = dict(segment)

    # Remove dynamic runtime attributes if present
    s_dict.pop("dependency", None)

    # Normalize canonical representation with sorted keys and UTF-8
    canonical = json.dumps(s_dict, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def assert_unaffected_unchanged(
    before_hashes: dict[str, str],
    after_plan: dict[str, Any],
    unaffected_ids: list[str],
) -> list[str]:
    """
    Verify that every segment in unaffected_ids has the same hash before
    and after the change run. Returns a list of violated segment ids
    (empty = invariant holds).
    """
    violations: list[str] = []

    # Map all segments in after_plan by full_seg_id
    current_segments: dict[str, Any] = {}
    for tid, plan in after_plan.items():
        if isinstance(plan, TrailerPlan):
            segs = plan.segments
        elif isinstance(plan, dict):
            segs = plan.get("segments", [])
        else:
            segs = getattr(plan, "segments", [])

        for s in segs:
            sid = s.segment_id if hasattr(s, "segment_id") else s.get("segment_id")
            full_id = f"{tid}.{sid}"
            current_segments[full_id] = s

    for full_id in unaffected_ids:
        expected_hash = before_hashes.get(full_id)
        if expected_hash is None:
            continue

        seg = current_segments.get(full_id)
        if seg is None:
            violations.append(full_id)
            continue

        current_hash = compute_segment_hash(seg)
        if current_hash != expected_hash:
            logger.error(
                "[assert_unaffected_unchanged] Hash mismatch for %s: before=%s, after=%s",
                full_id, expected_hash, current_hash
            )
            violations.append(full_id)

    return violations


def analyze_change_impact(
    change_event: ChangeEvent | dict[str, Any],
    candidate_plan: dict[str, Any],
    dependency_index: dict[str, dict[str, Any]] | None,
    constraint_map: dict[str, Any],
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    """
    Apply change event to constraint map, determine affected segments via reverse lookup,
    and snapshot hashes for unaffected segments.

    Returns:
        (new_constraint_map, affected_segment_ids, unaffected_hashes)

    Raises:
        ValueError: If change event references unknown asset, policy, or target.
    """
    if isinstance(change_event, dict):
        event = ChangeEvent.model_validate(change_event)
    else:
        event = change_event

    # Ensure dependency index exists
    if not dependency_index:
        dependency_index = build_dependency_index(candidate_plan)

    event_type = event.type if hasattr(event.type, "value") else str(event.type)
    target_kind = event.target.kind if event.target else "contract"
    target_id = event.target.id if event.target else ""

    # Also support top-level target_asset_id if specified
    if hasattr(event, "target_asset_id") and event.target_asset_id:
        target_id = event.target_asset_id

    patch = event.patch or {}

    # Validate target exists in constraint map (fail-closed, no silent no-ops)
    rules = constraint_map.get("rules", [])
    known_assets = {
        r.get("scope", {}).get("asset_id")
        for r in rules
        if r.get("scope", {}).get("asset_id")
    } | {r.get("source_ref") for r in rules if r.get("source_ref")}

    known_policies = {
        r.get("rule_id") for r in rules if r.get("rule_id")
    } | {r.get("source_ref") for r in rules if r.get("source_ref")}

    affected_segments: list[str] = []

    if event_type == "CONTRACT_UPDATE" or target_kind == "contract":
        # Must exist in known_assets or contract rules
        matched_rule = any(
            r.get("scope", {}).get("asset_id") == target_id
            or r.get("source_ref") == target_id
            or r.get("rule_id") == getattr(event, "target_contract_id", None)
            for r in rules
        )
        if not matched_rule and target_id not in known_assets:
            raise ValueError(f"Unknown asset_id in change event: {target_id!r}")

        # Patch constraint map
        new_cmap = patch_constraint_map(constraint_map, patch, asset_id=target_id)

        # Reverse lookup: find segments whose contracts contain target_id or contract_id
        contract_id = getattr(event, "target_contract_id", None)
        for seg_id, dep in dependency_index.items():
            contracts = dep.get("contracts", [])
            if target_id in contracts or (contract_id and contract_id in contracts):
                affected_segments.append(seg_id)

    elif event_type == "POLICY_UPDATE" or target_kind == "policy":
        if target_id not in known_policies:
            raise ValueError(f"Unknown policy_id in change event: {target_id!r}")

        new_cmap = patch_constraint_map(constraint_map, patch, policy_id=target_id)

        # Reverse lookup: find segments whose policies contain target_id
        for seg_id, dep in dependency_index.items():
            policies = dep.get("policies", [])
            if target_id in policies:
                affected_segments.append(seg_id)

    elif event_type == "AUDIENCE_UPDATE" or target_kind == "audience":
        # Updates audience rating ceiling or framing
        new_cmap = copy.deepcopy(constraint_map)
        new_cmap["version"] = new_cmap.get("version", 0) + 1
        matched = False
        for r in new_cmap.get("rules", []):
            if r.get("scope", {}).get("audience_id") == target_id:
                r["rule"].update(patch)
                matched = True
        if not matched:
            raise ValueError(f"Unknown audience_id in change event: {target_id!r}")

        # Reverse lookup: all segments of trailers for target audience
        for seg_id, dep in dependency_index.items():
            if dep.get("audience") == target_id or seg_id.startswith(f"{target_id}_"):
                affected_segments.append(seg_id)

    elif event_type == "EVIDENCE_UPDATE" or target_kind == "scene":
        new_cmap = copy.deepcopy(constraint_map)
        new_cmap["version"] = new_cmap.get("version", 0) + 1
        # Reverse lookup: segments referencing scene
        for seg_id, dep in dependency_index.items():
            if target_id in dep.get("scene", []):
                affected_segments.append(seg_id)

    elif event_type == "COST_UPDATE" or target_kind == "cost":
        new_cmap = copy.deepcopy(constraint_map)
        new_cmap["version"] = new_cmap.get("version", 0) + 1
        for r in new_cmap.get("rules", []):
            if r.get("rule_id") == "RULE-BUDGET-RUN":
                r["rule"].update(patch)
        # Cost changes do not affect specific segments; plan-level Budget check runs
        affected_segments = []

    else:
        raise ValueError(f"Unsupported change event type: {event_type!r}")

    # Deduplicate and sort affected_segments
    affected_segments = sorted(set(affected_segments))

    # Snapshot hashes for all unaffected segments
    unaffected_hashes: dict[str, str] = {}
    for tid, plan in candidate_plan.items():
        if isinstance(plan, TrailerPlan):
            segs = plan.segments
        elif isinstance(plan, dict):
            segs = plan.get("segments", [])
        else:
            segs = getattr(plan, "segments", [])

        for s in segs:
            sid = s.segment_id if hasattr(s, "segment_id") else s.get("segment_id")
            full_id = f"{tid}.{sid}"
            if full_id not in affected_segments:
                unaffected_hashes[full_id] = compute_segment_hash(s)

    logger.info(
        "[analyze_change_impact] event=%s target=%s affected=%s unaffected=%d",
        event.event_id, target_id, affected_segments, len(unaffected_hashes)
    )

    return new_cmap, affected_segments, unaffected_hashes
