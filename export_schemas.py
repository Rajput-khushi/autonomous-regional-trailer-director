"""
export_schemas.py — Export JSON Schemas for all major Pydantic models.
Authority: IMPLEMENTATION_PLAN.md §1 (models.py + JSON Schema export).

Usage:
  python export_schemas.py [--out schemas/]

Writes one .json file per model to the schemas/ directory.
Schemas are deterministic (model_json_schema() output is stable).
No extra dependencies beyond pydantic>=2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


# ── Models to export ────────────────────────────────────────────────────────
# Ordered: input fixtures first, then output artifacts.
from src.models import (
    # Input fixtures
    Episode,
    ScenesFile,
    DialogueFile,
    SubtitlesFile,
    StoryFacts,
    ContractsFile,
    PoliciesFile,
    AudiencesFile,
    HistoricPerformance,
    CostSheet,
    # Planning / output
    TrailerPlan,
    TrailerSegment,
    # Validation
    ValidatorResult,
    TrailerValidationResult,
    # Story / spoiler maps
    StoryMap,
    SpoilerMap,
    # Constraint map
    ConstraintMap,
    # Logs and records
    RevisionRecord,
    RevisionLog,
    DecisionLogEntry,
    DecisionLog,
    HumanReviewItem,
    # Change event
    ChangeEvent,
    # Audience promise
    AudiencePromise,
    # Run state
    RunState,
    # Replay
    ReplayFile,
)

EXPORT_MODELS: list[tuple[str, type]] = [
    # Input fixtures
    ("Episode",               Episode),
    ("ScenesFile",            ScenesFile),
    ("DialogueFile",          DialogueFile),
    ("SubtitlesFile",         SubtitlesFile),
    ("StoryFacts",            StoryFacts),
    ("ContractsFile",         ContractsFile),
    ("PoliciesFile",          PoliciesFile),
    ("AudiencesFile",         AudiencesFile),
    ("HistoricPerformance",   HistoricPerformance),
    ("CostSheet",             CostSheet),
    # Planning / output artifacts
    ("TrailerPlan",           TrailerPlan),
    ("TrailerSegment",        TrailerSegment),
    # Validation
    ("ValidatorResult",       ValidatorResult),
    ("TrailerValidationResult", TrailerValidationResult),
    # Story / spoiler maps
    ("StoryMap",              StoryMap),
    ("SpoilerMap",            SpoilerMap),
    # Constraint map
    ("ConstraintMap",         ConstraintMap),
    # Logs and revision records
    ("RevisionRecord",        RevisionRecord),
    ("RevisionLog",           RevisionLog),
    ("DecisionLogEntry",      DecisionLogEntry),
    ("DecisionLog",           DecisionLog),
    ("HumanReviewItem",       HumanReviewItem),
    # Change event
    ("ChangeEvent",           ChangeEvent),
    # Audience promise
    ("AudiencePromise",       AudiencePromise),
    # Run state (for change-impact resume)
    ("RunState",              RunState),
    # Replay fixture wrapper
    ("ReplayFile",            ReplayFile),
]


def export_schemas(out_dir: Path) -> list[str]:
    """
    Export JSON Schema for each model in EXPORT_MODELS to out_dir.
    Returns list of written file paths.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    for name, model_cls in EXPORT_MODELS:
        schema = model_cls.model_json_schema()
        # Add a title if missing
        schema.setdefault("title", name)
        # Write with 2-space indent for readability
        out_path = out_dir / f"{name}.schema.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
            f.write("\n")
        written.append(str(out_path))
        print(f"  wrote  {out_path.relative_to(Path.cwd()) if out_path.is_relative_to(Path.cwd()) else out_path}")

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export JSON Schemas for all Pydantic models to schemas/"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("schemas"),
        help="Output directory (default: schemas/)",
    )
    args = parser.parse_args()

    print(f"Exporting {len(EXPORT_MODELS)} schemas to {args.out}/")
    written = export_schemas(args.out)
    print(f"\nDone — {len(written)} schemas written.")


if __name__ == "__main__":
    main()
