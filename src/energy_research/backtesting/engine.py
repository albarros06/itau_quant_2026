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
from energy_research.common.signals import hypothesis_returns
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

    gross = float(returns.sum())
    n_legs = 2 if direction in ("spread", "relative_value") else 1
    costs = cost_model.compute(n_legs=n_legs, n_days=n_days)
    net = gross - costs.total

    daily = returns.to_numpy(dtype=float)
    std = daily.std(ddof=0)
    sharpe = float(daily.mean() / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std > 0 else 0.0
    cumulative = np.cumsum(daily)
    drawdown = float((np.maximum.accumulate(cumulative) - cumulative).max()) if n_days else 0.0

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
        },
    )
