"""Deterministic thesis-hypothesis → daily-strategy-returns mapping.

Shared value logic used by both screening and backtesting (which may not import
each other); takes primitive arguments only, so ``common`` needs no knowledge of
any pipeline layer's types. This is the single seam where "what does this thesis's
return stream look like" is decided — conditional masking (003) and equal-weight
multi-leg baskets both live here so the two callers cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from energy_research.common.conditions import SignalCondition, evaluate_condition


@dataclass(frozen=True)
class ActivityStats:
    """Realized position activity over one split, derived from the 0/1 mask.

    For an unconditional thesis ``in_market_days == total_days`` and
    ``entries == exits == 1`` — identical to the implicit accounting the pre-003
    cost model assumed (003 data-model.md §ActivityStats, FR-012).
    """

    in_market_days: int
    total_days: int
    entries: int
    exits: int

    def as_dict(self) -> dict:
        return {
            "in_market_days": self.in_market_days,
            "total_days": self.total_days,
            "entries": self.entries,
            "exits": self.exits,
        }


def _activity_stats(mask: np.ndarray, total_days: int) -> ActivityStats:
    """Entries/exits/in-market from a 0/1 mask, treating the position as flat (0)
    before the first day (so an always-in mask is one entry + one closing exit)."""
    in_market = int(mask.sum())
    prev = np.concatenate(([0.0], mask[:-1])) if mask.size else mask
    entries = int(((prev == 0.0) & (mask == 1.0)).sum())
    exits = int(((prev == 1.0) & (mask == 0.0)).sum())
    if mask.size and mask[-1] == 1.0:
        exits += 1  # close the still-open position at split end (round-trip assumption)
    return ActivityStats(
        in_market_days=in_market, total_days=total_days, entries=entries, exits=exits
    )


def hypothesis_returns(
    prices: pd.DataFrame,
    instruments: list[str],
    direction: str,
    condition: SignalCondition | None = None,
) -> tuple[pd.Series, ActivityStats]:
    """Daily strategy returns for a hypothesis over a price panel, plus activity.

    - long:   equal-weight ``1/n`` basket of the declared instruments' returns
    - short:  the same basket, negated
    - spread / relative_value: first minus second instrument's returns (exactly two)

    When a ``condition`` is present its 0/1 mask (lookahead-shifted, warmup-inactive)
    is multiplied into each leg's return so inactive days contribute exactly zero.
    ``condition=None`` and ``n=1`` reduce to the exact pre-003 single-instrument
    formula, byte-for-byte (FR-012, SC-006).
    """
    missing = [i for i in instruments if i not in prices.columns]
    if missing:
        raise KeyError(f"price panel is missing instruments {missing}")

    rets = prices[instruments].pct_change().dropna(how="any")
    mask = evaluate_condition(prices, condition).reindex(rets.index).fillna(0.0)

    if direction in ("long", "short"):
        sign = 1.0 if direction == "long" else -1.0
        legs = [sign * rets[i] * mask for i in instruments]
        combined = sum(legs) / float(len(instruments))
    elif direction in ("spread", "relative_value"):
        if len(instruments) < 2:
            raise ValueError(f"direction {direction!r} requires two instruments")
        combined = (rets[instruments[0]] - rets[instruments[1]]) * mask
    else:
        raise ValueError(f"unknown direction {direction!r}")

    activity = _activity_stats(mask.to_numpy(dtype=float), total_days=len(rets))
    return combined, activity
