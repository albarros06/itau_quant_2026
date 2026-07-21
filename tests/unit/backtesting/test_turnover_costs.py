"""Turnover-aware cost scaling in isolation (003 turnover-cost-contract.md, SC-004)."""

from __future__ import annotations

import pytest

from energy_research.backtesting.costs import CostModel
from energy_research.config.settings import BacktestingConfig


def _model() -> CostModel:
    return CostModel(
        BacktestingConfig(transaction_cost_bps=10.0, slippage_bps=5.0, financing_annual_rate=0.126)
    )


def test_doubling_turnover_doubles_transaction_and_slippage():
    base = _model().compute(n_legs=1, entries=1, exits=1, in_market_days=100)
    twice = _model().compute(n_legs=1, entries=2, exits=2, in_market_days=100)
    assert twice.transaction_costs == pytest.approx(2 * base.transaction_costs)
    assert twice.slippage == pytest.approx(2 * base.slippage)
    # Financing depends on in-market days only, not turnover.
    assert twice.financing_carry == pytest.approx(base.financing_carry)


def test_halving_in_market_days_halves_financing():
    full = _model().compute(n_legs=1, entries=1, exits=1, in_market_days=200)
    half = _model().compute(n_legs=1, entries=1, exits=1, in_market_days=100)
    assert half.financing_carry == pytest.approx(full.financing_carry / 2)
    # Turnover unchanged → transaction/slippage unchanged.
    assert half.transaction_costs == pytest.approx(full.transaction_costs)


def test_unconditional_reproduces_pre003_constants():
    """entries=1, exits=1, in_market_days=n_days == the pre-003 '2 legs, full window'
    assumption, to the last bit (FR-012, SC-006)."""
    costs = _model().compute(n_legs=1, entries=1, exits=1, in_market_days=252)
    assert costs.transaction_costs == pytest.approx(2 * 10 / 1e4)
    assert costs.slippage == pytest.approx(2 * 5 / 1e4)
    assert costs.financing_carry == pytest.approx(0.126)


def test_basket_pays_per_leg_turnover():
    one_leg = _model().compute(n_legs=1, entries=1, exits=1, in_market_days=100)
    two_leg = _model().compute(n_legs=2, entries=1, exits=1, in_market_days=100)
    assert two_leg.transaction_costs == pytest.approx(2 * one_leg.transaction_costs)
    assert two_leg.slippage == pytest.approx(2 * one_leg.slippage)
