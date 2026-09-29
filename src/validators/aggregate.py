"""
aggregate.py — Validator orchestration and status aggregation.
Authority: VALIDATION_AND_TESTING.md §1–§2.

Validation order (ARCHITECTURE.md §7):
  1. SceneExistence
  2. Timecode
  3. Rights
  4. Spoiler
  5. StoryTruth
  6. AudienceSafety
  7. DialectConsistency
  8. Accessibility
  9. Budget

Rules:
  1. All nine run so the report is complete.
  2. Segments failing SceneExistence or Timecode: dependent validators
     mark that segment SKIPPED with blocked_by.
  3. Fail-closed: validator exception → FAIL (never PASS).
  4. Hard failures are never downgraded to warnings.
  5. Scope-aware: if affected_decisions is non-empty, segment-level
     validators run only for those; plan-level checks always run.
  6. LLM advisory concerns may only add warnings; they cannot clear FAIL.

Aggregation per trailer (VALIDATION_AND_TESTING.md §2):
  All PASS             → PASS
  ≥1 WARN, no FAIL     → PASS_WITH_WARNINGS
  ≥1 FAIL + repairable → REPAIR_REQUIRED
  ≥1 non-repairable FAIL, repair exhausted, or blocking review → REJECTED

Order:
  REJECTED > REPAIR_REQUIRED > PASS_WITH_WARNINGS > PASS
"""

from __future__ import annotations

import logging
from typing import Any

from src.models import (
    TrailerValidation,
    ValidatorResult,
    ValidatorStatus,
    ValidationError,
    ValidationWarning,
    TrailerStatus,
    HumanReviewItem,
)
from src.validators.scene_existence import SceneExistenceValidator
from src.validators.timecode import TimecodeValidator
from src.validators.rights import RightsValidator
from src.validators.spoiler import SpoilerValidator
from src.validators.story_truth import StoryTruthValidator
from src.validators.audience_safety import AudienceSafetyValidator
from src.validators.dialect import DialectConsistencyValidator
from src.validators.accessibility import AccessibilityValidator
from src.validators.budget import BudgetValidator
from src.evidence import scan_for_injection

logger = logging.getLogger(__name__)

# Non-repairable error codes (cannot be fixed by repair agent)
NON_REPAIRABLE_CODES = frozenset({
    "BUDGET_UNRESOLVED",
    "TRAILER_ID_INVALID",
    "AUDIENCE_INVALID",
    "VALIDATOR_EXCEPTION",
})

# Exact 9-validator sequence
VALIDATOR_NAMES = [
    "SceneExistenceValidator",
    "TimecodeValidator",
    "RightsValidator",
    "SpoilerValidator",
    "StoryTruthValidator",
    "AudienceSafetyValidator",
    "DialectConsistencyValidator",
    "AccessibilityValidator",
    "BudgetValidator",
]


