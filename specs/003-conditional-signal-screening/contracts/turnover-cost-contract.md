# Contract: Turnover-Aware Cost Accounting

Extends [backtest-contract.md](../../001-auto-research-pipeline/contracts/backtest-contract.md).
Implements FR-007, FR-008. All rules of the parent contract (split scoping, ledger-gated final
evaluation, mandatory non-null cost components, no gross-only persistence) apply unchanged; this
document adds only what changes about *how the cost numbers are computed*.

## Input (in addition to the parent contract's)

- The `ActivityStats` derived from the same position mask
  ([conditional-signal-contract.md](./conditional-signal-contract.md)) used to compute the
  thesis's return stream for this split: `entries`, `exits`, `in_market_days`.

## Output (in addition to the parent contract's `BacktestResult`)

- `other_metrics` (already a JSON column, unchanged type) gains `in_market_days`, `total_days`,
  `entries`, `exits` alongside the existing `sharpe`/`max_drawdown`/etc. keys.

## Contract rules

1. **Transaction costs and slippage scale with realized turnover, not a fixed round-trip
   assumption**: `traded_notional = (entries + exits) * n_legs * gross_exposure` (replacing the
   prior hardcoded `2.0 * n_legs`); `transaction_costs = traded_notional * transaction_cost_bps /
   1e4`; `slippage = traded_notional * slippage_bps / 1e4` — unchanged bps-of-notional formula,
   changed notional.
2. **Financing/carry accrues only on in-market days**:
   `financing_carry = gross_exposure * financing_annual_rate * in_market_days /
   TRADING_DAYS_PER_YEAR` (replacing `n_days`).
3. **Unconditional theses are cost-invariant under this change**: for `condition=null`,
   `entries=1, exits=1, in_market_days=total_days` by construction (the mask is constant-1 for
   the whole split), so `traded_notional` and `financing_carry` compute to exactly the pre-003
   values — no numeric drift for any existing thesis type (FR-012, SC-006).
4. **Costs are recoverable from persisted state**: given a `BacktestResult`'s `other_metrics`
   (`entries`, `exits`, `in_market_days`) and the cycle's `config_snapshot` (bps rates, annual
   financing rate), `transaction_costs`/`slippage`/`financing_carry` are exactly reproducible by
   re-running `CostModel.compute` — no information used to produce the persisted costs is
   discarded (SC-004).
5. **The activity-gate defaults are per split, not global**: `run_refinement` checks
   `ActivityStats.in_market_days` (refinement-split) against
   `conditional_screening.min_active_days.refinement` (default 60) before computing any cost or
   persisting any result; `run_final_evaluation` checks against `.final_evaluation` (default 30)
   analogously. Below the threshold, the thesis is rejected with a reason naming both counts and
   no `BacktestResult` row exists for that split (mirrors
   [conditional-signal-contract.md](./conditional-signal-contract.md) rule 11 for the discovery
   split).
6. **Non-finite guard is unaffected**: the existing engine-level and datastore-level refusal of
   non-finite `gross_return`/`net_return`/cost components (added independently of this feature,
   `energy_research.backtesting.engine.run_backtest` / `Repository.insert_backtest_result`)
   applies to conditional results exactly as it does to unconditional ones — a condition producing
   a degenerate all-zero-then-divide return stream is caught by the same guard, not a new one.
