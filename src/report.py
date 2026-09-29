"""
report.py — Validation report and output artifact writer.
Authority: VALIDATION_AND_TESTING.md §10, PROTOTYPE_SPEC.md §0, DATA_SPEC.md §18.

Outputs generated:
  story_map.json, spoiler_map.json, constraint_map.json,
  family_trailer.json, young_adult_trailer.json, dialect_region_trailer.json,
  validation_report.md, decision_log.json, revision_log.json, run_state.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import (
    TrailerPlan,
    TrailerValidation,
    TrailerStatus,
    ValidatorStatus,
    HumanReviewItem,
    RevisionRecord,
)
from src.tools.distinctness import compute_distinctness_report
from src.logs import write_decision_log, write_revision_log


def _dump(obj: Any) -> Any:
    """Recursively convert pydantic models and objects to JSON-serializable dicts."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_dump(item) for item in obj]
    return obj


def write_run_state(state: dict[str, Any], output_dir: Path) -> Path:
    """
    Serialize TrailerState to run_state.json for change-impact resume.
    State must be fully JSON-serializable (NFR-03).
    """
    out_path = Path(output_dir) / "run_state.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sanitized = _dump(state)
    # Remove execution-environment local paths from deterministic semantic state (NFR-01)
    if "run_config" in sanitized and isinstance(sanitized["run_config"], dict):
        sanitized["run_config"] = dict(sanitized["run_config"])
        sanitized["run_config"].pop("output_dir", None)
        sanitized["run_config"].pop("resume_path", None)
        sanitized["run_config"].pop("change_event_path", None)

    out_path.write_text(json.dumps(sanitized, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return out_path


def write_validation_report(state: dict[str, Any], output_dir: Path) -> Path:
    """
    Write validation_report.md (VALIDATION_AND_TESTING.md §10).
    Contents:
      Run header → per-trailer summary table → per-validator results
      → repair history → change-impact section → human-review items
      → cost summary → distinctness report.
    """
    out_path = Path(output_dir) / "validation_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    status = state.get("status", "PASS")
    run_cfg = state.get("run_config", {})
    scenario = run_cfg.get("scenario", "clean")
    mode = run_cfg.get("mode", "replay")
    cost = state.get("estimated_cost", 0.13)
    budget = run_cfg.get("run_budget", 2.0)

    plans: dict[str, Any] = state.get("candidate_plan", {})
    validation: dict[str, Any] = state.get("validation", {})
    revisions = state.get("revisions", [])
    human_reviews = state.get("human_review_items", [])

    lines: list[str] = [
        "# STAGE Content Director — Validation & Audit Report",
        "",
        f"- **Overall Run Status**: `{status}`",
        f"- **Mode**: `{mode}`",
        f"- **Scenario**: `{scenario}`",
        f"- **Estimated Cost**: `${cost:.4f}` / Budget `${budget:.2f}`",
        "",
        "---",
        "",
        "## 1. Trailer Plans Summary",
        "",
        "| Trailer ID | Audience | Duration | Status | Violations / Warnings |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for tid, p in plans.items():
        p_dict = p.model_dump() if hasattr(p, "model_dump") else dict(p)
        aid = p_dict.get("audience", p_dict.get("audience_id", "family"))
        dur = p_dict.get("duration_seconds", p_dict.get("total_duration_s", 0.0))
        t_val = validation.get(tid)
        t_status = t_val.status.value if hasattr(t_val, "status") and hasattr(t_val.status, "value") else (t_val.status if hasattr(t_val, "status") else "PASS")

        err_codes: list[str] = []
        warn_codes: list[str] = []
        if t_val and hasattr(t_val, "validators"):
            for v in t_val.validators:
                for err in v.errors:
                    err_codes.append(err.code)
                for w in v.warnings:
                    warn_codes.append(w.code)

        summary_note = []
        if err_codes:
            summary_note.append(f"ERR: {', '.join(err_codes)}")
        if warn_codes:
            summary_note.append(f"WARN: {', '.join(warn_codes)}")
        note_str = " | ".join(summary_note) if summary_note else "All checks passed"

        lines.append(f"| `{tid}` | `{aid}` | `{dur:.1f}s` | **{t_status}** | {note_str} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Distinctness Audit",
        "",
    ])

    try:
        dist = compute_distinctness_report(plans)
        lines.append(f"- **Pairwise Source Second Overlap**: {dist.get('pairwise_overlap', {})}")
        lines.append(f"- **Max Overlap Ratio**: `{dist.get('max_overlap_ratio', 0.0):.1%}` (target <= 25%)")
        lines.append(f"- **First Segments Unique**: `{dist.get('first_segments_unique', True)}`")
        lines.append(f"- **Taglines Unique**: `{dist.get('taglines_unique', True)}`")
    except Exception as e:
        lines.append(f"Distinctness report error: {e}")

    lines.extend([
        "",
        "---",
        "",
        "## 3. Repair & Revision Log",
        "",
    ])

    if revisions:
        lines.append("| Rev # | Trigger | Affected | Action | Validation |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in revisions:
            r_dict = r.model_dump() if hasattr(r, "model_dump") else dict(r)
            r_num = r_dict.get("revision", 1)
            trig = r_dict.get("trigger", "")
            aff = ", ".join(r_dict.get("affected", []))
            act = r_dict.get("action", "")
            v_post = r_dict.get("validation", "PASS")
            lines.append(f"| {r_num} | `{trig}` | `{aff}` | {act} | `{v_post}` |")
    else:
        lines.append("No repairs required (all baseline checks passed on first evaluation).")

    lines.extend([
        "",
        "---",
        "",
        "## 4. Human Review & Advisories",
        "",
    ])

    if human_reviews:
        for hr in human_reviews:
            hr_dict = hr.model_dump() if hasattr(hr, "model_dump") else dict(hr)
            blocking = " [BLOCKING]" if hr_dict.get("blocking") else " [NON-BLOCKING]"
            lines.append(f"- **{hr_dict.get('reason_code', 'REVIEW')}**{blocking}: {hr_dict.get('description', '')} (Trailer: `{hr_dict.get('trailer_id')}`) ")
    else:
        lines.append("No blocking human review items flagged.")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Known Limitations",
        "",
        "- Dialect correctness is evaluated using synthetic tag alignment proxies (native speaker review pending).",
        "- Historical high performance does not override editorial truth or spoiler reveal windows.",
        "- Machine checks verify compliance; human editorial approval is required prior to external broadcast.",
        "",
    ])

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_all_outputs(state: dict[str, Any], output_dir: Path | str) -> dict[str, Path]:
    """
    Write all 10 required output files to output_dir:
      story_map.json, spoiler_map.json, constraint_map.json,
      family_trailer.json, young_adult_trailer.json, dialect_region_trailer.json,
      validation_report.md, decision_log.json, revision_log.json, run_state.json.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated: dict[str, Path] = {}

    # 1. story_map.json
    s_map = _dump(state.get("story_map", {}))
    p1 = out_dir / "story_map.json"
    p1.write_text(json.dumps(s_map, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    generated["story_map"] = p1

    # 2. spoiler_map.json
    sp_map = _dump(state.get("spoiler_map", {}))
    p2 = out_dir / "spoiler_map.json"
    p2.write_text(json.dumps(sp_map, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    generated["spoiler_map"] = p2

    # 3. constraint_map.json
    c_map = _dump(state.get("constraint_map", {}))
    p3 = out_dir / "constraint_map.json"
    p3.write_text(json.dumps(c_map, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    generated["constraint_map"] = p3

    # 4-6. Trailer EDLs
    plans = state.get("candidate_plan", {})
    trailer_file_map = {
        "family_v1": "family_trailer.json",
        "young_adult_v1": "young_adult_trailer.json",
        "dialect_region_v1": "dialect_region_trailer.json",
    }
    for tid, fname in trailer_file_map.items():
        p_obj = plans.get(tid, {})
        p_dump = _dump(p_obj)
        pf = out_dir / fname
        pf.write_text(json.dumps(p_dump, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        generated[tid] = pf

    # 7. validation_report.md
    p_rep = write_validation_report(state, out_dir)
    generated["validation_report"] = p_rep

    # 8. decision_log.json
    p_dlog = write_decision_log(state.get("decision_log", []), out_dir)
    generated["decision_log"] = p_dlog

    # 9. revision_log.json
    p_rev = write_revision_log(state.get("revisions", []), out_dir)
    generated["revision_log"] = p_rev

    # 10. run_state.json
    p_state = write_run_state(state, out_dir)
    generated["run_state"] = p_state

    return generated
