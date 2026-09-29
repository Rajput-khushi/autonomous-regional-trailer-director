"""
Adversarial test stubs — budget overrun (VALIDATION_AND_TESTING.md §7).
"""

from __future__ import annotations

import pytest

from src.models import ValidatorStatus, TrailerStatus
from src.validators.budget import BudgetValidator
from src.validators.aggregate import run_validators


def test_budget_overrun_fallback_profile():
    """
    run_budget = 0.50 → switches to lite profile (cost 0.13 <= 0.50).
    Warning: PLANNED_WITH_FALLBACK_PROFILE.
    Status: PASS_WITH_WARNINGS.
    """
    validator = BudgetValidator()
    plan = {
        "trailer_id": "family_v1",
        "cost_profile": "lite",
    }
    res = validator.validate_plan(plan, estimated_cost=0.13, run_budget=0.50, lite_cost=0.13)
    assert res.status == ValidatorStatus.WARN
    warn_codes = [w.code for w in res.warnings]
    assert "PLANNED_WITH_FALLBACK_PROFILE" in warn_codes


def test_budget_overrun_both_profiles_rejected():
    """
    run_budget = 0.10 → both full (0.81) and lite (0.13) exceed budget.
    Status: REJECTED (BUDGET_UNRESOLVED).
    Non-repairable error.
    """
    validator = BudgetValidator()
    plan = {
        "trailer_id": "family_v1",
        "cost_profile": "lite",
    }
    # With run_budget=0.10, even lite profile cost (0.13) exceeds budget!
    res = validator.validate_plan(plan, estimated_cost=0.13, run_budget=0.10, lite_cost=0.13)
    assert res.status == ValidatorStatus.FAIL
    error_codes = [e.code for e in res.errors]
    assert "BUDGET_UNRESOLVED" in error_codes
    # Verify non-repairable
    err = next(e for e in res.errors if e.code == "BUDGET_UNRESOLVED")
    assert err.repairable is False
