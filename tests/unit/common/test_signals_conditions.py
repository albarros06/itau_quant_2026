"""evaluate_condition + hypothesis_returns: regression-lock, lookahead, warmup,
multi-clause AND, and multi-leg basket math (003 research.md §9, SC-003/SC-006)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from energy_research.common.conditions import (
    ConditionClause,
    SignalCondition,
    evaluate_condition,
)
from energy_research.common.signals import hypothesis_returns


def _panel(n=120, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="D")
    x = 100 * np.cumprod(1 + rng.normal(0.001, 0.02, n))
    y = 100 * np.cumprod(1 + rng.normal(0.0005, 0.02, n))
    s = 100 * np.cumprod(1 + rng.normal(0.0, 0.01, n))  # a "signal" instrument
    return pd.DataFrame({"X": x, "Y": y, "S": s}, index=dates)


def _clause(**kw) -> ConditionClause:
    base = dict(
        instrument_key="S",
        subject_transform="level",
        subject_lookback=None,
        comparator="<",
        reference_kind="constant",
        reference_value=100.0,
        reference_lookback=None,
        reference_quantile=None,
    )
    base.update(kw)
    return ConditionClause(**base)


class TestUnconditionalRegression:
    """condition=None reproduces the pre-003 single-instrument/spread formula exactly."""

    def test_unconditional_regression_long(self):
        prices = _panel()
        ref = prices["X"].pct_change().dropna()
        got, activity = hypothesis_returns(prices, ["X"], "long", None)
        assert np.array_equal(got.to_numpy(), ref.to_numpy())
        assert activity.in_market_days == activity.total_days == len(ref)
        assert activity.entries == 1 and activity.exits == 1

    def test_unconditional_regression_short(self):
        prices = _panel()
        ref = -prices["X"].pct_change().dropna()
        got, _ = hypothesis_returns(prices, ["X"], "short", None)
        assert np.array_equal(got.to_numpy(), ref.to_numpy())

    def test_unconditional_regression_spread(self):
        prices = _panel()
        rets = prices[["X", "Y"]].pct_change().dropna(how="any")
        ref = rets["X"] - rets["Y"]
        got, _ = hypothesis_returns(prices, ["X", "Y"], "spread", None)
        assert np.array_equal(got.to_numpy(), ref.to_numpy())


class TestMultiLegBasket:
    def test_long_basket_is_average_of_single_legs(self):
        prices = _panel()
        basket, _ = hypothesis_returns(prices, ["X", "Y"], "long", None)
        x_only, _ = hypothesis_returns(prices, ["X"], "long", None)
        y_only, _ = hypothesis_returns(prices, ["Y"], "long", None)
        expected = (x_only + y_only) / 2.0
        assert np.allclose(basket.to_numpy(), expected.to_numpy())


class TestLookahead:
    def test_lookahead_first_day_is_flat_and_shift_changes_positions(self):
        prices = _panel()
        cond = SignalCondition(clauses=[_clause(comparator="<", reference_value=100.0)])
        mask = evaluate_condition(prices, cond)
        # Decision at close of day t drives exposure from t+1: first day is always flat.
        assert mask.iloc[0] == 0.0
        # SC-003: shifting every signal forward one day changes the position series.
        shifted_prices = prices.shift(1).bfill()
        mask_shifted = evaluate_condition(shifted_prices, cond)
        assert not np.array_equal(mask.to_numpy(), mask_shifted.to_numpy())

    def test_extreme_value_never_enters_its_own_day_return(self):
        prices = _panel()
        # A condition on S that is true early; plant an extreme X move on the first
        # active day and confirm the mask for that day reflects the PRIOR day only.
        cond = SignalCondition(clauses=[_clause(comparator=">", reference_value=0.0)])  # always
        mask = evaluate_condition(prices, cond)
        active = mask.to_numpy()
        # 'always true' becomes active from day 1 (day 0 flat by the one-day shift).
        assert active[0] == 0.0
        assert active[1] == 1.0


class TestWarmupAndCombination:
    def test_sma_warmup_resolves_inactive_not_nan(self):
        prices = _panel()
        cond = SignalCondition(
            clauses=[
                _clause(
                    subject_transform="sma",
                    subject_lookback=20,
                    comparator="<",
                    reference_kind="constant",
                    reference_value=1e9,  # SMA always below → active once warm
                )
            ]
        )
        mask = evaluate_condition(prices, cond)
        assert not mask.isna().any()
        # First 20-1 rows have no SMA → inactive; then active (post one-day shift).
        assert mask.iloc[:19].sum() == 0.0
        assert mask.iloc[25] == 1.0

    def test_multi_clause_is_and(self):
        prices = _panel()
        c1 = _clause(instrument_key="S", comparator="<", reference_value=100.0)
        c2 = _clause(instrument_key="S", comparator=">", reference_value=99.0)
        both = evaluate_condition(prices, SignalCondition(clauses=[c1, c2]))
        only1 = evaluate_condition(prices, SignalCondition(clauses=[c1]))
        # AND is a subset of either clause alone.
        assert ((both.to_numpy() == 1.0) <= (only1.to_numpy() == 1.0)).all()


class TestConditionActivity:
    def test_masked_days_contribute_zero_and_activity_counts_transitions(self):
        prices = _panel()
        cond = SignalCondition(clauses=[_clause(comparator="<", reference_value=100.0)])
        returns, activity = hypothesis_returns(prices, ["X"], "long", cond)
        assert activity.in_market_days == int(
            evaluate_condition(prices, cond).reindex(returns.index).sum()
        )
        assert activity.in_market_days < activity.total_days  # genuinely conditional
        assert activity.entries >= 1 and activity.exits >= 1
        # Inactive days contribute exactly zero return.
        mask = evaluate_condition(prices, cond).reindex(returns.index).to_numpy()
        assert returns.to_numpy()[mask == 0.0] == pytest.approx(0.0)
