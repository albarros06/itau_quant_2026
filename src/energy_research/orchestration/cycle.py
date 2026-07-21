"""The bounded research-cycle state machine (FR-022, spec User Stories 1 & 3).

Single pass: freshness gate → split allocation → generation → screening (with
mandatory multiplicity control) → refinement-split backtests → bounded
critique-and-improve loop → one ledger-gated final evaluation per lineage →
complete report. The cycle's resolved ``config_snapshot`` and ``seed`` are
persisted on the ResearchCycle record (FR-029) so ``replay`` can reload them.

Loop bounds (Clarification Q3): a per-lineage refinement-depth cap AND a per-run
cap on lineages/iterations, whichever is hit first. Refinement variants are
screened in waves so multiplicity control applies across each wave's family.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from energy_research.backtesting.service import BacktestingService
from energy_research.common import seed as seed_mod
from energy_research.common.logging import configure as configure_logging
from energy_research.common.logging import get_logger, kv
from energy_research.config.settings import PipelineConfig
from energy_research.critique.service import CritiqueService
from energy_research.datastore.ledger import EvaluationLedger
from energy_research.datastore.repository import Repository
from energy_research.generation.service import GenerationService
from energy_research.reporting.report_builder import build_report
from energy_research.screening.service import ScreeningService

log = get_logger("orchestration.cycle")

_REJECTED_STATUSES = ("screened_rejected", "rejected_underperform", "invalid_schema")


@dataclass
class CycleResult:
    cycle_id: str
    seed: int
    report_path: Path
    promoted_thesis_ids: list[str] = field(default_factory=list)
    statuses: dict = field(default_factory=dict)  # thesis_id -> final status


def _create_split_allocations(repo: Repository, cycle_id: str, config: PipelineConfig) -> None:
    start_s, end_s = repo.common_date_bounds(config.universe_keys)
    start, end = pd.Timestamp(start_s), pd.Timestamp(end_s)
    span_days = (end - start).days
    disc_end = start + pd.Timedelta(days=int(span_days * config.splits.discovery_fraction))
    ref_end = disc_end + pd.Timedelta(days=int(span_days * config.splits.refinement_fraction))
    scope = ",".join(config.universe_keys)
    bounds = [
        ("discovery", start, disc_end),
        ("refinement", disc_end + pd.Timedelta(days=1), ref_end),
        ("final_evaluation", ref_end + pd.Timedelta(days=1), end),
    ]
    for split_type, s, e in bounds:
        repo.create_split_allocation(
            cycle_id, split_type, s.date().isoformat(), e.date().isoformat(), scope
        )


def run_cycle(config: PipelineConfig, seed: int | None = None) -> CycleResult:
    configure_logging()
    if seed is None:
        seed = config.reproducibility.seed
    if seed is None:
        seed = secrets.randbits(31)  # auto-generated, recorded on the cycle (FR-029)
    seed_mod.set_seed(seed)

    repo = Repository(
        config.datastore.db_path,
        config.datastore.lake_dir,
        config.data_quality.max_cross_series_gap_days,
    )
    ledger = EvaluationLedger(config.datastore.db_path)
    try:
        # Refuse to start on stale/missing data, before any state is created (FR-006).
        repo.assert_fresh(config.universe_keys, config.data_quality.freshness_tolerance_days)

        caps = config.refinement
        cycle_id = repo.create_cycle(
            config.snapshot(),
            seed,
            max_refinement_depth=caps.max_refinement_depth_per_lineage,
            max_lineages=caps.max_lineages_per_run,
        )
        log.info("cycle started %s", kv(cycle_id=cycle_id, seed=seed))
        try:
            result = _run_cycle_body(repo, ledger, config, cycle_id, seed)
            repo.finish_cycle(cycle_id, "completed")
            return result
        except Exception:
            repo.finish_cycle(cycle_id, "failed")
            raise
    finally:
        repo.close()


def _instrument_trends(repo: Repository, cycle_id: str, config: PipelineConfig) -> dict[str, float]:
    data = repo.read_discovery_data(cycle_id, config.universe_keys)
    rets = data.prices.pct_change()
    return {key: float(rets[key].dropna().mean()) for key in config.universe_keys}


def _run_cycle_body(
    repo: Repository, ledger: EvaluationLedger, config: PipelineConfig, cycle_id: str, seed: int
) -> CycleResult:
    _create_split_allocations(repo, cycle_id, config)

    generation = GenerationService(repo, ledger, config)
    screening = ScreeningService(repo, config)
    backtesting = BacktestingService(repo, ledger, config)
    critique = CritiqueService(repo, config)
    caps = config.refinement

    # --- initial proposals: one lineage each, bounded by the per-run cap ---------
    n_initial = min(config.generation.max_theses_per_cycle, caps.max_lineages_per_run)
    gen_outcome = generation.generate_initial(cycle_id, n_initial)
    iterations_launched = len(gen_outcome.proposed_thesis_ids) + len(gen_outcome.invalid_thesis_ids)
    iteration_budget = caps.max_lineages_per_run * (1 + caps.max_refinement_depth_per_lineage)

    if iterations_launched == 0:
        log.error("generation produced no candidate theses for cycle %s", cycle_id)
        report = build_report(
            repo,
            ledger,
            cycle_id,
            config.datastore.reports_dir,
            empty_reason="generation produced no candidate theses this cycle "
            "(no market/qualitative context yielded a proposal)",
        )
        return CycleResult(cycle_id=cycle_id, seed=seed, report_path=report["path"])

    # --- screening + refinement backtests for the initial wave -------------------
    screened = screening.screen_cycle(cycle_id)
    for thesis_id in screened.passed_thesis_ids:
        backtesting.run_refinement(thesis_id)

    # --- bounded critique-and-improve loop (FR-020..FR-022) ----------------------
    trends = _instrument_trends(repo, cycle_id, config)
    for _wave in range(caps.max_refinement_depth_per_lineage):
        candidates = []
        for thesis in repo.theses_for_cycle(cycle_id):
            lineage = repo.get_lineage(thesis["lineage_id"])
            latest = repo.theses_for_lineage(thesis["lineage_id"])[-1]
            if latest["thesis_id"] != thesis["thesis_id"]:
                continue  # only a lineage's newest variant is a refinement candidate
            if latest["status"] not in _REJECTED_STATUSES:
                continue
            if lineage["refinement_depth"] >= caps.max_refinement_depth_per_lineage:
                continue
            candidates.append(latest)
        if not candidates or iterations_launched >= iteration_budget:
            break

        new_thesis_ids: list[str] = []
        for thesis in candidates:
            if iterations_launched >= iteration_budget:
                log.warning(
                    "per-run iteration cap reached %s",
                    kv(cycle_id=cycle_id, budget=iteration_budget),
                )
                break
            instrument = (thesis["hypothesis"].get("instruments") or [None])[0]
            crit = critique.critique_thesis(
                thesis["thesis_id"], instrument_trend=trends.get(instrument, 0.0)
            )
            if crit is None:
                continue
            new_id, valid = generation.generate_refinement(
                cycle_id,
                thesis["thesis_id"],
                {"weaknesses": crit.weaknesses, "suggested_direction": crit.suggested_direction},
            )
            repo.bump_lineage_depth(thesis["lineage_id"])
            iterations_launched += 1
            if valid:
                new_thesis_ids.append(new_id)

        if new_thesis_ids:
            # Each refinement wave is screened as its own family so multiplicity
            # control applies across it (FR-030).
            wave = screening.screen_cycle(cycle_id, thesis_ids=new_thesis_ids)
            for thesis_id in wave.passed_thesis_ids:
                backtesting.run_refinement(thesis_id)

    # --- one final evaluation per lineage, on its best surviving variant ---------
    result = CycleResult(cycle_id=cycle_id, seed=seed, report_path=Path())
    seen_lineages: set[str] = set()
    for thesis in repo.theses_for_cycle(cycle_id):
        lineage_id = thesis["lineage_id"]
        if lineage_id in seen_lineages:
            continue
        seen_lineages.add(lineage_id)
        variants = repo.theses_for_lineage(lineage_id)
        survivors = [v for v in variants if v["status"] == "backtested"]
        if not survivors:
            continue
        best = max(
            survivors,
            key=lambda v: repo.backtest_results_for(v["thesis_id"], split_type="refinement")[-1][
                "net_return"
            ],
        )
        repo.update_thesis_status(
            best["thesis_id"],
            "final_evaluation_pending",
            "selected as the lineage's best refinement-split variant",
        )
        final_status = backtesting.run_final_evaluation(best["thesis_id"])
        if final_status == "promoted":
            result.promoted_thesis_ids.append(best["thesis_id"])

    report = build_report(repo, ledger, cycle_id, config.datastore.reports_dir)
    result.report_path = report["path"]
    result.statuses = {t["thesis_id"]: t["status"] for t in repo.theses_for_cycle(cycle_id)}
    log.info(
        "cycle complete %s",
        kv(
            cycle_id=cycle_id,
            theses=len(result.statuses),
            promoted=len(result.promoted_thesis_ids),
            report=str(result.report_path),
        ),
    )
    return result


def replay_cycle(config: PipelineConfig, cycle_id: str) -> CycleResult:
    """Re-execute a completed cycle from its recorded config snapshot + seed
    (FR-028/FR-029, SC-009). Produces a new ResearchCycle expected to reproduce
    the original's shortlist and verdicts."""
    from energy_research.config.settings import config_from_snapshot

    repo = Repository(
        config.datastore.db_path,
        config.datastore.lake_dir,
        config.data_quality.max_cross_series_gap_days,
    )
    try:
        recorded = repo.get_cycle(cycle_id)
    finally:
        repo.close()
    replay_config = config_from_snapshot(recorded["config_snapshot"])
    return run_cycle(replay_config, seed=recorded["seed"])
