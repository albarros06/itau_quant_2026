"""Vectorized backtest engine (research.md §5, contracts/backtest-contract.md).

Accepts ONLY split-scoped data (a ``SplitScopedData`` for the refinement or
final-evaluation split, produced by the datastore's scoped query methods) — never
a raw date range — so a caller cannot widen its own data access (rule 1). Every
result carries all three cost components; a gross-only result cannot leave this
module (rule 4).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from energy_research.backtesting.costs import TRADING_DAYS_PER_YEAR, CostModel
from energy_research.common.signals import hypothesis_equity_curve, hypothesis_returns
from energy_research.datastore.repository import SplitScopedData

_ALLOWED_SPLITS = ("refinement", "final_evaluation")


@dataclass(frozen=True)
class BacktestComputation:
    split_type: str
    gross_return: float
    transaction_costs: float
    slippage: float
    financing_carry: float
    net_return: float
    other_metrics: dict


def run_backtest(
    data: SplitScopedData, hypothesis: dict, cost_model: CostModel
) -> BacktestComputation:
    if data.split_type not in _ALLOWED_SPLITS:
        raise ValueError(
            f"backtest engine only accepts {_ALLOWED_SPLITS} data, got "
            f"{data.split_type!r} — split scoping is structural (FR-018)"
        )
    instruments = hypothesis["instruments"]
    direction = hypothesis["direction"]
    returns = hypothesis_returns(data.prices, instruments, direction)
    n_days = len(returns)
    if n_days == 0:
        raise ValueError(f"no {data.split_type}-split observations for instruments {instruments}")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        # A zero/NaN price turns percent-change into inf/NaN and would poison
        # every downstream figure. Refuse loudly, naming the inputs, instead of
        # letting a non-finite "result" masquerade as performance (Principle VII;
        # observed live with unclamped near-zero CMO prices).
        raise ValueError(
            f"{data.split_type}-split returns for instruments {instruments} contain "
            "non-finite values — an input series has zero/NaN prices; fix the series "
            "(e.g. a value_clamp on the provider descriptor) rather than backtesting it"
        )

    # Buy-and-hold over the split window: the position is entered once and exited
    # once (the cost model's 2-leg trade count), so the window return is the
    # compounded price move of each leg — not the arithmetic sum of daily returns,
    # which would model a daily-rebalanced book and understate turnover costs by a
    # factor of ~n_days. See signals.hypothesis_equity_curve.
    equity = hypothesis_equity_curve(data.prices, instruments, direction).to_numpy(dtype=float)
    gross = float(equity[-1] - 1.0)
    n_legs = 2 if direction in ("spread", "relative_value") else 1
    costs = cost_model.compute(n_legs=n_legs, n_days=n_days)
    net = gross - costs.total

    daily = returns.to_numpy(dtype=float)
    # Sample std (ddof=1): a backtest window is a sample of possible outcomes, not
    # the whole population, so correct for small-sample under-dispersion. Kept in
    # lockstep with screening.methods.block_bootstrap_test, which uses the same
    # convention — the two must never diverge.
    std = daily.std(ddof=1) if daily.size > 1 else 0.0
    sharpe = float(daily.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    # Peak-to-trough drawdown on the same compounded equity curve as the gross
    # return, as a fraction of the running peak.
    running_max = np.maximum.accumulate(equity)
    drawdown = float((1.0 - equity / running_max).max()) if n_days else 0.0

    return BacktestComputation(
        split_type=data.split_type,
        gross_return=gross,
        transaction_costs=costs.transaction_costs,
        slippage=costs.slippage,
        financing_carry=costs.financing_carry,
        net_return=net,
        other_metrics={
            "sharpe": sharpe,
            "max_drawdown": drawdown,
            "n_days": n_days,
            "date_range": list(data.date_range),
            "any_synthetic_input": data.any_synthetic,
            "calendar_dropped_dates": data.misaligned_dropped,
        },
    )
