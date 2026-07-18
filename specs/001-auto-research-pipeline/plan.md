# Implementation Plan: Automated Trading-Idea Research Pipeline

**Branch**: `001-auto-research-pipeline` | **Date**: 2026-07-18 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-auto-research-pipeline/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Build an end-to-end, minimally-supervised research pipeline that turns current Brazilian
energy-market and derivatives data plus qualitative context into a statistically screened,
realistically backtested shortlist of trading theses, with a bounded critique-and-improve loop and
a fully auditable report. The architecture is a **strict, single-direction layered pipeline**
(config → common → ingestion → cleaning → datastore → {generation, screening, backtesting,
critique, reporting} → orchestration) in which the mid-tier analysis layers never call each other
directly — they communicate only by reading and writing persisted records in `datastore` — and
layer boundaries are enforced mechanically (import-linter), not just by convention. This directly
implements the constitution's data-provider agnosticism, one-shot statistical rigor, constrained
LLM autonomy, and backtest-honesty principles as structural properties of the codebase rather than
review-time checks. See [research.md](./research.md) for the decisions behind each technology
choice.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `pydantic` (schema validation for LLM output, config, and entity
models), `pandas` + `pyarrow` (data manipulation and the Parquet data lake), `scipy`/`statsmodels`
(statistical screening tests), `anthropic` SDK (LLM structured-output calls for thesis
generation/critique), `import-linter` (architecture boundary enforcement), `pytest` (testing).
No web framework, no broker/execution SDK of any kind (structurally excluded — see Constitution
Principle III and spec Out of Scope).

