# Contracts

This feature extends three existing 001 contracts rather than replacing them. Each file below
states only what's *new or changed*; where a rule from the 001 contract still applies unmodified,
it is referenced, not restated.

- [conditional-signal-contract.md](./conditional-signal-contract.md) — the `SignalCondition`
  vocabulary (extends
  [thesis-schema.md](../../001-auto-research-pipeline/contracts/thesis-schema.md)) and the
  deterministic, lookahead-free evaluation contract shared by screening and backtesting (extends
  [screening-contract.md](../../001-auto-research-pipeline/contracts/screening-contract.md)).
- [turnover-cost-contract.md](./turnover-cost-contract.md) — the entry/exit-based cost accounting
  rule (extends
  [backtest-contract.md](../../001-auto-research-pipeline/contracts/backtest-contract.md)).
- [multi-leg-evaluation-contract.md](./multi-leg-evaluation-contract.md) — equal-weight basket
  semantics for `long`/`short` and the tightened exactly-two-instrument rule for
  `spread`/`relative_value` (extends thesis-schema.md's `direction` rules).
