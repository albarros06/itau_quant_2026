"""Transaction cost, slippage, and financing/carry models (FR-017, Principle IV).

All parameters come from configuration; the models return per-unit-notional cost
fractions so ``engine`` can net them against gross return directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from energy_research.config.settings import BacktestingConfig

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class CostBreakdown:
    transaction_costs: float
    slippage: float
    financing_carry: float

    @property
    def total(self) -> float:
        return self.transaction_costs + self.slippage + self.financing_carry


class CostModel:
    def __init__(self, config: BacktestingConfig):
        self._config = config

    def compute(
        self,
        *,
        n_legs: int,
        entries: int,
        exits: int,
        in_market_days: int,
        gross_exposure: float = 1.0,
    ) -> CostBreakdown:
        """Turnover-aware costs (003 contracts/turnover-cost-contract.md).

        Transaction costs and slippage scale with realized entry/exit events per leg
        (``traded_notional = (entries + exits) * n_legs``), not a fixed round trip;
        financing/carry accrues only on in-market days. An unconditional always-in
        strategy (``entries=1, exits=1, in_market_days=n_days``) reproduces the
        pre-003 ``2 * n_legs`` notional and full-window financing exactly (FR-012).
        """
        traded_notional = (entries + exits) * n_legs * gross_exposure
        transaction_costs = traded_notional * self._config.transaction_cost_bps / 1e4
        slippage = traded_notional * self._config.slippage_bps / 1e4
        financing = (
            gross_exposure
            * self._config.financing_annual_rate
            * in_market_days
            / TRADING_DAYS_PER_YEAR
        )
        return CostBreakdown(
            transaction_costs=float(transaction_costs),
            slippage=float(slippage),
            financing_carry=float(financing),
        )
