"""``research-pipeline`` CLI: ingest, run-cycle, replay (plan.md Target Platform).

A stateless batch entry point — "continuous" ingestion is an external scheduler
invoking ``ingest`` on a cadence (research.md §6). Missing/invalid configuration
surfaces as a visible error, never a hidden default (spec Edge Case).
"""

from __future__ import annotations

import argparse
import sys

from energy_research.common.logging import configure as configure_logging
from energy_research.common.logging import get_logger
from energy_research.config.settings import load_config

log = get_logger("cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="research-pipeline",
        description="Automated trading-idea research pipeline for Brazilian energy markets",
    )
    parser.add_argument(
        "--config", default="config/default.yaml", help="path to the pipeline configuration YAML"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "ingest", help="fetch, clean, quality-check, and persist all configured providers' data"
    )
    sub.add_parser(
        "run-cycle", help="run one end-to-end research cycle (trigger → report, no manual steps)"
    )
    replay_parser = sub.add_parser(
        "replay", help="re-execute a completed cycle from its recorded config snapshot + seed"
    )
    replay_parser.add_argument("--cycle-id", required=True)

    args = parser.parse_args(argv)
    configure_logging()
    config = load_config(args.config)

    if args.command == "ingest":
        from energy_research.orchestration.ingest import ingest_all

        summary = ingest_all(config)
        print(
            f"ingested {summary['series']} series and "
            f"{summary['context_docs']} context documents "
            f"({summary['quality_issues']} data-quality issues recorded)"
        )
        return 0

    if args.command == "run-cycle":
        from energy_research.orchestration.cycle import run_cycle

        result = run_cycle(config)
        print(
            f"cycle {result.cycle_id} complete (seed {result.seed}); "
            f"{len(result.promoted_thesis_ids)} thesis(es) promoted"
        )
        print(f"report: {result.report_path}")
        return 0

    if args.command == "replay":
        from energy_research.orchestration.cycle import replay_cycle

        result = replay_cycle(config, args.cycle_id)
        print(
            f"replayed as cycle {result.cycle_id} (seed {result.seed}); "
            f"{len(result.promoted_thesis_ids)} thesis(es) promoted"
        )
        print(f"report: {result.report_path}")
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
