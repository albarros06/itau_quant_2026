---

description: "Task list for Automated Trading-Idea Research Pipeline"
---

# Tasks: Automated Trading-Idea Research Pipeline

**Input**: Design documents from `/specs/001-auto-research-pipeline/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md,
data-model.md, contracts/, quickstart.md — all present.

**Tests**: Not requested in the feature specification. The contract tests included below
(architecture boundaries, schema validation, multiplicity-control non-disableability,
evaluation-ledger atomicity) are not generic verification scaffolding — they are the mechanical
enforcement of Constitution-mandated guarantees that plan.md designated as first-class,
non-optional deliverables (the layered architecture's boundary contract, the LLM output schema
contract, the mandatory multiplicity control, and the spent-once-per-lineage guarantee). No other
test tasks are included.

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single project (see plan.md Project Structure): `src/energy_research/`, `tests/`, `config/` at
repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [ ] T001 Create project skeleton: `src/energy_research/{config,common,ingestion/providers,cleaning,datastore,generation,screening,backtesting,critique,reporting,orchestration}/__init__.py`, `src/energy_research/cli.py`, and `tests/{contract,integration,unit/{ingestion,cleaning,screening,backtesting,orchestration}}/__init__.py` per plan.md Project Structure
- [ ] T002 Initialize `pyproject.toml` (Python 3.11+, dependencies: pydantic, pandas, pyarrow, scipy, statsmodels, anthropic, import-linter, pytest) and generate `uv.lock`
- [ ] T003 Add import-linter layer-contract configuration to `pyproject.toml` implementing the layers/independence/forbidden-dependency contracts from `contracts/architecture-boundaries.md`
- [ ] T004 Add ruff lint/format configuration to `pyproject.toml`
- [ ] T005 [P] Create `config/default.yaml` and `config/providers.yaml` skeletons (placeholder values, no secrets) per `quickstart.md` §1

**Checkpoint**: Repository scaffolding and dependency/architecture tooling in place.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting infrastructure that every user story depends on: config schema,
determinism, the datastore (SQLite relational state + Parquet data lake), the evaluation ledger,
the connector protocol, and the thesis output schema — plus the contract tests that mechanically
enforce them from day one.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T006 `src/energy_research/config/settings.py` — pydantic-settings models for instrument universe, provider registry, data-quality freshness tolerance, screening method + multiplicity parameters, backtest cost/slippage/financing models, refinement-loop bounds, and seed (Constitution Principle VI)
- [ ] T007 [P] `src/energy_research/common/seed.py` — single `set_seed(seed)` entry point seeding every randomness source used anywhere in the pipeline (research.md §8)
- [ ] T008 [P] `src/energy_research/common/logging.py` — structured logging setup used for fail-loud warnings/errors (Constitution Principle VII)
- [ ] T009 `src/energy_research/datastore/schema.py` — SQLite table definitions for all data-model.md entities (DataSeries index, DataQualityRecord, ThesisLineage, EvaluationLedger, TradingThesis, DataSplitAllocation, ScreeningResult, BacktestResult, Critique, ResearchCycle, ResearchReport)
- [ ] T010 [P] `src/energy_research/datastore/repository.py` — split-scoped read/write methods (discovery/refinement/final_evaluation query scoping per `DataSplitAllocation`) plus `DataSeries`/`DataQualityRecord` persistence
- [ ] T011 [P] `src/energy_research/datastore/ledger.py` — `EvaluationLedger.spend()`/`status()` atomic operations implementing `contracts/evaluation-ledger-contract.md`
- [ ] T012 [P] `src/energy_research/datastore/lake.py` — Parquet data-lake read/write helpers keyed by category/instrument/date, carrying `provenance` and `freshness_ts`
- [ ] T013 [P] `src/energy_research/ingestion/connector.py` — `MarketDataConnector` and `QualitativeContextConnector` protocol definitions per `contracts/data-connector.md`
- [ ] T014 `src/energy_research/ingestion/registry.py` — config-keyed provider registry resolving `provider_id` → connector implementation (depends on T006, T013)
- [ ] T015 [P] `src/energy_research/generation/schemas.py` — `TradingThesisDraft` pydantic model matching `contracts/thesis-schema.md`'s JSON Schema
- [ ] T016 [P] `tests/contract/test_architecture_boundaries.py` — asserts the import-linter layer/independence/forbidden-dependency contracts (T003) hold
- [ ] T017 [P] `tests/contract/test_thesis_schema.py` — asserts `TradingThesisDraft` (T015) accepts valid drafts and rejects malformed or out-of-universe ones
- [ ] T018 [P] `tests/contract/test_evaluation_ledger.py` — asserts `EvaluationLedger.spend()` (T011) is atomic and enforces spend-once-per-lineage under repeat/concurrent attempts

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - Run an automated research cycle to a screened, backtested shortlist (Priority: P1) 🎯 MVP

**Goal**: From a labeled sample dataset, produce schema-validated theses, screen them on
discovery-only data with mandatory multiplicity control, backtest survivors with full cost
honesty, spend each lineage's one-time final-evaluation entitlement, and emit a complete report —
with zero manual steps between trigger and report. No refinement loop yet (that is User Story 3).

**Independent Test**: Run `research-pipeline run-cycle` against the sample dataset and verify
every acceptance scenario in spec.md User Story 1 (theses with rationale+hypothesis, a verdict+
reason for every thesis, screening-failed theses never backtested, net-of-cost backtest results,
a report explainable without reading code).

### Implementation for User Story 1

- [ ] T019 [P] [US1] `src/energy_research/ingestion/providers/sample_provider.py` — `MarketDataConnector` + `QualitativeContextConnector` implementation serving a clearly labeled synthetic sample dataset
- [ ] T020 [US1] `src/energy_research/cleaning/pipeline.py` — normalizes `sample_provider` output into `DataSeries` records with `provenance=synthetic` and stamped freshness (depends on T019, T010, T012)
- [ ] T021 [P] [US1] `src/energy_research/generation/llm_client.py` — `LLMClient` adapter: Anthropic structured-output call constrained to `TradingThesisDraft`, independently re-validated on response (Constitution Principle III)
- [ ] T022 [US1] `src/energy_research/generation/service.py` — assembles market + qualitative context from the datastore, calls `llm_client`, persists `TradingThesis` (schema-invalid drafts get `status=invalid_schema` and are excluded downstream) (depends on T021, T010)
- [ ] T023 [P] [US1] `src/energy_research/screening/methods.py` — block-bootstrap statistical test on discovery-split data (research.md §4)
- [ ] T024 [P] [US1] `src/energy_research/screening/multiplicity.py` — Benjamini-Hochberg multiplicity control applied across all theses screened in a cycle (FR-030)
- [ ] T025 [US1] `src/energy_research/screening/service.py` — discovery-split-only screening: applies method + multiplicity control, persists `ScreeningResult` with an explicit verdict and specific reason for every thesis (depends on T023, T024, T010)
- [ ] T026 [P] [US1] `tests/contract/test_multiplicity_control.py` — asserts the config schema (T006) rejects or ignores any attempt to disable multiplicity control, and that `screening/service.py` (T025) always applies an adjusted threshold, never an unadjusted per-thesis one (FR-030, SC-011) (depends on T006, T025)
- [ ] T027 [P] [US1] `src/energy_research/backtesting/costs.py` — transaction cost, slippage, and financing/carry models, parameterized by config
- [ ] T028 [US1] `src/energy_research/backtesting/engine.py` — vectorized backtest engine accepting only split-scoped data (refinement or final_evaluation), computing `net_return` from gross minus all three cost components (depends on T027, T010)
- [ ] T029 [US1] `src/energy_research/backtesting/service.py` — runs the refinement-split backtest for screening survivors; runs the final-evaluation backtest gated by `ledger.spend()` per `contracts/evaluation-ledger-contract.md` (depends on T028, T011)
- [ ] T030 [P] [US1] `src/energy_research/reporting/report_builder.py` — builds `ResearchReport` entries (rationale, hypothesis, screening verdict+reason, backtest results, final status) per `contracts/report-contract.md` (depends on T010)
- [ ] T031 [US1] `src/energy_research/orchestration/cycle.py` — single-pass cycle: freshness check → generation → screening → refinement-split backtest → final-evaluation backtest on the lineage → report; persists the cycle's `config_snapshot` and `seed` onto its `ResearchCycle` record (FR-029) so `replay` (T050) and reproducibility (T052) have something to reload (depends on T020, T022, T025, T029, T030)
- [ ] T032 [US1] `src/energy_research/cli.py` — add `run-cycle` command wiring `orchestration.cycle` with `--config` option (depends on T031)
- [ ] T033 [US1] `tests/integration/test_research_cycle_end_to_end.py` — drives `run-cycle` against `sample_provider`'s labeled dataset; asserts spec.md User Story 1 Acceptance Scenarios 1–5 (depends on T032)

**Checkpoint**: User Story 1 is fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - Continuous, provider-agnostic data ingestion and quality assurance (Priority: P1)

**Goal**: Real (non-sample) provider connectors, full data-quality detection with fail-loud
recording, freshness-tolerance enforcement, and proof that swapping a provider requires zero
downstream code changes.

**Independent Test**: Run `research-pipeline ingest` against a configured provider; verify the
dataset is cleaned, quality-checked, and marked current. Inject a gap/outlier/stale feed and
verify a visible error/warning plus a recorded `DataQualityRecord` — never silent interpolation.

### Implementation for User Story 2

- [ ] T034 [P] [US2] `src/energy_research/cleaning/quality_checks.py` — gap/outlier/stale-feed/schema-mismatch detection producing `DataQualityRecord` entries (depends on T010)
- [ ] T035 [US2] `src/energy_research/cleaning/pipeline.py` — integrate `quality_checks` into the cleaning pipeline: raise a visible warning/error on any issue and record every automated correction/gap-fill/fallback; never silently interpolate (depends on T034, T020)
- [ ] T036 [P] [US2] `src/energy_research/datastore/repository.py` — add freshness-tolerance enforcement: refuse to start a cycle when any required series' `freshness_ts` is stale beyond the configured tolerance, with a stated reason (depends on T010, T006)
- [ ] T037 [P] [US2] `src/energy_research/ingestion/providers/secondary_market_provider.py` — a second concrete `MarketDataConnector` implementation, config-selectable (concrete provider identity is a config-time decision, not fixed here) (depends on T013)
- [ ] T038 [P] [US2] `src/energy_research/ingestion/providers/qualitative_context_provider.py` — a concrete `QualitativeContextConnector` implementation for news/hydrology-outlook/macro-regime context (concrete provider identity is a config-time decision, not fixed here) (depends on T013)
- [ ] T039 [US2] `src/energy_research/cli.py` — add `ingest` command wiring ingestion + cleaning for all configured providers (depends on T035, T037, T038)
- [ ] T040 [P] [US2] `tests/integration/test_provider_swap.py` — swap the configured `MarketDataConnector` provider in config and confirm ingestion and a full cycle succeed with zero changes to cleaning/datastore/analysis code (SC-010) (depends on T039)
- [ ] T041 [P] [US2] `tests/integration/test_data_quality_failloud.py` — inject a gap, an outlier, and a stale feed; assert each raises a visible warning/error and produces a `DataQualityRecord`, with no silent interpolation (SC-006) (depends on T035, T036)
- [ ] T042 [P] [US2] `tests/integration/test_synthetic_labeling.py` — verifies that `provenance=synthetic` set during cleaning (T020) is clearly labeled end to end into the `ResearchReport` (T030) and CLI output, with no path by which a synthetic result could be mistaken for real (FR-007, spec.md User Story 2 Acceptance Scenario 5) (depends on T035, T030)

**Checkpoint**: User Story 1 and User Story 2 both work independently.

---

## Phase 5: User Story 3 - Bounded iterative critique-and-improve (Priority: P2)

**Goal**: Automatically critique rejected/underperforming theses and use the critique to generate
improved or alternative variants within the same lineage, bounded by a per-lineage refinement-depth
cap and a per-run lineage/iteration cap.

**Independent Test**: Force a rejected/underperforming thesis, set small caps, run the loop, and
verify a specific critique is produced, an improved variant is generated from it, and the loop
terminates at the configured limit.

### Implementation for User Story 3

- [ ] T043 [P] [US3] `src/energy_research/critique/schemas.py` — `ThesisCritique` pydantic model matching `contracts/critique-schema.md`
- [ ] T044 [P] [US3] `tests/contract/test_critique_schema.py` — asserts `ThesisCritique` (T043) accepts valid critiques and rejects malformed or overly generic ones, mirroring `test_thesis_schema.py` (T017) (depends on T043)
- [ ] T045 [US3] `src/energy_research/critique/service.py` — LLM call constrained to `ThesisCritique` (reusing `llm_client` from T021), independently re-validated, persisted and attached to the critiqued thesis (depends on T043, T021, T010)
- [ ] T046 [US3] `src/energy_research/generation/service.py` — extend to accept a `Critique` as input context and produce a new thesis variant in the same lineage (`parent_thesis_id` set, `iteration_index` incremented) (depends on T022, T045)
- [ ] T047 [US3] `src/energy_research/orchestration/cycle.py` — extend to a bounded loop: on rejection/underperformance, invoke critique → generation → screening → refinement backtest, tracking the per-lineage refinement-depth cap and the per-run lineage/iteration cap, terminating at whichever is hit first (depends on T031, T046)
- [ ] T048 [US3] `tests/integration/test_refinement_loop_bounds.py` — force a rejected/underperforming thesis with small caps; assert a critique with specific weaknesses is produced, an improved variant is generated from it, and the loop terminates at the configured limit (spec.md User Story 3 Acceptance Scenarios 1–3) (depends on T047)

**Checkpoint**: All user stories independently functional.

---

## Phase 6: User Story 4 - Transparent audit of every thesis decision (Priority: P3)

**Goal**: Every thesis from every iteration is traceable end to end from the report artifact
alone; a completed cycle is exactly reproducible from its recorded configuration and seed; the
spend-once-per-lineage guarantee is independently auditable.

**Independent Test**: From a completed cycle's artifacts alone (no code), trace one promoted and
one rejected thesis end to end; replay the cycle from its recorded config+seed and confirm the
shortlist reproduces; confirm a lineage's final-evaluation period was spent at most once.

### Implementation for User Story 4

- [ ] T049 [P] [US4] `src/energy_research/reporting/report_builder.py` — extend to include every thesis from every iteration/lineage of a cycle, including refused final-evaluation attempts, rendered in a human-readable structured format (depends on T030, T047)
- [ ] T050 [P] [US4] `src/energy_research/cli.py` — add `replay` command: reload a `ResearchCycle`'s `config_snapshot` + `seed` (persisted by T031) and re-execute (depends on T031, T006)
- [ ] T051 [P] [US4] `tests/integration/test_report_transparency.py` — from a completed cycle's report artifact alone, trace one promoted and one rejected thesis end to end: rationale → evidence → verdict → performance (spec.md User Story 4 Acceptance Scenario 1, SC-008) (depends on T049)
- [ ] T052 [P] [US4] `tests/integration/test_reproducibility.py` — replay a completed cycle and assert the shortlist and verdicts reproduce exactly (spec.md User Story 4 Acceptance Scenario 2, SC-009) (depends on T050)
- [ ] T053 [P] [US4] `tests/integration/test_ledger_audit.py` — for any thesis, confirm via `ledger.status()` that its lineage's final-evaluation period was consumed at most once (spec.md User Story 4 Acceptance Scenario 3, SC-005) (depends on T011, T047)

**Checkpoint**: All user stories independently functional and fully auditable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T054 [P] `README.md` — architecture overview, layer diagram, pointer to `specs/001-auto-research-pipeline/quickstart.md`
- [ ] T055 [P] Ruff lint pass across `src/energy_research/` and `tests/`; fix violations
- [ ] T056 Re-verify the Constitution Check table in `plan.md` against the implemented code (walk all 8 principles); record any drift
- [ ] T057 [P] `tests/unit/{ingestion,cleaning,screening,backtesting,orchestration}/` — unit-test coverage pass for logic not already exercised by contract/integration tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories.
- **User Story 1 (Phase 3)** and **User Story 2 (Phase 4)**: Both depend only on Foundational.
  They touch disjoint files (US1: generation/screening/backtesting/reporting/orchestration
  services; US2: cleaning/quality_checks, additional providers, freshness enforcement) and can
  proceed **in parallel** by different developers.
- **User Story 3 (Phase 5)**: Extends `orchestration/cycle.py` and `generation/service.py`, both
  created in Phase 3. **Requires User Story 1 complete first** — this is an implementation
  dependency, not just a foundational one (the spec's own priority note: US3 "builds on US1").
- **User Story 4 (Phase 6)**: Extends `reporting/report_builder.py` (Phase 3) and reads
  loop-produced state (Phase 5) for full "all iterations" coverage. **Requires User Story 1
  complete**; the loop-audit scenarios (T053) additionally require **User Story 3 complete**.
- **Polish (Phase 7)**: Depends on all desired user stories being complete.

### User Story Dependencies (implementation, not just acceptance)

- **US1 (P1)**: No dependency on other stories. True MVP.
- **US2 (P1)**: No dependency on US1's analysis services; only shares Phase 2 datastore/ingestion
  foundations. Independently buildable in parallel with US1.
- **US3 (P2)**: Extends US1's files — build after US1.
- **US4 (P3)**: Extends US1's (and, for full coverage, US3's) files — build after US1 (and
  ideally after US3).

### Within Each User Story

- Models/schemas before services.
- Services before orchestration wiring.
- Orchestration before CLI wiring.
- CLI wiring before the story's integration test.

---

## Parallel Example: Phase 3 (User Story 1)

After Phase 2 (Foundational) is complete, these Phase 3 tasks touch disjoint files and share no
in-phase dependency, so they can run together:

```bash
Task: "ingestion/providers/sample_provider.py — sample dataset connector (T019)"
Task: "generation/llm_client.py — Anthropic structured-output adapter (T021)"
Task: "screening/methods.py — block-bootstrap test (T023)"
Task: "screening/multiplicity.py — Benjamini-Hochberg control (T024)"
Task: "backtesting/costs.py — cost/slippage/financing models (T027)"
Task: "reporting/report_builder.py — report entry builder (T030)"
```

Everything else in Phase 3 (T020, T022, T025, T026, T028, T029, T031–T033) has an in-phase
dependency and must follow in order (T026, the multiplicity non-disableability test, specifically
requires T025 to be done first).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `research-pipeline run-cycle` against the sample dataset; confirm
   every US1 acceptance scenario.
5. This is a demonstrable, working research assistant even before real data or the refinement
   loop exist.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add User Story 1 → validate independently → MVP.
3. Add User Story 2 (can be built in parallel with US1 by a second developer) → validate
   independently → the dataset behind US1 can now be real, provider-swappable data.
4. Add User Story 3 → validate independently → the shortlist gets better through self-critique.
5. Add User Story 4 → validate independently → results become fully auditable and reproducible by
   a reviewer who didn't run the cycle.

### Parallel Team Strategy

With two developers: both complete Setup + Foundational together; then Developer A takes User
Story 1, Developer B takes User Story 2 (genuinely independent — disjoint files, shared only
through the Phase 2 datastore/ingestion interfaces). User Story 3 and 4 are then sequenced after
User Story 1 lands, since they extend its files directly.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task in the same phase.
- [Story] label maps each task to its user story for traceability; Setup/Foundational/Polish tasks
  carry no story label by design.
- Contract tests (T016–T018, T026, T044) exist to make the constitution's boundary/schema/
  multiplicity/spent-once guarantees build-breaking, not just documented — see plan.md's
  Constitution Check. T042 (synthetic-labeling) closes the same gap for Principle IV's
  synthetic-data-labeling guarantee at the integration level.
- `secondary_market_provider.py` (T037) and `qualitative_context_provider.py` (T038) are
  intentionally generic names — the concrete vendor is a configuration decision (Principle VI),
  not fixed at planning time.
- Commit after each task or logical group.
- Stop at any checkpoint to validate a story independently before continuing.
- Avoid: cross-story dependencies that break independent testability beyond the documented
  US1→US3 and US1→US4 extension relationships.
