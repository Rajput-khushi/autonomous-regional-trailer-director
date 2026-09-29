"""
Validator 9 — BudgetValidator (deterministic).
Authority: VALIDATION_AND_TESTING.md §4.9, ARCHITECTURE.md §7, §9.

Checks:
  - Plan cost profile fallback warning: PLANNED_WITH_FALLBACK_PROFILE (warn)
  - Estimated cost <= run_budget.
  - If both full and lite profiles exceed budget → BUDGET_UNRESOLVED (fail, non-repairable).
  - Otherwise budget overrun → BUDGET_EXCEEDED (fail).
"""

from __future__ import annotations

from typing import Any

from src.models import (
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
)


class BudgetValidator:
    """
    Deterministic plan-level validator. Imports no planner or LLM code.
    """

    name = "BudgetValidator"

    def validate_plan(
        self,
        plan: dict[str, Any],
        estimated_cost: float,
        run_budget: float,
        lite_cost: float = 0.13,
    ) -> ValidatorResult:
        """
        Validate budget constraints for a trailer plan.
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []
        evidence: list[str] = [f"budget:{run_budget}", f"cost:{estimated_cost:.4f}"]

        cost_profile = plan.get("cost_profile", "full")

        # 1. Fallback profile warning
        if cost_profile == "lite":
            warnings.append(
                ValidationWarning(
                    code="PLANNED_WITH_FALLBACK_PROFILE",
                    rule_id="BUDGET-002",
                    segment_id="__plan__",
                    message="Trailer was planned using fallback 'lite' cost profile",
                    evidence=["profile:lite"],
                )
            )

        # 2. Budget limits
        if estimated_cost > run_budget:
            evidence.append(f"overrun:{estimated_cost - run_budget:.4f}")
            # If even the lite cost profile exceeds run_budget, it is unresolvable
            if run_budget < lite_cost:
                errors.append(
                    ValidationError(
                        code="BUDGET_UNRESOLVED",
                        rule_id="BUDGET-001",
                        segment_id="__plan__",
                        message=(
                            f"Run budget {run_budget} is insufficient even for lite fallback profile ({lite_cost}). "
                            "Requires human approval / budget increase."
                        ),
                        evidence=[f"budget:{run_budget}", f"lite_cost:{lite_cost}"],
                        repairable=False,  # Non-repairable!
                    )
                )
            else:
                errors.append(
                    ValidationError(
                        code="BUDGET_EXCEEDED",
                        rule_id="BUDGET-001",
                        segment_id="__plan__",
                        message=f"Estimated cost {estimated_cost:.4f} exceeds run budget {run_budget}",
                        evidence=[f"budget:{run_budget}", f"cost:{estimated_cost:.4f}"],
                        repairable=True,
                    )
                )

        status = ValidatorStatus.FAIL if errors else (ValidatorStatus.WARN if warnings else ValidatorStatus.PASS)

        return ValidatorResult(
            validator=self.name,
            status=status,
            errors=errors,
            warnings=warnings,
            evidence=evidence,
        )

    def validate(
        self,
        plan: dict[str, Any],
        estimated_cost: float,
        run_budget: float,
        lite_cost: float = 0.13,
    ) -> dict[str, ValidatorResult]:
        """
        Return {"__plan__": ValidatorResult}.
        """
        return {"__plan__": self.validate_plan(plan, estimated_cost, run_budget, lite_cost)}
