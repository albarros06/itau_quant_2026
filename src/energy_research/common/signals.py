"""Deterministic thesis-hypothesis → daily-strategy-returns mapping.

Shared value logic used by both screening and backtesting (which may not import
each other); takes primitive arguments only, so ``common`` needs no knowledge of
any pipeline layer's types.
"""

from __future__ import annotations

import pandas as pd


def _aligned_daily_returns(prices: pd.DataFrame, instruments: list[str]) -> pd.DataFrame:
    """Per-instrument daily simple returns, rows with any missing value dropped."""
    missing = [i for i in instruments if i not in prices.columns]
    if missing:
        raise KeyError(f"price panel is missing instruments {missing}")
    return prices[instruments].pct_change().dropna(how="any")


def hypothesis_returns(prices: pd.DataFrame, instruments: list[str], direction: str) -> pd.Series:
    """Daily strategy returns for a hypothesis over a price panel.

    - long:   returns of the first instrument
    - short:  negative returns of the first instrument
    - spread / relative_value: first minus second instrument's returns

    This is the daily-return *series* (used for the screening bootstrap test and for
    Sharpe); for the buy-and-hold window total return / equity curve use
    ``hypothesis_equity_curve`` — the two must not be conflated (compounding this
    combined series would model a daily-rebalanced book, not a held position).
    """
    rets = _aligned_daily_returns(prices, instruments)
    if direction == "long":
        return rets[instruments[0]]
    if direction == "short":
        return -rets[instruments[0]]
    if direction in ("spread", "relative_value"):
        if len(instruments) < 2:
            raise ValueError(f"direction {direction!r} requires two instruments")
        return rets[instruments[0]] - rets[instruments[1]]
    raise ValueError(f"unknown direction {direction!r}")


def hypothesis_equity_curve(
    prices: pd.DataFrame, instruments: list[str], direction: str
) -> pd.Series:
    """Buy-and-hold equity curve (initial notional = 1.0) for the hypothesis.

    Each leg is compounded from its *own* price path so the legs drift apart over
    the window exactly as a held book does — the counterpart to the cost model
    charging a single entry+exit per leg. ``curve.iloc[-1] - 1.0`` is the window
    total return; feed the whole curve to a peak-to-trough drawdown.

    Compounding the *combined* daily series (``hypothesis_returns``) instead would
    keep the legs perfectly rebalanced against each other every day — a
    daily-rebalanced strategy, whose costs would be n_days of turnover, not two
    trades. That is the mismatch this function exists to avoid.
    """
    rets = _aligned_daily_returns(prices, instruments)
    growth = (1.0 + rets).cumprod()  # per-instrument compounded price path, base 1.0
    if direction == "long":
        return growth[instruments[0]]
    if direction == "short":
        # Static short P&L is the negative of the long leg's price move.
        return 2.0 - growth[instruments[0]]
    if direction in ("spread", "relative_value"):
        if len(instruments) < 2:
            raise ValueError(f"direction {direction!r} requires two instruments")
        long_pnl = growth[instruments[0]] - 1.0
        short_pnl = growth[instruments[1]] - 1.0
        return 1.0 + long_pnl - short_pnl
    raise ValueError(f"unknown direction {direction!r}")
