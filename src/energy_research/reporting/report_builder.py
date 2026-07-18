"""ResearchReport builder (contracts/report-contract.md, FR-023–FR-026).

Builds one entry for EVERY thesis of a cycle — all iterations, all lineages,
including invalid-schema drafts and refused final-evaluation attempts — from
persisted datastore records only (this layer never recomputes statistics). Also
renders a self-contained, human-readable Markdown artifact so a reviewer can
answer "why was thesis X rejected/promoted?" without reading code (SC-008).

Synthetic provenance is surfaced on every entry whose input series were synthetic
(Principle IV) — there is no path by which a synthetic result reads as real.
"""

from __future__ import annotations

from pathlib import Path

from energy_research.common.logging import get_logger
from energy_research.datastore.ledger import EvaluationLedger
from energy_research.datastore.repository import Repository

log = get_logger("reporting.report_builder")


def _performance(bt: dict) -> dict:
    """Net-of-cost performance block; never gross-only (Principle IV)."""
    return {
        "split_type": bt["split_type"],
        "gross_return": bt["gross_return"],
        "transaction_costs": bt["transaction_costs"],
        "slippage": bt["slippage"],
        "financing_carry": bt["financing_carry"],
        "net_return": bt["net_return"],
        "other_metrics": bt["other_metrics"],
    }


def build_report(
    repo: Repository,
    ledger: EvaluationLedger,
    cycle_id: str,
    reports_dir: Path,
    empty_reason: str | None = None,
) -> dict:
    """Assemble, persist, and render the cycle's report. Returns
    ``{"report_id", "path", "entries"}``."""
    theses = repo.theses_for_cycle(cycle_id)
    provenance_by_key = {row["instrument_key"]: row["provenance"] for row in repo.series_rows()}

    entries: list[dict] = []
    for thesis in theses:
        instruments = thesis["hypothesis"].get("instruments", [])
        synthetic_inputs = sorted(i for i in instruments if provenance_by_key.get(i) == "synthetic")
        screening = repo.screening_result_for(thesis["thesis_id"])
        refinement_results = repo.backtest_results_for(thesis["thesis_id"], split_type="refinement")
        final_results = repo.backtest_results_for(
            thesis["thesis_id"], split_type="final_evaluation"
        )
        try:
            ledger_status = ledger.status(thesis["lineage_id"])
            ledger_block = {
                "spent": ledger_status.spent,
                "spent_by_thesis_id": ledger_status.spent_by_thesis_id,
                "spent_at": ledger_status.spent_at,
            }
        except LookupError:
            ledger_block = None
        entries.append(
            {
                "thesis_id": thesis["thesis_id"],
                "lineage_id": thesis["lineage_id"],
                "parent_thesis_id": thesis["parent_thesis_id"],
                "iteration_index": thesis["iteration_index"],
                "rationale": thesis["rationale"],
                "hypothesis": thesis["hypothesis"],
                "synthetic_inputs": synthetic_inputs,
                "screening": None
                if screening is None
                else {
                    "method": screening["method"],
                    "statistic_value": screening["statistic_value"],
                    "p_value": screening["p_value"],
                    "multiplicity_method": screening["multiplicity_method"],
                    "adjusted_threshold": screening["adjusted_threshold"],
                    "verdict": screening["verdict"],
                    "reason": screening["reason"],
                },
                "refinement_backtests": [_performance(b) for b in refinement_results],
                "final_evaluation": [_performance(b) for b in final_results],
                "evaluation_ledger": ledger_block,
                "final_status": thesis["status"],
                "final_status_reason": thesis["status_reason"],
            }
        )

    report_payload_extra = {
        "refused_final_evaluation_attempts": repo.ledger_refusal_rows(cycle_id),
    }
    if not entries and empty_reason:
        report_payload_extra["empty_reason"] = empty_reason

    report_id = repo.insert_report(cycle_id, entries + [{"__meta__": report_payload_extra}])
    path = _render_markdown(repo, cycle_id, report_id, entries, report_payload_extra, reports_dir)
    log.info("report written: %s (%d thesis entries)", path, len(entries))
    return {"report_id": report_id, "path": path, "entries": entries}


def _render_markdown(
    repo: Repository,
    cycle_id: str,
    report_id: str,
    entries: list[dict],
    meta: dict,
    reports_dir: Path,
) -> Path:
    cycle = repo.get_cycle(cycle_id)
    lines = [
        f"# Research Report — cycle `{cycle_id}`",
        "",
        f"- report id: `{report_id}`",
        f"- cycle started: {cycle['started_at']}",
        f"- seed: `{cycle['seed']}` (cycle is replayable via "
        f"`research-pipeline replay --cycle-id {cycle_id}`)",
        f"- theses covered: {len(entries)} (every iteration of every lineage)",
        "",
    ]
    if "empty_reason" in meta:
        lines += [f"**No theses were proposed this cycle.** Reason: {meta['empty_reason']}", ""]
    for e in entries:
        synthetic = (
            (
                " — **SYNTHETIC DATA**: built on synthetic input series "
                f"{e['synthetic_inputs']}, not a real-data result"
            )
            if e["synthetic_inputs"]
            else ""
        )
        lines += [
            f"## Thesis `{e['thesis_id']}` — {e['final_status']}",
            "",
            f"- lineage `{e['lineage_id']}`, iteration {e['iteration_index']}"
            + (f", refined from `{e['parent_thesis_id']}`" if e["parent_thesis_id"] else "")
            + synthetic,
            f"- **Rationale**: {e['rationale']}",
            f"- **Hypothesis**: {e['hypothesis'] or '(failed schema validation)'}",
        ]
        if e["screening"]:
            s = e["screening"]
            lines.append(f"- **Screening** [{s['verdict'].upper()}]: {s['reason']}")
        else:
            lines.append("- **Screening**: not screened — " + e["final_status_reason"])
        for b in e["refinement_backtests"]:
            lines.append(
                f"- **Refinement backtest**: net {b['net_return']:+.4f} = gross "
                f"{b['gross_return']:+.4f} − costs {b['transaction_costs']:.4f} − "
                f"slippage {b['slippage']:.4f} − financing {b['financing_carry']:.4f}"
            )
        for b in e["final_evaluation"]:
            lines.append(
                f"- **Final evaluation** (one-shot, ledger-gated): net "
                f"{b['net_return']:+.4f} = gross {b['gross_return']:+.4f} − costs "
                f"{b['transaction_costs']:.4f} − slippage {b['slippage']:.4f} − "
                f"financing {b['financing_carry']:.4f}"
            )
        if e["evaluation_ledger"]:
            led = e["evaluation_ledger"]
            spent = (
                f"spent by `{led['spent_by_thesis_id']}` at {led['spent_at']}"
                if led["spent"]
                else "not spent"
            )
            lines.append(f"- **Evaluation ledger**: final-evaluation entitlement {spent}")
        lines += [f"- **Final status**: {e['final_status']} — {e['final_status_reason']}", ""]

    refusals = meta.get("refused_final_evaluation_attempts", [])
    if refusals:
        lines += ["## Refused final-evaluation attempts", ""]
        for r in refusals:
            lines.append(f"- {r['attempted_at']}: {r['detail']}")
        lines.append("")

    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{cycle_id}.md"
    path.write_text("\n".join(lines))
    return path
