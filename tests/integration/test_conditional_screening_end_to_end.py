"""Planted-signal conditional screening (003 spec.md US1, SC-001/SC-002/SC-007).

Instrument X's returns are positive only when signal S is below its 20-day SMA; a
conditional thesis passes screening while the unconditional one fails, and inverting
the condition flips the result. Under-observed conditions are refused before testing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from energy_research.common import seed as seed_mod
from energy_research.common.conditions import (
    ConditionClause,
    SignalCondition,
    evaluate_condition,
)
from energy_research.common.records import CleanedSeries
from energy_research.config.settings import (
    BacktestingConfig,
    DataQualityConfig,
    DatastoreConfig,
    InstrumentConfig,
    MarketProviderEntry,
    PipelineConfig,
    ProvidersConfig,
    RefinementConfig,
    ScreeningConfig,
    SplitsConfig,
)
from energy_research.datastore.repository import Repository
from energy_research.screening.service import ScreeningService

# S < SMA(S, 20): the regime in which X drifts up.
_BELOW_SMA = {
    "instrument_key": "S",
    "subject_transform": "level",
    "subject_lookback": None,
    "comparator": "<",
    "reference_kind": "sma",
    "reference_value": 0.0,
    "reference_lookback": 20,
    "reference_quantile": None,
}


def _config(base_dir) -> PipelineConfig:
    return PipelineConfig(
        providers=ProvidersConfig(
            market_data=[MarketProviderEntry(provider_id="planted", categories=["spot"])]
        ),
        datastore=DatastoreConfig(
            db_path=base_dir / "research.sqlite",
            lake_dir=base_dir / "lake",
            reports_dir=base_dir / "reports",
        ),
        instrument_universe=[
            InstrumentConfig(key="S", category="spot"),
            InstrumentConfig(key="X", category="spot"),
        ],
        data_quality=DataQualityConfig(freshness_tolerance_days=7),
        splits=SplitsConfig(discovery_fraction=0.5, refinement_fraction=0.3),
        screening=ScreeningConfig(n_bootstrap=300, block_size=10, alpha=0.10),
        backtesting=BacktestingConfig(
            transaction_cost_bps=5.0, slippage_bps=3.0, financing_annual_rate=0.11
        ),
        refinement=RefinementConfig(max_refinement_depth_per_lineage=1, max_lineages_per_run=4),
    )


def _store(repo: Repository, key: str, values: np.ndarray, dates: pd.DatetimeIndex) -> None:
    frame = pd.DataFrame(
        {
            "date": dates,
            "value": values,
            "provenance": "synthetic",
            "freshness_ts": datetime.now(UTC).isoformat(),
        }
    )
    repo.store_cleaned_series(
        CleanedSeries(
            category="spot",
            instrument_key=key,
            provider_id="planted",
            provenance="synthetic",
            freshness_ts=datetime.now(UTC),
            frame=frame,
        )
    )


def _planted_panel(n: int) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    """S oscillates; X drifts +2% when the lagged S<SMA(S,20) mask is on, −2.5% off."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    t = np.arange(n)
    s = 100.0 + 10.0 * np.sin(2 * np.pi * t / 40.0)
    condition = SignalCondition(clauses=[ConditionClause(**_BELOW_SMA)])
    mask = evaluate_condition(pd.DataFrame({"S": s}, index=dates), condition).to_numpy()
    x_returns = np.where(mask == 1.0, 0.02, -0.025)
    x = 100.0 * np.cumprod(1.0 + x_returns)
    return dates, s, x


def _seed_cycle(repo: Repository, config: PipelineConfig, n: int) -> str:
    dates, s, x = _planted_panel(n)
    _store(repo, "S", s, dates)
    _store(repo, "X", x, dates)
    cycle_id = repo.create_cycle(config.snapshot(), seed=7, max_refinement_depth=1, max_lineages=4)
    repo.create_split_allocation(
        cycle_id, "discovery", str(dates[0].date()), str(dates[-1].date()), "S,X"
    )
    return cycle_id


