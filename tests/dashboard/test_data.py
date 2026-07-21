"""Tests for the read-only data layer's mapping from persisted pipeline state.

A small fixture datastore + lake is built through the real pipeline write APIs
(Repository + lake), so these tests exercise the exact records the dashboard reads
in production: statuses bucket correctly, the cost breakdown survives round-trip,
Sharpe is pulled from other_metrics, the synthetic flag is surfaced, and equity
reconstruction refuses (with a reason) when the lake cannot cover a split window.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest
from dashboard.utils.data import DashboardData

from energy_research.common.records import CleanedSeries
from energy_research.datastore.repository import Repository

SPOT = "BR_POWER_SE_SPOT"


def _series_frame(dates: list[str], values: list[float], provenance: str) -> pd.DataFrame:
    ts = datetime(2026, 7, 19, tzinfo=UTC).isoformat()
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "value": values,
            "provenance": provenance,
            "freshness_ts": ts,
        }
    )


@pytest.fixture
def project(tmp_path):
    """Build a project root with config, a datastore, and a lake holding one cycle."""
    root = tmp_path
    (root / "config").mkdir()
    (root / "data").mkdir()

    # Minimal pipeline config pointing at this temp datastore/lake.
    (root / "config" / "providers.yaml").write_text(
        "market_data:\n  - provider_id: sample_provider\n    categories: [spot]\n"
    )
    (root / "config" / "default.yaml").write_text(
        "providers_file: providers.yaml\n"
        "datastore:\n"
        "  db_path: data/research.sqlite\n"
        "  lake_dir: data/lake\n"
        "  reports_dir: data/reports\n"
        "instrument_universe:\n"
        "  - {key: BR_POWER_SE_SPOT, category: spot}\n"
        "data_quality: {freshness_tolerance_days: 7}\n"
        "splits: {discovery_fraction: 0.5, refinement_fraction: 0.3}\n"
        "screening: {}\n"
        "backtesting: {transaction_cost_bps: 5, slippage_bps: 3, financing_annual_rate: 0.11}\n"
        "refinement: {max_refinement_depth_per_lineage: 2, max_lineages_per_run: 5}\n"
    )

    repo = Repository(root / "data/research.sqlite", root / "data/lake")
    # Real spot series spanning 2026-07-10..2026-07-19 (mirrors the real lake window).
    dates = [f"2026-07-{d:02d}" for d in range(10, 20)]
    repo.store_cleaned_series(
        CleanedSeries(
            category="spot",
            instrument_key=SPOT,
            provider_id="new_vendor",
            provenance="real",
            freshness_ts=datetime(2026, 7, 19, tzinfo=UTC),
            frame=_series_frame(dates, [100.0 + i for i in range(10)], "real"),
        )
    )

    cycle_id = repo.create_cycle({"k": "v"}, seed=42, max_refinement_depth=2, max_lineages=5)
    # Split windows INSIDE the real series range → equity reconstruction works.
    repo.create_split_allocation(cycle_id, "refinement", "2026-07-13", "2026-07-16", SPOT)
    repo.create_split_allocation(cycle_id, "final_evaluation", "2026-07-17", "2026-07-19", SPOT)

    entries = [
        {
            "thesis_id": "th_promoted",
            "lineage_id": "lin_1",
            "parent_thesis_id": None,
            "iteration_index": 0,
            "rationale": "spot short drift",
            "hypothesis": {
                "instruments": [SPOT], "direction": "short", "horizon": "refinement_window",
            },
            "synthetic_inputs": [],
            "screening": {"method": "block_bootstrap", "statistic_value": 1.2, "p_value": 0.02,
                          "multiplicity_method": "benjamini_hochberg", "adjusted_threshold": 0.1,
                          "verdict": "pass", "reason": "passed"},
            "refinement_backtests": [
                {"split_type": "refinement", "gross_return": 0.10, "transaction_costs": 0.01,
                 "slippage": 0.005, "financing_carry": 0.004, "net_return": 0.081,
                 "other_metrics": {"sharpe": 1.44, "max_drawdown": 0.13, "n_days": 3,
                                   "date_range": ["2026-07-13", "2026-07-16"],
                                   "any_synthetic_input": False}},
            ],
            "final_evaluation": [
                {"split_type": "final_evaluation", "gross_return": 0.06, "transaction_costs": 0.008,
                 "slippage": 0.004, "financing_carry": 0.003, "net_return": 0.045,
                 "other_metrics": {"sharpe": 1.10, "max_drawdown": 0.09, "n_days": 2,
                                   "date_range": ["2026-07-17", "2026-07-19"],
                                   "any_synthetic_input": False}},
            ],
            "evaluation_ledger": {"spent": True, "spent_by_thesis_id": "th_promoted",
                                  "spent_at": "2026-07-19"},
            "final_status": "promoted",
            "final_status_reason": "net above promotion threshold",
        },
        {
            "thesis_id": "th_synth",
            "lineage_id": "lin_2",
            "parent_thesis_id": None,
            "iteration_index": 0,
            "rationale": "synthetic-input thesis",
            "hypothesis": {
                "instruments": [SPOT], "direction": "long", "horizon": "refinement_window",
            },
            "synthetic_inputs": [SPOT],
            "screening": None,
            "refinement_backtests": [],
            "final_evaluation": [],
            "evaluation_ledger": None,
            "final_status": "screened_rejected",
            "final_status_reason": "failed screening",
        },
        {"__meta__": {"refused_final_evaluation_attempts": []}},
    ]
    repo.insert_report(cycle_id, entries)
    repo.close()

    cfg = {
        "data": {"pipeline_config": "config/default.yaml"},
        "display": {"thesis_page_size": 25, "cycle_list_limit": 20, "overview_spark_points": 60,
                    "equity_min_points": 3, "default_cycle": "latest"},
        "overview": {"spot_key": SPOT},
        "viewport": {"mobile_max_px": 640, "desktop_min_px": 1200},
    }
    return cfg, root, cycle_id


def test_lists_cycle_and_resolves_default(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        cycles = data.list_report_cycles()
        assert [c["cycle_id"] for c in cycles] == [cycle_id]
        assert data.resolve_default_cycle() == cycle_id
    finally:
        data.close()


def test_report_entries_skips_meta_block(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        entries = data.report_entries(cycle_id)
        assert {e["thesis_id"] for e in entries} == {"th_promoted", "th_synth"}
        assert all("__meta__" not in e for e in entries)
    finally:
        data.close()


def test_cost_breakdown_and_sharpe_survive_roundtrip(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        entry = data.thesis_entry(cycle_id, "th_promoted")
        bt = entry["final_evaluation"][-1]
        # net == gross − tx − slippage − financing (Principle IV honesty).
        assert bt["net_return"] == pytest.approx(
            bt["gross_return"] - bt["transaction_costs"] - bt["slippage"] - bt["financing_carry"]
        )
        assert bt["other_metrics"]["sharpe"] == pytest.approx(1.10)
    finally:
        data.close()


def test_cycle_summary_buckets_and_best_metrics(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        s = data.cycle_summary(cycle_id)
        assert s["total"] == 2
        assert s["counts"]["promoted"] == 1
        assert s["counts"]["rejected"] == 1
        assert s["best_sharpe"] == pytest.approx(1.10)  # from final_evaluation
        assert s["best_net"] == pytest.approx(0.045)
        assert s["any_synthetic"] is True  # th_synth has synthetic_inputs
    finally:
        data.close()


def test_instrument_snapshot_surfaces_provenance(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        snap = data.instrument_snapshot(SPOT)
        assert snap is not None
        assert snap.provenance == "real"
        assert snap.latest_value == pytest.approx(109.0)
        assert snap.latest_date == "2026-07-19"
        assert len(snap.spark) >= 2
    finally:
        data.close()


def test_equity_reconstructs_within_covered_window(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        entry = data.thesis_entry(cycle_id, "th_promoted")
        eq = data.reconstruct_equity(cycle_id, entry)
        assert eq.available is True
        assert set(eq.frame["split_type"]) <= {"refinement", "final_evaluation"}
        assert not eq.frame.empty
    finally:
        data.close()


def test_equity_refuses_when_window_not_covered(project):
    cfg, root, cycle_id = project
    data = DashboardData(cfg, root)
    try:
        # Point the thesis at a cycle whose split windows predate the real series.
        repo = Repository(root / "data/research.sqlite", root / "data/lake")
        old_cycle = repo.create_cycle({}, seed=1, max_refinement_depth=2, max_lineages=5)
        repo.create_split_allocation(old_cycle, "refinement", "2024-01-01", "2024-06-01", SPOT)
        repo.create_split_allocation(
            old_cycle, "final_evaluation", "2024-06-02", "2024-12-01", SPOT
        )
        entry = data.thesis_entry(cycle_id, "th_promoted")
        repo.close()

        eq = data.reconstruct_equity(old_cycle, entry)
        assert eq.available is False
        assert "not in the current lake" in eq.reason
        assert eq.frame.empty
    finally:
        data.close()
