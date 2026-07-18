# Itaú Quant Research Platform — Automated Trading-Idea Research Pipeline

An end-to-end, minimally-supervised research pipeline that turns Brazilian
energy-market and derivatives data plus qualitative context into a statistically
screened, realistically backtested shortlist of trading theses — with a bounded
critique-and-improve loop and a fully auditable, reproducible report.

Feature docs: [specs/001-auto-research-pipeline/](specs/001-auto-research-pipeline/)
— see [quickstart.md](specs/001-auto-research-pipeline/quickstart.md) for operating
the pipeline and [plan.md](specs/001-auto-research-pipeline/plan.md) for the design.
Governance: [.specify/memory/constitution.md](.specify/memory/constitution.md).

## Architecture

A strict, single-direction layered pipeline. The mid-tier analysis layers never
call each other — they communicate only through persisted datastore records — and
the boundaries are enforced mechanically by import-linter (a violation is a failing
test, not a review comment).

```text
                 ┌──────────────────────────── cli ────────────────────────────┐
                 │                       orchestration                         │
                 │  (the only layer allowed to sequence the analysis layers)   │
                 └──┬──────────┬───────────┬───────────┬───────────┬───────────┘
                    ▼          ▼           ▼           ▼           ▼
              generation   screening   backtesting  critique   reporting
                    │          │           │           │           │
                    └──────────┴─────┬─────┴───────────┴───────────┘
                                     ▼
                                 datastore   (SQLite state + Parquet lake;
                                     ▲        owns split scoping + the ledger)
                                 cleaning
                                     ▲
                                 ingestion   (provider-agnostic connectors,
                                     ▲        config-keyed registry)
                                  common     (seed, logging, shared types, LLM transport)
                                     ▲
                                  config     (pydantic-validated YAML; no secrets)
```

Key structural guarantees:

- **Split integrity** — screening can only read discovery-split data; backtests
  only refinement- or final-evaluation-scoped data. The datastore exposes no
  unscoped read path.
- **Spend-once-per-lineage** — the final-evaluation period is consumed via one
  atomic ledger transaction per thesis lineage; reuse attempts are refused and
  durably recorded.
- **Constrained LLM autonomy** — thesis generation and critique emit only
  JSON-schema-validated, independently re-validated, inert data records. No
  broker/execution package exists anywhere in the dependency graph (enforced by
  an import-linter contract).
- **Backtest honesty** — every result carries transaction costs, slippage, and
  financing/carry (non-null database columns); synthetic data is labeled
  end to end into the report.
- **Reproducibility** — one seed entry point, config snapshot recorded per cycle,
  `replay` re-executes a cycle exactly.

## Usage

```bash
uv sync                                                  # install (uv.lock pinned)
uv run research-pipeline ingest    --config config/default.yaml
uv run research-pipeline run-cycle --config config/default.yaml
uv run research-pipeline replay    --config config/default.yaml --cycle-id <id>
```

Reports land in `data/reports/<cycle_id>.md`. All instruments, providers,
thresholds, cost models, and loop bounds live in `config/` — never in code.
The default configuration uses the clearly labeled synthetic `sample_provider`;
set `generation.backend: anthropic` (and export `ANTHROPIC_API_KEY`) for real
LLM-driven thesis generation.

## Development

```bash
uv run pytest              # contract + integration + unit suites
uv run ruff check src tests
uv run lint-imports        # architecture boundary contracts (also run by pytest)
```