def _add_thesis(repo, cycle_id, condition) -> str:
    lineage = repo.create_lineage(cycle_id, root_thesis_id="pending")
    return repo.insert_thesis(
        cycle_id=cycle_id,
        lineage_id=lineage,
        rationale="Planted-signal fixture thesis for conditional screening validation.",
        hypothesis={
            "instruments": ["X"],
            "direction": "long",
            "horizon": "refinement_window",
            "condition": condition,
        },
        status="proposed",
    )


@pytest.fixture
def screening_env(tmp_path):
    seed_mod.set_seed(20260721)
    config = _config(tmp_path)
    repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
    yield config, repo
    repo.close()


def test_conditional_passes_unconditional_fails_and_invert_flips(screening_env):
    config, repo = screening_env
    cycle_id = _seed_cycle(repo, config, n=320)
    inverted = {**_BELOW_SMA, "comparator": ">="}

    t_uncond = _add_thesis(repo, cycle_id, None)
    t_cond = _add_thesis(repo, cycle_id, {"clauses": [_BELOW_SMA]})
    t_inv = _add_thesis(repo, cycle_id, {"clauses": [inverted]})

    svc = ScreeningService(repo, config)
    # Each thesis screened as its own family, so verdicts are on the merits alone.
    for tid in (t_uncond, t_cond, t_inv):
        svc.screen_cycle(cycle_id, thesis_ids=[tid])

    r_uncond = repo.screening_result_for(t_uncond)
    r_cond = repo.screening_result_for(t_cond)
    r_inv = repo.screening_result_for(t_inv)

    assert r_cond["verdict"] == "pass"  # SC-002: the conditional thesis is real signal
    assert r_uncond["verdict"] == "fail"  # unconditional mixes regimes → no edge
    assert r_inv["verdict"] == "fail"  # inverting the condition flips the result
    # SC-001: two theses differing only in condition get different statistics.
    assert r_cond["statistic_value"] != pytest.approx(r_uncond["statistic_value"])
    # Activity is persisted for the conditional thesis (genuinely < full window).
    assert 0 < r_cond["other_metrics"]["in_market_days"] < r_cond["other_metrics"]["total_days"]


def test_under_observed_condition_is_refused_with_both_counts(screening_env):
    config, repo = screening_env
    # A 60-day discovery panel: even a mostly-active condition is < the 100-day floor.
    cycle_id = _seed_cycle(repo, config, n=60)
    tid = _add_thesis(repo, cycle_id, {"clauses": [_BELOW_SMA]})

    ScreeningService(repo, config).screen_cycle(cycle_id, thesis_ids=[tid])

    assert repo.screening_result_for(tid) is None  # no p-value recorded (excluded from family)
    thesis = next(t for t in repo.theses_for_cycle(cycle_id) if t["thesis_id"] == tid)
    assert thesis["status"] == "screened_rejected"
    assert "100" in thesis["status_reason"]  # required count named
    assert "below the required minimum" in thesis["status_reason"]


def test_never_active_condition_refused_without_nan(screening_env):
    config, repo = screening_env
    cycle_id = _seed_cycle(repo, config, n=320)
    never = {**_BELOW_SMA, "reference_kind": "constant", "reference_value": -1e9,
             "reference_lookback": None}
    tid = _add_thesis(repo, cycle_id, {"clauses": [never]})

    # 0 active days must hit the refusal path cleanly — no divide-by-zero / NaN.
    ScreeningService(repo, config).screen_cycle(cycle_id, thesis_ids=[tid])

    assert repo.screening_result_for(tid) is None
    thesis = next(t for t in repo.theses_for_cycle(cycle_id) if t["thesis_id"] == tid)
    assert thesis["status"] == "screened_rejected"
    assert "only 0" in thesis["status_reason"]
