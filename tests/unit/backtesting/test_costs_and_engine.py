from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from energy_research.backtesting.costs import CostModel
from energy_research.backtesting.engine import run_backtest
from energy_research.config.settings import BacktestingConfig
from energy_research.datastore.repository import SplitScopedData


def make_config(**kw):
    defaults = {"transaction_cost_bps": 10.0, "slippage_bps": 5.0, "financing_annual_rate": 0.126}
    defaults.update(kw)
    return BacktestingConfig(**defaults)


def make_data(split_type="refinement", n=100, drift=0.002):
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    values = 100 * np.cumprod(1 + np.full(n, drift))
    prices = pd.DataFrame({"X": values, "Y": np.full(n, 100.0)}, index=dates)
    return SplitScopedData(
        split_type=split_type,
        date_range=(str(dates[0].date()), str(dates[-1].date())),
        prices=prices,
        provenance={"X": "synthetic", "Y": "synthetic"},
    )


class TestCostModel:
    def test_breakdown_arithmetic(self):
        costs = CostModel(make_config()).compute(n_legs=1, n_days=252)
        assert costs.transaction_costs == pytest.approx(2 * 10 / 1e4)
        assert costs.slippage == pytest.approx(2 * 5 / 1e4)
        assert costs.financing_carry == pytest.approx(0.126)
        assert costs.total == pytest.approx(0.002 + 0.001 + 0.126)

    def test_spread_doubles_traded_notional(self):
        one = CostModel(make_config()).compute(n_legs=1, n_days=10)
        two = CostModel(make_config()).compute(n_legs=2, n_days=10)
        assert two.transaction_costs == pytest.approx(2 * one.transaction_costs)
        assert two.financing_carry == pytest.approx(one.financing_carry)


class TestEngine:
    def test_net_is_gross_minus_all_components(self):
        result = run_backtest(
            make_data(), {"instruments": ["X"], "direction": "long"}, CostModel(make_config())
        )
        assert result.net_return == pytest.approx(
            result.gross_return
            - result.transaction_costs
            - result.slippage
            - result.financing_carry
        )
        assert result.gross_return > 0

    def test_short_flips_sign_of_gross(self):
        long_r = run_backtest(
            make_data(), {"instruments": ["X"], "direction": "long"}, CostModel(make_config())
        )
        short_r = run_backtest(
            make_data(), {"instruments": ["X"], "direction": "short"}, CostModel(make_config())
        )
        assert short_r.gross_return == pytest.approx(-long_r.gross_return)

    def test_rejects_discovery_split_structurally(self):
        with pytest.raises(ValueError, match="split scoping is structural"):
            run_backtest(
                make_data(split_type="discovery"),
                {"instruments": ["X"], "direction": "long"},
                CostModel(make_config()),
            )

    def test_rejects_empty_window(self):
        data = make_data(n=1)  # single price → zero return observations
        with pytest.raises(ValueError, match="no refinement-split observations"):
            run_backtest(
                data, {"instruments": ["X"], "direction": "long"}, CostModel(make_config())
            )

    def test_synthetic_flag_propagates_into_metrics(self):
        result = run_backtest(
            make_data(), {"instruments": ["X"], "direction": "long"}, CostModel(make_config())
        )
        assert result.other_metrics["any_synthetic_input"] is True