**Storage**: SQLite for all structured/relational state (theses, lineages, evaluation ledger,
screening/backtest results, critiques, cycles, reports); Parquet files (partitioned by category /
instrument / date) for the market and qualitative-context data lake. See
[research.md §2](./research.md#2-storage-relational-ledger--columnar-data-lake).

**Testing**: `pytest` for unit/integration tests; `import-linter` layer-contract checks and JSON
Schema validation checks run as contract tests (`tests/contract/`); an integration test drives a
full cycle against a clearly labeled synthetic dataset (quickstart.md §5) to verify User Story 1
end to end without live providers.

**Target Platform**: Linux server or local developer machine. The pipeline is a CLI-invoked batch
job (`research-pipeline ingest`, `research-pipeline run-cycle`, `research-pipeline replay`), not a
persistent service; "continuous" ingestion (FR-001) is achieved by an externally configured
scheduler (cron/CI) triggering the CLI at a configurable interval, not an embedded scheduler
process (research.md §6).

**Project Type**: Single project — a Python library/CLI package. The interactive Streamlit
dashboard is an explicitly separate feature (spec Assumptions) that will consume this pipeline's
persisted `datastore`/report artifacts; it is out of scope for this plan.

**Performance Goals**: Not latency-critical — a batch/offline research workload. No hard SLA is
specified in the spec; default expectation is that a full research cycle over the configured
instrument universe and refinement-loop bounds completes within a single operational run (minutes
to low hours, not a real-time constraint).

**Constraints**: No dependency on, or code path to, any broker/execution/order-placement package
(structurally enforced via the architecture boundary contract, see
[contracts/architecture-boundaries.md](./contracts/architecture-boundaries.md)). All randomness
seeded via a single entry point; all dependencies pinned via a committed lockfile
(research.md §7–8). All provider credentials referenced via configuration (env var names), never
embedded in code or config values committed to the repo.

**Scale/Scope**: Tens of instruments/tenors across the configured Brazilian energy and derivatives
universe; multi-year daily (and where available intraday) history per series. Per run, the number
of lineages/refinement iterations is bounded by two configurable caps (FR-022) — expected order of
tens per cycle, not hundreds; exact defaults are a configuration concern, not fixed here.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Provider-Agnostic Data Ingestion | **PASS** | Single `MarketDataConnector` / `QualitativeContextConnector` protocol family (research.md §9, contracts/data-connector.md); all providers resolved via config-keyed registry; no downstream layer imports a concrete provider (architecture-boundaries.md). |
| II. Statistical Rigor Before Backtesting | **PASS** | `screening` layer reads discovery-split data only, enforced by split-scoped `datastore` query methods, not caller discipline (data-model.md §DataSplitAllocation). Spent-once-per-lineage enforced transactionally by the `EvaluationLedger` (evaluation-ledger-contract.md), not by convention. |
| III. Constrained LLM Autonomy | **PASS** | `generation`/`critique` emit only JSON-Schema-validated, double-validated output (thesis-schema.md, critique-schema.md); failures rejected, never repaired (FR-011). No broker/execution package exists in the dependency set, and the architecture boundary contract makes that structural, not incidental. |
| IV. Backtest Honesty | **PASS** | `BacktestResult` schema makes `transaction_costs`/`slippage`/`financing_carry` mandatory, non-null fields (data-model.md); a result missing them is invalid and cannot be persisted (backtest-contract.md). `provenance=synthetic` propagates from `DataSeries` through every downstream artifact into the report (report-contract.md). |
| V. Mobile-First, Fully Responsive UI | **N/A (deferred)** | This plan covers the research pipeline only; the Streamlit dashboard is a separate, not-yet-planned feature (spec Assumptions). No UI is built here, so this gate does not apply to this plan. |
| VI. Configuration Over Hardcoding | **PASS** | Instrument universe, provider registry, statistical/multiplicity method + parameters, cost/slippage/financing models, and refinement-loop bounds are all `pydantic`-validated config (quickstart.md §1), never hardcoded. |
| VII. Fail-Loud Observability | **PASS** | Every detected data-quality issue produces a `DataQualityRecord`, whether or not auto-corrected (data-model.md); stale data structurally refuses to start a cycle (FR-006); the ledger's refusal path is logged, never a silent no-op (evaluation-ledger-contract.md). |
| VIII. Simplicity & Reproducibility | **PASS** | Purpose-built lightweight backtest engine instead of a heavyweight framework, SQLite instead of a database server, no embedded scheduler (research.md §5–6) — chosen because they need less integration code than the alternatives, not more. Single seed entry point + config snapshot recorded per cycle enables exact replay (FR-028/029, quickstart.md §6). |

**Result**: No violations. Complexity Tracking table is not needed (empty — no principle
deviations to justify).

*Post-Phase-1 re-check performed after data-model.md and contracts/ were written: the design
introduced no new dependencies, layers, or provider-specific logic beyond what's justified above.
All entities (data-model.md) and contracts carry the same guarantees analyzed in the table above.
**Result: still PASS, no changes.***

## Project Structure

### Documentation (this feature)

```text
specs/001-auto-research-pipeline/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── README.md
│   ├── architecture-boundaries.md
│   ├── data-connector.md
│   ├── thesis-schema.md
│   ├── critique-schema.md
│   ├── screening-contract.md
│   ├── backtest-contract.md
│   ├── evaluation-ledger-contract.md
│   └── report-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/energy_research/
├── config/               # pydantic-settings models + YAML loader; no deps on other layers
├── common/                # logging, seed management (common/seed.py), shared value types
├── ingestion/              # MarketDataConnector / QualitativeContextConnector protocols + registry
│   └── providers/          # concrete provider adapters, one module per provider_id
├── cleaning/               # normalization, quality checks, DataQualityRecord emission
├── datastore/               # SQLite models/repository (theses, lineages, ledger, results, cycles,
│                             # reports) + Parquet data-lake read/write; owns all split-scoping and
│                             # the EvaluationLedger's atomic spend operation
├── generation/              # LLMClient adapter + thesis-schema validation; reads datastore only
├── screening/               # statistical tests + multiplicity control; discovery-split only
├── backtesting/             # cost/slippage/financing-aware backtest engine; split-scoped
├── critique/                # critique generation + critique-schema validation
├── reporting/                # ResearchReport builder, reads only persisted datastore records
├── orchestration/            # the bounded research-cycle state machine; the only layer allowed
│                             # to import generation/screening/backtesting/critique/reporting
└── cli.py                   # `research-pipeline` entry points: ingest, run-cycle, replay

tests/
├── contract/
│   ├── test_architecture_boundaries.py   # import-linter contract check
│   ├── test_thesis_schema.py
│   ├── test_critique_schema.py
│   ├── test_evaluation_ledger.py         # atomicity / spend-once-per-lineage
│   └── test_multiplicity_control.py      # multiplicity control is mandatory, non-disableable
├── integration/
│   ├── test_research_cycle_end_to_end.py # synthetic labeled dataset, per quickstart.md §5
│   ├── test_provider_swap.py             # SC-010: zero downstream changes on provider swap
│   ├── test_data_quality_failloud.py     # SC-006: visible error + record, never silent
│   ├── test_synthetic_labeling.py        # FR-007: synthetic provenance survives to the report
│   ├── test_refinement_loop_bounds.py    # bounded critique-and-improve loop terminates
│   ├── test_report_transparency.py       # SC-008: code-free audit of a thesis's outcome
│   ├── test_reproducibility.py           # SC-009: replay reproduces the same shortlist
│   └── test_ledger_audit.py              # SC-005: final-evaluation spent at most once
└── unit/
    ├── ingestion/
    ├── cleaning/
    ├── screening/
    ├── backtesting/
    └── orchestration/

config/
├── default.yaml            # instrument universe, providers, thresholds, loop bounds (Principle VI)
└── providers.yaml           # provider registry + credential env-var references (no secrets)

pyproject.toml
uv.lock
```

**Structure Decision**: Single project (no frontend/backend split — this feature has no UI
surface). The `src/energy_research/` package mirrors the eight-layer dependency chain from the
Constitution Check table exactly one module per layer, with `orchestration` as the sole
integration point and `tests/contract/test_architecture_boundaries.py` mechanically enforcing that
`generation`, `screening`, `backtesting`, `critique`, and `reporting` never import one another
(contracts/architecture-boundaries.md). The Streamlit dashboard (out of scope here) will later
live as its own top-level package/feature reading from `src/energy_research/datastore`.

## Complexity Tracking

*No entries — Constitution Check reported no violations requiring justification.*
