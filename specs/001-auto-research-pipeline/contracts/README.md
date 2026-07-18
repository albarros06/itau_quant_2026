# Contracts

This feature is a batch pipeline, not a networked API — "contracts" here are the internal
interfaces between layers, plus the external LLM-facing schemas. Each contract is what
`/speckit-tasks` and `/speckit-implement` build against and what contract tests in
`tests/contract/` verify.

- [architecture-boundaries.md](./architecture-boundaries.md) — the enforced layer dependency
  contract (import-linter rules).
- [data-connector.md](./data-connector.md) — the provider-agnostic ingestion interface
  (Constitution Principle I), covering both market-data and qualitative-context connectors.
- [thesis-schema.md](./thesis-schema.md) — the schema-validated LLM thesis-generation output
  contract (Constitution Principle III).
- [critique-schema.md](./critique-schema.md) — the schema-validated LLM critique output contract.
- [screening-contract.md](./screening-contract.md) — screening layer input/output contract,
  including the mandatory multiplicity-control application point.
- [backtest-contract.md](./backtest-contract.md) — backtesting layer input/output contract,
  including split-scoping and mandatory cost fields.
- [evaluation-ledger-contract.md](./evaluation-ledger-contract.md) — the spent-once-per-lineage
  transactional contract.
- [report-contract.md](./report-contract.md) — required content of the end-of-cycle report
  artifact.