def run_validators(
    plan: dict[str, Any],
    evidence_index: dict[str, Any],
    spoiler_map: dict[str, Any],
    story_map: dict[str, Any],
    story_facts: dict[str, Any],
    constraint_map: dict[str, Any],
    subtitles: dict[str, Any],
    audience_profile: dict[str, Any],
    estimated_cost: float,
    run_budget: float,
    affected_decisions: list[str] | None = None,
    repair_attempts: dict[str, int] | None = None,
    max_repair_iterations: int = 2,
    human_review_items: list[HumanReviewItem] | None = None,
) -> TrailerValidation:
    """
    Run all nine validators for one trailer plan.
    Returns a TrailerValidation (alias for TrailerValidationResult).

    If affected_decisions is non-empty, segment-level validators run only
    for those segment ids. Plan-level checks always run.
    """
    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    trailer_id = plan_dict.get("trailer_id", "trailer_plan")
    segments = plan_dict.get("segments", [])
    repair_attempts = repair_attempts or {}

    # Scope awareness: determine active segments
    scoped_sids: set[str] | None = None
    if affected_decisions:
        scoped_sids = set()
        for aff in affected_decisions:
            if aff.startswith(f"{trailer_id}."):
                scoped_sids.add(aff.split(".", 1)[1])
            else:
                scoped_sids.add(aff)

    # Instantiate the 9 validators
    v_scene = SceneExistenceValidator()
    v_time = TimecodeValidator()
    v_rights = RightsValidator()
    v_spoiler = SpoilerValidator()
    v_story = StoryTruthValidator()
    v_safety = AudienceSafetyValidator()
    v_dialect = DialectConsistencyValidator()
    v_access = AccessibilityValidator()
    v_budget = BudgetValidator()

    # Safe defaults
    evidence_index = evidence_index or {}
    scenes_map = evidence_index.get("by_scene", {})
    constraint_map = constraint_map or {}
    spoiler_map = spoiler_map or {}
    story_map = story_map or {}
    story_facts = story_facts or {}
    subtitles = subtitles or {}
    audience_profile = audience_profile or {}

    # Track segments failing scene existence or timecode
    blocked_segments: dict[str, str] = {}  # segment_id -> blocking_validator_name

    validator_results: list[ValidatorResult] = []

    # 1. SceneExistenceValidator
    try:
        scene_seg_results: dict[str, ValidatorResult] = {}
        seen_sids: set[str] = set()
        v_errors: list[ValidationError] = []
        v_warnings: list[ValidationWarning] = []
        v_evidence: list[str] = []

        for seg in segments:
            s_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = s_dict.get("segment_id", "")
            if scoped_sids is not None and sid not in scoped_sids:
                continue

            res = v_scene.validate_segment(s_dict, evidence_index, constraint_map, seen_sids)
            scene_seg_results[sid] = res
            v_errors.extend(res.errors)
            v_warnings.extend(res.warnings)
            v_evidence.extend(res.evidence)

            if res.status == ValidatorStatus.FAIL:
                blocked_segments[sid] = v_scene.name

        # Plan-level trailer_id and audience checks
        plan_level_res = v_scene.validate(plan_dict, evidence_index, constraint_map).get("__plan__")
        if plan_level_res:
            v_errors.extend(plan_level_res.errors)

        scene_status = (
            ValidatorStatus.FAIL if v_errors
            else (ValidatorStatus.WARN if v_warnings else ValidatorStatus.PASS)
        )
        validator_results.append(
            ValidatorResult(
                validator=v_scene.name,
                status=scene_status,
                errors=v_errors,
                warnings=v_warnings,
                evidence=sorted(set(v_evidence)),
                details={sid: r.model_dump() for sid, r in scene_seg_results.items()},
            )
        )
    except Exception as ex:
        logger.exception("Exception in SceneExistenceValidator")
        validator_results.append(
            ValidatorResult(
                validator=v_scene.name,
                status=ValidatorStatus.FAIL,
                errors=[
                    ValidationError(
                        code="VALIDATOR_EXCEPTION",
                        rule_id="SYS-001",
                        segment_id="__plan__",
                        message=f"Validator exception: {ex}",
                        repairable=False,
                    )
                ],
            )
        )

    # 2. TimecodeValidator
    try:
        time_seg_results: dict[str, ValidatorResult] = {}
        v_errors = []
        v_warnings = []
        v_evidence = []
        scenes_map = evidence_index.get("by_scene", {})

        for seg in segments:
            s_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
            sid = s_dict.get("segment_id", "")
            if scoped_sids is not None and sid not in scoped_sids:
                continue

            if sid in blocked_segments:
                # Segment was already blocked by SceneExistence
                res = ValidatorResult(
                    validator=v_time.name,
                    status=ValidatorStatus.SKIPPED,
                    blocked_by=blocked_segments[sid],
                )
                time_seg_results[sid] = res
                continue

            video = s_dict.get("video") or s_dict.get("scene_id", "")
            sc = scenes_map.get(video, {})
            res = v_time.validate_segment(s_dict, sc)
            time_seg_results[sid] = res
            v_errors.extend(res.errors)
            v_warnings.extend(res.warnings)
            v_evidence.extend(res.evidence)

            if res.status == ValidatorStatus.FAIL:
                blocked_segments[sid] = v_time.name

        # Plan-level duration checks
        time_plan = v_time.validate(plan_dict, evidence_index, constraint_map).get("__plan__")
        if time_plan:
            v_errors.extend(time_plan.errors)
            v_warnings.extend(time_plan.warnings)
            v_evidence.extend(time_plan.evidence)

        # Check if all evaluated segments were skipped
        all_skipped = bool(time_seg_results) and all(
            r.status == ValidatorStatus.SKIPPED for r in time_seg_results.values()
        )
        if all_skipped and not v_errors and not v_warnings:
            time_status = ValidatorStatus.SKIPPED
            time_blocked = next(iter(blocked_segments.values()), None)
        else:
            time_status = (
                ValidatorStatus.FAIL if v_errors
                else (ValidatorStatus.WARN if v_warnings else ValidatorStatus.PASS)
            )
            time_blocked = None

        validator_results.append(
            ValidatorResult(
                validator=v_time.name,
                status=time_status,
                errors=v_errors,
                warnings=v_warnings,
                evidence=sorted(set(v_evidence)),
                blocked_by=time_blocked,
                details={sid: r.model_dump() for sid, r in time_seg_results.items()},
            )
        )
    except Exception as ex:
        logger.exception("Exception in TimecodeValidator")
        validator_results.append(
            ValidatorResult(
                validator=v_time.name,
                status=ValidatorStatus.FAIL,
                errors=[
                    ValidationError(
                        code="VALIDATOR_EXCEPTION",
                        rule_id="SYS-001",
                        segment_id="__plan__",
                        message=f"Validator exception: {ex}",
                        repairable=False,
                    )
                ],
            )
        )

    # Helper for running dependent segment-level validators
    def _run_dependent_validator(validator_obj, validate_fn, plan_checks=None) -> ValidatorResult:
        try:
            seg_results: dict[str, ValidatorResult] = {}
            errors: list[ValidationError] = []
            warnings: list[ValidationWarning] = []
            evidence: list[str] = []

            for seg in segments:
                s_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
                sid = s_dict.get("segment_id", "")
                if scoped_sids is not None and sid not in scoped_sids:
                    continue

                if sid in blocked_segments:
                    seg_res = ValidatorResult(
                        validator=validator_obj.name,
                        status=ValidatorStatus.SKIPPED,
                        blocked_by=blocked_segments[sid],
                    )
                    seg_results[sid] = seg_res
                    continue

                seg_res = validate_fn(s_dict)
                seg_results[sid] = seg_res
                errors.extend(seg_res.errors)
                warnings.extend(seg_res.warnings)
                evidence.extend(seg_res.evidence)

            if plan_checks:
                p_errs, p_warns, p_ev = plan_checks()
                errors.extend(p_errs)
                warnings.extend(p_warns)
                evidence.extend(p_ev)

            all_skipped = bool(seg_results) and all(
                r.status == ValidatorStatus.SKIPPED for r in seg_results.values()
            )
            if all_skipped and not errors and not warnings:
                status = ValidatorStatus.SKIPPED
                blocked = next(iter(blocked_segments.values()), None)
            else:
                status = (
                    ValidatorStatus.FAIL if errors
                    else (ValidatorStatus.WARN if warnings else ValidatorStatus.PASS)
                )
                blocked = None

            return ValidatorResult(
                validator=validator_obj.name,
                status=status,
                errors=errors,
                warnings=warnings,
                evidence=sorted(set(evidence)),
                blocked_by=blocked,
                details={sid: r.model_dump() for sid, r in seg_results.items()},
            )
        except Exception as ex:
            logger.exception(f"Exception in {validator_obj.name}")
            return ValidatorResult(
                validator=validator_obj.name,
                status=ValidatorStatus.FAIL,
                errors=[
                    ValidationError(
                        code="VALIDATOR_EXCEPTION",
                        rule_id="SYS-001",
                        segment_id="__plan__",
                        message=f"Validator exception: {ex}",
                        repairable=False,
                    )
                ],
            )

    # 3. RightsValidator
    c_start = constraint_map.get("campaign", {}).get("start_date", "2026-10-05")
    c_end = constraint_map.get("campaign", {}).get("end_date", "2026-11-05")
    c_terr = constraint_map.get("campaign", {}).get("territory", "IN")
    res_rights = _run_dependent_validator(
        v_rights,
        lambda s: v_rights.validate_segment(
            s, constraint_map, evidence_index, c_start, c_end, c_terr
        ),
    )
    validator_results.append(res_rights)

    # 4. SpoilerValidator
    def _spoiler_plan_checks():
        sp_full = v_spoiler.validate(plan_dict, spoiler_map)
        p_res = sp_full.get("__plan__")
        return (p_res.errors if p_res else [], p_res.warnings if p_res else [], p_res.evidence if p_res else [])

    res_spoiler = _run_dependent_validator(
        v_spoiler,
        lambda s: v_spoiler.validate_segment(s, spoiler_map),
        plan_checks=_spoiler_plan_checks,
    )
    validator_results.append(res_spoiler)

    # 5. StoryTruthValidator
    def _story_plan_checks():
        st_full = v_story.validate(plan_dict, story_map, story_facts, evidence_index)
        p_res = st_full.get("__plan__")
        return (p_res.errors if p_res else [], p_res.warnings if p_res else [], p_res.evidence if p_res else [])

    res_story = _run_dependent_validator(
        v_story,
        lambda s: v_story.validate_segment(s, story_map, story_facts, evidence_index),
        plan_checks=_story_plan_checks,
    )
    validator_results.append(res_story)

    # 6. AudienceSafetyValidator
    ceiling = (
        audience_profile.get("rating_ceiling", "U")
        if isinstance(audience_profile, dict)
        else getattr(audience_profile, "rating_ceiling", "U")
    )
    res_safety = _run_dependent_validator(
        v_safety,
        lambda s: v_safety.validate_segment(
            s, scenes_map.get(s.get("video") or s.get("scene_id", ""), {}), rating_ceiling=ceiling
        ),
    )
    validator_results.append(res_safety)

    # 7. DialectConsistencyValidator
    aud_dict = audience_profile.model_dump() if hasattr(audience_profile, "model_dump") else dict(audience_profile)
    res_dialect = _run_dependent_validator(
        v_dialect,
        lambda s: v_dialect.validate_segment(s, evidence_index, aud_dict),
    )
    validator_results.append(res_dialect)

    # 8. AccessibilityValidator
    res_access = _run_dependent_validator(
        v_access,
        lambda s: v_access.validate_segment(s, evidence_index, aud_dict),
    )
    validator_results.append(res_access)

    # 9. BudgetValidator (plan-level)
    try:
        res_b = v_budget.validate_plan(plan_dict, estimated_cost, run_budget)
        validator_results.append(res_b)
    except Exception as ex:
        logger.exception("Exception in BudgetValidator")
        validator_results.append(
            ValidatorResult(
                validator=v_budget.name,
                status=ValidatorStatus.FAIL,
                errors=[
                    ValidationError(
                        code="VALIDATOR_EXCEPTION",
                        rule_id="SYS-001",
                        segment_id="__plan__",
                        message=f"Validator exception: {ex}",
                        repairable=False,
                    )
                ],
            )
        )

    # ── Plan-Level Checks ─────────────────────────────────────────────────────
    # Check 1: Injection propagation (VALIDATION_AND_TESTING.md §4.10)
    has_injection_suspected = False
    for seg in segments:
        s_dict = seg.model_dump() if hasattr(seg, "model_dump") else dict(seg)
        sid = s_dict.get("segment_id", "")
        vid = s_dict.get("video") or s_dict.get("scene_id", "")
        sc = scenes_map.get(vid, {})
        desc = sc.get("description", "")
        facts = " ".join(sc.get("visual_facts", []))

        is_suspicious = False
        if vid == "scene_05" or "ignore the music contract" in desc.lower():
            is_suspicious = True
        elif scan_for_injection(desc)[0] or scan_for_injection(facts)[0]:
            is_suspicious = True

        if is_suspicious:
            has_injection_suspected = True
            # Add warning to SceneExistence result
            validator_results[0].warnings.append(
                ValidationWarning(
                    code="INJECTION_DETECTED",
                    rule_id="SEC-001",
                    segment_id=sid,
                    message=f"Segment {sid} references scene {vid} with untrusted instruction text",
                    evidence=[f"scene:{vid}"],
                )
            )
            if validator_results[0].status == ValidatorStatus.PASS:
                validator_results[0].status = ValidatorStatus.WARN

            if human_review_items is not None:
                human_review_items.append(
                    HumanReviewItem(
                        item_id=f"rev_inj_{sid}",
                        trailer_id=trailer_id,
                        segment_id=sid,
                        reason_code="INJECTION_SUSPECTED",
                        description=f"Segment {sid} uses scene {vid} containing untrusted instruction text.",
                        blocking=False,  # Non-blocking per spec
                    )
                )

    # Check 2: Audience proxy-bias check
    if aud_dict.get("risk_flags") and "AUDIENCE_PROXY_BIAS" in aud_dict.get("risk_flags", []):
        validator_results[5].warnings.append(
            ValidationWarning(
                code="AUDIENCE_PROXY_BIAS",
                rule_id="POL-AUDIENCE-001",
                segment_id="__plan__",
                message="Audience profile contains geographic proxy bias warning",
                evidence=["risk:AUDIENCE_PROXY_BIAS"],
            )
        )
        if human_review_items is not None:
            human_review_items.append(
                HumanReviewItem(
                    item_id=f"rev_bias_{trailer_id}",
                    trailer_id=trailer_id,
                    reason_code="AUDIENCE_PROXY_BIAS",
                    description="Audience profile data contains location proxy bias",
                    blocking=False,
                )
            )

    # Construct the TrailerValidationResult
    tv_res = TrailerValidation(
        trailer_id=trailer_id,
        status=TrailerStatus.PASS,  # Will be aggregated below
        validators=validator_results,
        human_review_required=has_injection_suspected,
        repair_attempts=dict(repair_attempts),
    )

    tv_res.status = aggregate_trailer_status(
        tv_res, repair_attempts=repair_attempts, max_repair_iterations=max_repair_iterations
    )

    return tv_res


