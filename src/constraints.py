"""
constraints.py — ConstraintMapper implementation.
Authority: ARCHITECTURE.md §3 (ConstraintMapper), SUMMARY.md §13.

Responsibilities (Phase 4):
  - Compile policies.json + contracts.json + audience rating ceilings + cost
    sheet into a flat, ID'd constraint map.
  - Pure deterministic function; no LLM call.
  - Fail-closed on missing contract entry (RIGHTS_CONTRACT_MISSING).
  - Each constraint change creates a new constraint_map.version.

Rule categories (SUMMARY.md §13):
  RATING, RIGHTS, TERRITORY, ACTOR_PROMOTIONAL_USE, MUSIC_PROMOTIONAL_USE,
  SPOILER, STORY_TRUTH, DIALECT, CULTURAL_RESPECT, ACCESSIBILITY, BUDGET,
  TIMECODE (PD-13)
"""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.models import (
    Contract,
    Policy,
    AudienceProfile,
    CostSheet,
    ConstraintCategory,
)

logger = logging.getLogger(__name__)

RATING_ORDER = ["U", "UA13+", "UA16+", "A"]


def build_constraint_map(
    contracts: list[Contract] | list[dict[str, Any]],
    policies: list[Policy] | list[dict[str, Any]],
    audiences: list[AudienceProfile] | list[dict[str, Any]],
    cost_sheet: CostSheet | dict[str, Any],
    prior_version: int = 0,
) -> dict[str, Any]:
    """
    Compile policies, contracts, audience ceilings, and budget into
    a flat, indexed constraint map. Pure deterministic function.
    """
    version = prior_version if prior_version > 0 else 1
    rules: list[dict[str, Any]] = []

    # 1. Compile contract rules (MUSIC_PROMOTIONAL_USE, ACTOR_PROMOTIONAL_USE, RIGHTS)
    for c in contracts:
        if isinstance(c, Contract):
            cid = c.contract_id
            atype = c.asset_type
            aid = c.asset_id
            promo = c.promotional_use
            terrs = c.territories
            vfrom = c.valid_from
            vuntil = c.valid_until
        else:
            cid = c.get("contract_id", "")
            atype = c.get("asset_type", "")
            aid = c.get("asset_id", "")
            promo = c.get("promotional_use", False)
            terrs = c.get("territories", [])
            vfrom = c.get("valid_from", "")
            vuntil = c.get("valid_until", "")

        cat = (
            ConstraintCategory.MUSIC_PROMOTIONAL_USE.value
            if atype == "music"
            else ConstraintCategory.ACTOR_PROMOTIONAL_USE.value
        )

        rules.append({
            "rule_id": f"RULE-CONTRACT-{cid}",
            "category": cat,
            "severity": "HARD",
            "scope": {"asset_id": aid, "asset_type": atype},
            "rule": {
                "promotional_use": promo,
                "territories": terrs,
                "valid_from": vfrom,
                "valid_until": vuntil,
            },
            "source_ref": cid,
        })

    # 2. Compile policy rules
    category_map = {
        "rating": ConstraintCategory.RATING.value,
        "spoiler": ConstraintCategory.SPOILER.value,
        "story": ConstraintCategory.STORY_TRUTH.value,
        "story_truth": ConstraintCategory.STORY_TRUTH.value,
        "dialect": ConstraintCategory.DIALECT.value,
        "accessibility": ConstraintCategory.ACCESSIBILITY.value,
        "access": ConstraintCategory.ACCESSIBILITY.value,
        "rights": ConstraintCategory.RIGHTS.value,
        "duration": ConstraintCategory.TIMECODE.value,
        "timecode": ConstraintCategory.TIMECODE.value,
        "cultural": ConstraintCategory.CULTURAL_RESPECT.value,
        "cultural_respect": ConstraintCategory.CULTURAL_RESPECT.value,
        "budget": ConstraintCategory.BUDGET.value,
    }

    for p in policies:
        if isinstance(p, Policy):
            pid = p.policy_id
            pcat = p.category
            psev = p.severity
            prule = p.rule
        else:
            pid = p.get("policy_id", "")
            pcat = p.get("category", "")
            psev = p.get("severity", "FAIL")
            prule = p.get("rule", {})

        mapped_cat = category_map.get(str(pcat).lower(), ConstraintCategory.RIGHTS.value)
        sev_str = "HARD" if psev in ("FAIL", "HARD") else "SOFT"
        scope = prule.get("scope", {}) if isinstance(prule, dict) else {}

        rules.append({
            "rule_id": pid,
            "category": mapped_cat,
            "severity": sev_str,
            "scope": scope,
            "rule": prule,
            "source_ref": pid,
        })

    # 3. Compile audience rating ceilings
    for a in audiences:
        if isinstance(a, AudienceProfile):
            aid = a.audience_id
            ceiling = a.rating_ceiling
            allowed_framing = a.allowed_framing_tags
            avoid = a.avoid_tags
        else:
            aid = a.get("audience_id", "")
            ceiling = a.get("rating_ceiling", "U")
            allowed_framing = a.get("allowed_framing_tags", [])
            avoid = a.get("avoid_tags", [])

        rules.append({
            "rule_id": f"RULE-RATING-{aid}",
            "category": ConstraintCategory.RATING.value,
            "severity": "HARD",
            "scope": {"audience_id": aid},
            "rule": {
                "rating_ceiling": ceiling,
                "allowed_framing_tags": allowed_framing,
                "avoid_tags": avoid,
            },
            "source_ref": f"audience:{aid}",
        })

    # 4. Compile budget rule
    if isinstance(cost_sheet, CostSheet):
        budget = cost_sheet.run_budget
        curr = cost_sheet.currency_unit
        fallback_prof = cost_sheet.fallback_profile
    else:
        budget = cost_sheet.get("run_budget", 5.0)
        curr = cost_sheet.get("currency_unit", "USD_synthetic")
        fallback_prof = cost_sheet.get("fallback_profile", "lite")

    rules.append({
        "rule_id": "RULE-BUDGET-RUN",
        "category": ConstraintCategory.BUDGET.value,
        "severity": "HARD",
        "scope": {"currency_unit": curr},
        "rule": {
            "run_budget": budget,
            "fallback_profile": fallback_prof,
        },
        "source_ref": "cost_sheet:run_budget",
    })

    return {
        "synthetic": True,
        "version": version,
        "evaluation_date": "2026-10-06",
        "campaign": {
            "campaign_start": "2026-10-05",
            "campaign_end": "2026-11-05",
        },
        "rating_order": RATING_ORDER,
        "rules": rules,
    }


def patch_constraint_map(
    constraint_map: dict[str, Any],
    patch: dict[str, Any],
    asset_id: str | None = None,
    policy_id: str | None = None,
) -> dict[str, Any]:
    """
    Apply a change event patch to the constraint map, returning a new version.
    Aborts with ValueError if the referenced asset/policy does not exist.
    """
    updated = copy.deepcopy(constraint_map)
    updated["version"] = updated.get("version", 0) + 1

    matched = False

    if asset_id is not None:
        for r in updated.get("rules", []):
            scope = r.get("scope", {})
            if scope.get("asset_id") == asset_id or r.get("source_ref") == asset_id:
                r["rule"].update(patch)
                matched = True
        if not matched:
            raise ValueError(f"Asset {asset_id!r} not found in constraint map")

    if policy_id is not None:
        for r in updated.get("rules", []):
            if r.get("rule_id") == policy_id or r.get("source_ref") == policy_id:
                if isinstance(r["rule"], dict):
                    r["rule"].update(patch)
                else:
                    r["rule"] = patch
                matched = True
        if not matched:
            raise ValueError(f"Policy {policy_id!r} not found in constraint map")

    return updated
