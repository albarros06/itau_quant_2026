"""``research-ops-agent`` CLI: bootstrap, tick, approve, reject, status, log.

A stateless batch entry point, exactly like 001's ``research-pipeline`` CLI
(research.md §1) — "continuous" operation is an external scheduler invoking
``tick`` on a cadence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from energy_research.common.logging import configure as configure_logging
from energy_research.common.logging import get_logger
from ops_agent.agent import OpsAgent
from ops_agent.config import load_ops_agent_config
from ops_agent.proposals.git_store import GitIdentityError

log = get_logger("ops_agent.cli")


def _resolve_proposal_id(agent: OpsAgent, id_or_prefix: str) -> str:
    """Resolves an abbreviated proposal id (as printed by `bootstrap`/`status`,
    which show only the first 8 characters) to its full id — the same way `git`
    resolves an abbreviated commit SHA."""
    matches = [p["id"] for p in agent.repo.list_proposals() if p["id"].startswith(id_or_prefix)]
    if not matches:
        raise LookupError(f"no proposal matching id {id_or_prefix!r}")
    if len(matches) > 1:
        raise LookupError(f"proposal id {id_or_prefix!r} is ambiguous: matches {matches}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    # A shared parent parser so `--config` works both before AND after the
    # subcommand (`research-ops-agent --config X bootstrap` and
    # `research-ops-agent bootstrap --config X` both work) — argparse subparsers
    # don't inherit a parent-only option positioned after the subcommand token.
    config_parent = argparse.ArgumentParser(add_help=False)
    config_parent.add_argument(
        "--config", default="config/ops_agent.yaml", help="path to the ops-agent configuration YAML"
    )

    parser = argparse.ArgumentParser(
        prog="research-ops-agent",
        description="Autonomous operations agent for the energy-research pipeline",
        parents=[config_parent],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "bootstrap",
        help="discover vendors and open provisioning proposals",
        parents=[config_parent],
    )
    sub.add_parser(
        "tick",
        help="one bounded pass: refresh data and trigger a cycle if due",
        parents=[config_parent],
    )
    approve_parser = sub.add_parser(
        "approve", help="merge a proposal branch (researcher-run only)", parents=[config_parent]
    )
    approve_parser.add_argument("proposal_id")
    reject_parser = sub.add_parser(
        "reject", help="mark a proposal rejected (researcher-run only)", parents=[config_parent]
    )
    reject_parser.add_argument("proposal_id")
    sub.add_parser(
        "status",
        help="summarize schedule state, budgets, and pending proposals",
        parents=[config_parent],
    )
    log_parser = sub.add_parser(
        "log", help="print activity-log entries in chronological order", parents=[config_parent]
    )
    log_parser.add_argument("--since")
    log_parser.add_argument("--until")
    log_parser.add_argument("--action")
    onboard_parser = sub.add_parser(
        "onboard",
        help="draft a config-only onboarding proposal for a new vendor",
        parents=[config_parent],
    )
    onboard_parser.add_argument("--provider-id", required=True)
    onboard_parser.add_argument(
        "--interface-doc", required=True, help="path to vendor interface notes"
    )

    args = parser.parse_args(argv)
    configure_logging()
    config = load_ops_agent_config(args.config)

    with OpsAgent(config) as agent:
        if args.command == "bootstrap":
            proposals = agent.bootstrap()
            print(f"opened {len(proposals)} provisioning proposal(s):")
            for p in proposals:
                print(f"  {p.id[:8]}  {p.branch_name}  ({p.kind})")
            return 0

        if args.command == "tick":
            result = agent.tick()
            if not result["cycle_ran"]:
                print("nothing due; no-op tick")
                return 0
            print(
                f"cycle {result['cycle_id']} complete; "
                f"{len(result['promoted_thesis_ids'])} thesis(es) promoted"
            )
            print(f"report: {result['report_path']}")
            return 0

        if args.command == "approve":
            try:
                full_id = _resolve_proposal_id(agent, args.proposal_id)
                proposal = agent.git_store.approve(full_id)
            except (GitIdentityError, LookupError) as exc:
                parser.error(str(exc))
                return 2
            print(f"{proposal.id[:8]} -> {proposal.status} ({proposal.applied_commit_sha})")
            return 0

        if args.command == "reject":
            try:
                full_id = _resolve_proposal_id(agent, args.proposal_id)
                proposal = agent.git_store.reject(full_id)
            except (GitIdentityError, LookupError) as exc:
                parser.error(str(exc))
                return 2
            print(f"{proposal.id[:8]} -> {proposal.status}")
            return 0

        if args.command == "status":
            pending = agent.repo.list_proposals(status="proposed")
            print(f"pending proposals: {len(pending)}")
            for p in pending:
                print(f"  {p['id'][:8]}  {p['branch_name']}  ({p['kind']})")
            for kind in ("cycle", "market_refresh", "qualitative_poll"):
                state = agent.repo.get_schedule_state(kind)
                last_fired = state["last_fired_at"] if state else "never"
                print(f"{kind}: last fired {last_fired}")
            return 0

        if args.command == "log":
            rows = agent.repo.read_activity(
                since=args.since, until=args.until, action=args.action
            )
            for r in rows:
                print(
                    f"{r['ts']}  {r['action']:20s} {r['target']:30s} "
                    f"{r['outcome']:8s} {r['reason']}"
                )
            return 0

        if args.command == "onboard":
            from ops_agent.proposals.models import OnboardingLimitation

            interface_doc = Path(args.interface_doc).read_text()
            result = agent.onboard(args.provider_id, interface_doc)
            if isinstance(result, OnboardingLimitation):
                print(f"onboarding limitation ({result.unsupported_aspect}): {result.reason}")
                return 1
            print(f"opened onboarding proposal {result.id[:8]}  {result.branch_name}")
            return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
