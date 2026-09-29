"""
main.py — Minimal CLI entry point.
Authority: IMPLEMENTATION_PLAN.md §7 (CLI), SUMMARY.md §25.

Usage (replay mode, default):
  python main.py --episode data/episode.json

Full options:
  python main.py \\
    --episode data/episode.json \\
    --mode replay|live          # default: replay
    --scenario traps|clean      # default: traps
    --out sample_run/           # default: sample_run
    --strict-replay             # abort on replay fixture miss

Change-impact resume:
  python main.py \\
    --episode data/episode.json \\
    --resume sample_run/run_state.json \\
    --change-event data/change_events/music_03_expired.json

Phase 0: CLI parses args and prints them; graph invocation is a stub.
Business logic wired in Phases 3–8.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


def load_config(config_path: Path = Path("config.yaml")) -> dict:
    """Load config.yaml; return an empty dict if not found."""
    if config_path.exists():
        with config_path.open() as f:
            return yaml.safe_load(f) or {}
    return {}


def build_run_config(args: argparse.Namespace, config: dict) -> dict:
    """Merge CLI args with config.yaml to produce run_config."""
    return {
        "mode": args.mode or config.get("mode", "replay"),
        "scenario": args.scenario or config.get("scenario", "traps"),
        "strict_replay": args.strict_replay or config.get("strict_replay", False),
        "output_dir": str(args.out or config.get("output_dir", "sample_run")),
        "evaluation_date": config.get("evaluation_date", "2026-09-29"),
        "max_repair_iterations": config.get("max_repair_iterations", 2),
        "run_budget": config.get("run_budget", 2.00),
        "model": config.get("model", {}),
        "campaign": config.get("campaign", {"territory": "IN", "start": "2026-10-05", "end": "2026-11-05"}),
        "resume_path": str(args.resume) if args.resume else None,
        "change_event_path": str(args.change_event) if args.change_event else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous Regional Trailer Director — prototype CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fresh replay run (default)
  python main.py --episode data/episode.json

  # Change-impact resume
  python main.py --episode data/episode.json \\
    --resume sample_run/run_state.json \\
    --change-event data/change_events/music_03_expired.json
""",
    )
    parser.add_argument(
        "--episode",
        type=Path,
        default=Path("data/episode.json"),
        help="Path to episode.json manifest (default: data/episode.json)",
    )
    parser.add_argument(
        "--mode",
        choices=["replay", "live"],
        default=None,
        help="Run mode: replay (no API key) or live (GEMINI_API_KEY required)",
    )
    parser.add_argument(
        "--scenario",
        choices=["traps", "clean"],
        default=None,
        help="Replay scenario: traps (demonstrates repair) or clean (baseline)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: sample_run/)",
    )
    parser.add_argument(
        "--strict-replay",
        action="store_true",
        default=False,
        help="Abort on replay fixture miss instead of logging and continuing",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
        help="Path to prior run_state.json for change-impact resume",
    )
    parser.add_argument(
        "--change-event",
        dest="change_event",
        type=Path,
        default=None,
        help="Path to change_event.json (requires --resume)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config()
    run_config = build_run_config(args, config)

    if run_config["change_event_path"] and not run_config["resume_path"]:
        logger.error("--change-event requires --resume <run_state.json>")
        return 2

    initial_state: dict[str, Any] = {}
    if run_config["resume_path"]:
        resume_file = Path(run_config["resume_path"])
        if not resume_file.exists():
            logger.error("Resume file not found: %s", resume_file)
            return 1
        with open(resume_file, "r", encoding="utf-8") as f:
            initial_state = json.load(f)

        cfg = initial_state.get("run_config", {})
        # Preserve prior scenario if not explicitly overridden on CLI
        if args.scenario is None and "scenario" in cfg:
            run_config["scenario"] = cfg["scenario"]

        cfg.update({k: v for k, v in run_config.items() if v is not None})
        initial_state["run_config"] = cfg

        if run_config["change_event_path"]:
            ce_file = Path(run_config["change_event_path"])
            if not ce_file.exists():
                logger.error("Change event file not found: %s", ce_file)
                return 1
            with open(ce_file, "r", encoding="utf-8") as f:
                initial_state["change_event"] = json.load(f)
    else:
        initial_state = {
            "run_config": run_config,
            "decision_log": [],
        }

    logger.info("=== Autonomous Regional Trailer Director (prototype) ===")
    logger.info("Mode:     %s", run_config["mode"])
    logger.info("Scenario: %s", run_config["scenario"])
    logger.info("Output:   %s", run_config["output_dir"])

    from src.graph import graph
    final_state = graph.invoke(initial_state, config={"recursion_limit": 30})
    logger.info("Run complete. Status: %s", final_state.get("status"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
