"""Deterministic thesis-hypothesis → daily-strategy-returns mapping.

Shared value logic used by both screening and backtesting (which may not import
each other); takes primitive arguments only, so ``common`` needs no knowledge of
any pipeline layer's types.
"""

from __future__ import annotations

import pandas as pd


def hypothesis_returns(prices: pd.DataFrame, instruments: list[str], direction: str) -> pd.Series:
    """Daily strategy returns for a hypothesis over a price panel.

    - long:   returns of the first instrument
    - short:  negative returns of the first instrument
    - spread / relative_value: first minus second instrument's returns
    """
    missing = [i for i in instruments if i not in prices.columns]
    if missing:
        raise KeyError(f"price panel is missing instruments {missing}")
    rets = prices[instruments].pct_change().dropna(how="any")
    if direction == "long":
        return rets[instruments[0]]
    if direction == "short":
        return -rets[instruments[0]]
    if direction in ("spread", "relative_value"):
        if len(instruments) < 2:
            raise ValueError(f"direction {direction!r} requires two instruments")
        return rets[instruments[0]] - rets[instruments[1]]
    raise ValueError(f"unknown direction {direction!r}")
