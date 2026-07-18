# Contract: Backtesting Layer

Implements FR-017–FR-019, Constitution Principle IV.

## Input

- One `TradingThesis` with `status = screened_passed` (for a `refinement`-split run) or
  `status = final_evaluation_pending` (for the single `final_evaluation`-split run).
- A `DataSplitAllocation` reference scoped to exactly one `split_type` — `refinement` or
  `final_evaluation`, never both, never unscoped.
- Cost/slippage/financing model parameters (from `config_snapshot`).

## Output

One `BacktestResult` (see data-model.md), with `transaction_costs`, `slippage`, and
`financing_carry` **always populated** (never null, never omitted) and `net_return` computed from
them — never a gross-only result (FR-017, Principle IV).

## Contract rules

1. **Split scoping is structural, not a parameter the caller can widen.** The layer's `datastore`
   client exposes separate methods for refinement-scoped and final-evaluation-scoped reads; there
   is no method that returns unscoped or cross-split data (FR-018).
2. **`final_evaluation` split access requires a successful `EvaluationLedger` spend first.** The
   backtesting layer calls the ledger's atomic spend operation
   ([evaluation-ledger-contract.md](./evaluation-ledger-contract.md)) before running a
   final-evaluation backtest; on refusal (already spent), it MUST NOT run the backtest and MUST
   produce a recorded refusal instead (FR-019, Edge Case: reuse of spent evaluation period).
3. **Exactly one `final_evaluation` `BacktestResult` may ever exist per lineage** — a structural
   consequence of rule 2 plus the ledger's uniqueness guarantee.
4. **No gross-only reporting**: any result missing a cost component is invalid and MUST be
   rejected before persistence, not persisted-then-filtered at display time (SC-004).