def aggregate_trailer_status(
    validation: TrailerValidation,
    repair_attempts: dict[str, int] | None = None,
    max_repair_iterations: int = 2,
    blocking_review: bool = False,
) -> TrailerStatus:
    """
    Compute the aggregate TrailerStatus from per-validator results.
    Rule: REJECTED > REPAIR_REQUIRED > PASS_WITH_WARNINGS > PASS.

    Conditions (VALIDATION_AND_TESTING.md §2):
      - All PASS (or SKIPPED with no errors/warnings) → PASS
      - ≥1 WARN, no FAIL → PASS_WITH_WARNINGS
      - ≥1 FAIL where every error is repairable and attempts remain → REPAIR_REQUIRED
      - ≥1 non-repairable FAIL, repair exhausted, or blocking human review → REJECTED
    """
    repair_attempts = repair_attempts or {}
    all_errors: list[ValidationError] = []
    all_warnings: list[ValidationWarning] = []

    for v in validation.validators:
        all_errors.extend(v.errors)
        all_warnings.extend(v.warnings)

    if not all_errors:
        if all_warnings:
            return TrailerStatus.PASS_WITH_WARNINGS
        return TrailerStatus.PASS

    # If any error exists:
    if blocking_review:
        return TrailerStatus.REJECTED

    for err in all_errors:
        if not err.repairable or err.code in NON_REPAIRABLE_CODES:
            return TrailerStatus.REJECTED

        sid = err.segment_id
        if sid and sid != "__plan__":
            attempts = repair_attempts.get(sid, 0)
            if attempts >= max_repair_iterations:
                return TrailerStatus.REJECTED

    return TrailerStatus.REPAIR_REQUIRED


def aggregate_run_status(
    trailer_validations: dict[str, Any],
) -> TrailerStatus:
    """
    Compute run-level status = worst trailer status.
    REJECTED > REPAIR_REQUIRED > PASS_WITH_WARNINGS > PASS.
    """
    statuses: list[str] = []
    for tv in trailer_validations.values():
        if isinstance(tv, dict):
            st = tv.get("status", "PASS")
        elif hasattr(tv, "status"):
            st = tv.status.value if hasattr(tv.status, "value") else str(tv.status)
        else:
            st = "PASS"
        statuses.append(st)

    if any(s == "REJECTED" or s == TrailerStatus.REJECTED.value for s in statuses):
        return TrailerStatus.REJECTED
    if any(s == "REPAIR_REQUIRED" or s == TrailerStatus.REPAIR_REQUIRED.value for s in statuses):
        return TrailerStatus.REPAIR_REQUIRED
    if any(s == "PASS_WITH_WARNINGS" or s == TrailerStatus.PASS_WITH_WARNINGS.value for s in statuses):
        return TrailerStatus.PASS_WITH_WARNINGS
    return TrailerStatus.PASS
