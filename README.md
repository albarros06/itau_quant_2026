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

## Operations agent (`ops_agent`)

A second, structurally-separate package, `src/ops_agent/`, operates the pipeline
above end to end: discovering vendor offerings, drafting provisioning/onboarding
proposals, keeping data fresh, triggering cycles on a cadence, and surfacing
shortlists — while `energy_research` itself stays the unchanged substrate.

Feature docs: [specs/002-research-ops-agent/](specs/002-research-ops-agent/) — see
[quickstart.md](specs/002-research-ops-agent/quickstart.md) for operating the agent
and [plan.md](specs/002-research-ops-agent/plan.md) for the design.

```text
ops_agent  ──imports──▶  energy_research      (one-directional; energy_research
   │                                            never imports ops_agent — enforced
   │                                            by an import-linter contract)
   ├─ discovery/    vendor catalog probing + LLM interpretation into draft proposals
   ├─ proposals/    git-branch-based change control (ops-proposal/* branches;
   │                approval = a human `git merge`, never the agent itself)
   ├─ onboarding/   config-only vendor onboarding (Data Source Descriptor drafting)
   ├─ store/        data/ops_agent.sqlite — activity log, budgets, schedule, proposals
   ├─ budget.py     per-period LLM/vendor-request spend guard
   ├─ scheduling.py cadence-driven "is X due" for cycle/market-refresh/qualitative-poll
   ├─ remediation.py bounded retry-then-escalate on stale/missing data
   └─ agent.py      bootstrap() / tick(): the two entry points cli.py wires up
```

The agent's reach is structurally limited to configuration proposals, data
ingestion, cycle triggering, and reading outputs — it has no import path to
`generation`/`screening`/`backtesting`/`critique`/`reporting`/`datastore.ledger`
(contracts/ops-agent-boundary.md), mechanically enforced the same way as every
other architecture boundary in this repo.

```bash
uv run research-ops-agent bootstrap --config config/ops_agent.yaml   # discover -> proposals
uv run research-ops-agent approve   <proposal-id>                     # human-run only
uv run research-ops-agent tick      --config config/ops_agent.yaml   # refresh + cycle if due
uv run research-ops-agent log       --since <ts>                      # full audit trail
```

## Development

```bash
uv run pytest              # contract + integration + unit suites
uv run ruff check src tests
uv run lint-imports        # architecture boundary contracts (also run by pytest)
```
