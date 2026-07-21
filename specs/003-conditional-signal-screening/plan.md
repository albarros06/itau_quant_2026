# Implementation Plan: Conditional-Signal Screening & Honest Multi-Leg Evaluation

**Branch**: `003-conditional-signal-screening` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-conditional-signal-screening/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See
`.specify/templates/plan-template.md` for the execution workflow.

## Summary

Make a thesis's stated `condition` machine-executable instead of decorative free text. A new
shared, pure function (`common.conditions.evaluate_condition`) turns a closed,
schema-validated condition vocabulary into a deterministic, lookahead-free daily position mask
over one split's data; `common.signals.hypothesis_returns` — already the single seam both
`screening` and `backtesting` call — is extended to multiply that mask into an
equal-weight, multi-leg return stream (fixing, in the same seam, the standing defect where
`long`/`short` theses silently traded only `instruments[0]`). Screening block-bootstraps the
*conditional* return stream under the existing multiplicity machinery; the cost model becomes
turnover-aware (entries/exits/in-market-days replace the pre-003 fixed "2 trades, full window"
assumption); an under-observation gate refuses conditions active on too few days, per split. Every
new behavior is additive and regression-locked: `condition=null` and single-instrument
`long`/`short` reproduce pre-003 numbers exactly (FR-012), and the one schema change
(`screening_results.other_metrics`) is an idempotent `ALTER TABLE ADD COLUMN`, this codebase's
first, deliberately minimal migration. See [research.md](./research.md) for the decisions behind
each design choice.

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from 001/002)

**Primary Dependencies**: No new dependencies. `pandas` (already a dependency) provides the
rolling/shift/quantile primitives `common.conditions.evaluate_condition` needs; `pydantic`
(already a dependency) validates the new `SignalCondition`/`ConditionClause` models exactly as it
validates the rest of `HypothesisDraft`; `numpy` (already a dependency, via `screening/methods.py`)
is unaffected — the block-bootstrap test itself does not change, only the array it receives.

**Storage**: SQLite (unchanged). One additive, idempotent schema change: `screening_results` gains
`other_metrics TEXT NOT NULL DEFAULT '{}'` (mirroring the column `backtest_results` already has),
applied via a guarded `ALTER TABLE ... ADD COLUMN` inside `create_schema` — this codebase's first
schema migration of any kind (research.md §5). No change to the Parquet lake or any other table.

**Testing**: `pytest`, extending the existing suite in place. New: `tests/unit/common/
test_signals_conditions.py` (condition evaluation, lookahead, warmup, multi-leg basket
math — including a frozen pre-003 regression fixture for SC-006), `tests/unit/backtesting/
test_turnover_costs.py` (entry/exit cost scaling, SC-004), a `tests/contract/
test_conditional_signal_schema.py` (vocabulary validation rules, mirroring
`test_thesis_schema.py`'s style), and one new `tests/integration/
test_conditional_screening_end_to_end.py` (planted-signal fixture, SC-001/SC-002, mirroring
`test_research_cycle_end_to_end.py`'s synthetic-dataset pattern). Existing tests in
`tests/unit/screening/`, `tests/unit/backtesting/test_costs_and_engine.py`,
`tests/integration/test_research_cycle_end_to_end.py`, and `tests/integration/
test_refinement_loop_bounds.py` are extended, not replaced, with unconditional-path assertions
proving byte-equality to their pre-003 behavior.

**Target Platform**: Linux server or local developer machine, same CLI-invoked batch model as
001 (`research-pipeline run-cycle`). No new entry point.

**Project Type**: Single project — an in-place extension of the existing `energy_research`
package (no new top-level package, unlike 002's `ops_agent` or the dashboard's `dashboard/`).
One new module (`common/conditions.py`); the rest is targeted changes to existing files.

**Performance Goals**: Not latency-critical, same batch-research workload as 001. Condition
evaluation is vectorized pandas over split-scoped panels already sized for the existing
`.pct_change()` call in `hypothesis_returns` — no new performance-sensitive path is introduced.

**Constraints**: The structural split-scoping guarantee (001's `Repository.read_{discovery,
refinement,final_evaluation}_data` as the only price-read paths) MUST remain the only place price
data crosses into `screening`/`backtesting` — condition evaluation reads from the same
already-scoped panel, never a wider one (Clarification 2026-07-21, contracts rule 6). The one
schema migration MUST be idempotent and MUST NOT require any out-of-band operational step (it
runs inside `create_schema`, which every code path already calls before using the database).

**Scale/Scope**: Same instrument universe and refinement-loop bounds as 001/002 (now 14 series
across four ONS submarkets, per the real-data-provider work). Condition clauses are bounded at
1..3 by default (config); this is a per-thesis constant-factor addition to existing computation,
not a new scaling dimension — screening/backtesting still process one thesis's return stream per
call, just a potentially-masked one.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Provider-Agnostic Data Ingestion | **N/A** | This feature touches no connector or provider code; conditions reference already-ingested universe instruments only (contracts rule 2, mirroring thesis-schema.md rule 3). |
| II. Statistical Rigor Before Backtesting | **PASS** | Condition evaluation reads exclusively from the split-scoped panel already handed to `screening`/`backtesting` (no widening of the read API, Clarification 2026-07-21); the block-bootstrap test and multiplicity control are unchanged code paths, now fed a conditional return stream (research.md §2, contracts rule 9). The under-observation gate (FR-006) is itself a rigor mechanism — a condition too thin to test honestly is refused, not tested. |
| III. Constrained LLM Autonomy | **PASS** | The condition vocabulary is a closed, Pydantic-validated schema (data-model.md `SignalCondition`) reaching the LLM via the same `model_json_schema()` structured-output path `TradingThesisDraft` already uses; anything outside the vocabulary is a validation failure, recorded `invalid_schema`, never repaired (conditional-signal-contract.md rule 1). No executable code or free-form expression is ever accepted as a condition. |
| IV. Backtest Honesty | **PASS** | Costs scale with realized entries/exits/in-market-days instead of a fixed assumption (turnover-cost-contract.md) — closer to true cost, never further from it. Multi-leg theses now trade every declared instrument (multi-leg-evaluation-contract.md), closing a standing violation where a report displayed untraded instruments. Net-of-cost reporting, synthetic labeling, and the non-finite persistence guard are all untouched and apply identically to conditional results. |
| V. Mobile-First, Fully Responsive UI | **N/A (deferred)** | No UI work in this plan; the dashboard consuming the new report fields (`condition_summary`, `activity`, `legs`) is explicitly out of scope (spec Assumptions) and will be its own change, subject to this gate then. |
| VI. Configuration Over Hardcoding | **PASS** | `max_clauses`, `max_lookback_days`, and per-split `min_active_days` are a new `ConditionalScreeningConfig` section (data-model.md §7), not hardcoded constants; all recorded in the cycle's `config_snapshot` automatically (`PipelineConfig.snapshot()` already recurses the whole model). |
| VII. Fail-Loud Observability | **PASS** | Under-observed conditions are refused with a reason naming both the observed and required counts (FR-006, SC-007) — never silently tested on a handful of days. Schema-invalid conditions follow the existing loud `invalid_schema` path. The pre-existing non-finite backtest guard is explicitly unaffected by this feature (turnover-cost-contract.md rule 6), not bypassable via a condition. |
| VIII. Simplicity & Reproducibility | **PASS** | One shared evaluation function reused by both `screening` and `backtesting` (research.md §1–2), not two parallel implementations. No parameter search/sweep over condition thresholds (spec Assumptions) — the multiplicity-controlled refinement loop remains the only variation mechanism, unchanged. The one schema migration is a single guarded `ALTER TABLE`, deliberately not a migrations framework, introduced only because this feature is the first to need it (research.md §5). Regression-locked to pre-003 behavior via a frozen fixture (research.md §9, SC-006), so reproducibility of every existing recorded cycle is unaffected. |

**Result**: No violations. Complexity Tracking table is not needed (empty — no principle
deviations to justify).

*Post-Phase-1 re-check performed after data-model.md and contracts/ were written: no new
dependency, no new top-level layer, and no provider-specific logic was introduced beyond what's
justified above. The one schema change (`screening_results.other_metrics`) is additive and
idempotent, consistent with Principle VIII's "only in response to a demonstrated, present need"
— the need being ActivityStats' persistence, already justified under Principle VII.
**Result: still PASS, no changes.***

*Post-implementation re-check (all 31 tasks complete; full suite green — T029): walked all 8
principles against the actual code, not just the design.*

| Principle | Status | Verified against implementation |
|---|---|---|
| I. Provider-Agnostic Data Ingestion | **N/A** | No connector/provider code touched; conditions reference universe instruments only, validated per-clause in `generation/schemas.py::validate_draft`. |
| II. Statistical Rigor Before Backtesting | **PASS** | `common.conditions.evaluate_condition` reads only the split-scoped panel `screening`/`backtesting` already hold; the block-bootstrap + multiplicity code is unchanged, now fed the conditional stream. The `min_active_days` gate excludes under-observed conditions from the family (`test_conditional_screening_end_to_end.py`, `test_methods_and_multiplicity.py::TestFamilyExcludesRefusals`). |
| III. Constrained LLM Autonomy | **PASS** | `SignalCondition`/`ConditionClause` are `extra="forbid"` Pydantic models reaching the LLM via `TradingThesisDraft.model_json_schema()`; free text is `invalid_schema` (`test_conditional_signal_schema.py::test_free_text_condition_is_schema_invalid`). No executable condition is ever accepted. |
| IV. Backtest Honesty | **PASS** | Costs scale with realized `entries`/`exits`/`in_market_days` (`test_turnover_costs.py`), recoverable from persisted `other_metrics` (`test_costs_and_engine.py::test_costs_recoverable_from_persisted_activity`); multi-leg baskets trade every declared instrument at `1/n` and the report lists exactly those legs (`test_report_transparency.py::test_every_entry_trades_exactly_its_declared_legs`). The non-finite guard is untouched. |
| V. Mobile-First, Fully Responsive UI | **N/A (deferred)** | No UI; new report fields (`condition_summary`, `legs`, `activity`) are JSON + Markdown only. |
| VI. Configuration Over Hardcoding | **PASS** | `ConditionalScreeningConfig` (`extra="forbid"`) holds `max_clauses`/`max_lookback_days`/per-split `min_active_days`; recorded verbatim in `config_snapshot`. |
| VII. Fail-Loud Observability | **PASS** | Under-observed conditions are refused with a reason naming both counts and no `ScreeningResult`/`BacktestResult` row (`test_conditional_screening_end_to_end.py`); a 0-active-days condition hits the same path with no NaN. |
| VIII. Simplicity & Reproducibility | **PASS** | One shared `hypothesis_returns`/`evaluate_condition` seam, not two. The one migration is a single guarded `ALTER TABLE`. `condition=None` + `n=1` is byte-equal to pre-003 (`test_signals_conditions.py::TestUnconditionalRegression`), and a pre-003 snapshot without the new section still replays (`test_reproducibility.py::test_pre003_snapshot_without_conditional_screening_still_replays`). |

**Result: PASS, no drift.** No Complexity Tracking entry needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-conditional-signal-screening/
├── plan.md                              # This file (/speckit-plan command output)
├── research.md                          # Phase 0 output (/speckit-plan command)
├── data-model.md                        # Phase 1 output (/speckit-plan command)
├── quickstart.md                        # Phase 1 output (/speckit-plan command)
├── contracts/                           # Phase 1 output (/speckit-plan command)
│   ├── README.md
│   ├── conditional-signal-contract.md
│   ├── turnover-cost-contract.md
│   └── multi-leg-evaluation-contract.md
└── tasks.md                             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

This feature extends the existing `energy_research` package in place — no new top-level
directory. Files with **(NEW)** are added; all others are targeted extensions of existing files.

```text
src/energy_research/
├── common/
│   ├── conditions.py                    # (NEW) SignalCondition/ConditionClause models +
│   │                                     #       evaluate_condition() — the shared, pure,
│   │                                     #       lookahead-free evaluator (research.md §1, §3)
│   └── signals.py                       # hypothesis_returns() extended: optional condition
│                                         #  param; equal-weight multi-leg basket for long/short
│                                         #  (research.md §2, contracts/multi-leg-evaluation-
│                                         #  contract.md); returns ActivityStats alongside the
│                                         #  return series
├── config/
│   └── settings.py                      # + ConditionalScreeningConfig (data-model.md §7)
├── generation/
│   ├── schemas.py                       # HypothesisDraft.condition: SignalCondition | None;
│   │                                     #  tightened spread/relative_value == 2 check
│   │                                     #  (multi-leg-evaluation-contract.md rule 2)
│   └── llm_client.py                    # _SYSTEM prompt gains the condition-vocabulary
│                                         #  paragraph (research.md §8)
├── critique/
│   └── service.py                       # critique prompt gains the same vocabulary note
├── screening/
│   └── service.py                       # passes hypothesis.condition through; applies the
│                                         #  min_active_days.discovery gate before testing
│                                         #  (conditional-signal-contract.md rule 11)
├── backtesting/
│   ├── costs.py                         # CostModel.compute(n_legs, entries, exits,
│   │                                     #  in_market_days, gross_exposure) — turnover-cost-
│   │                                     #  contract.md
│   ├── engine.py                        # run_backtest() passes condition through, persists
│   │                                     #  ActivityStats into other_metrics; existing
│   │                                     #  non-finite guard unchanged
│   └── service.py                       # applies min_active_days.refinement/.final_evaluation
│                                         #  gates before computing costs
├── datastore/
│   ├── schema.py                        # + guarded ALTER TABLE screening_results ADD COLUMN
│   │                                     #  other_metrics (research.md §5, data-model.md)
│   └── repository.py                    # insert_screening_result() accepts other_metrics
└── reporting/
    └── report_builder.py                # entries gain condition_summary / activity / legs
                                          #  (data-model.md, report entry extensions)

tests/
├── contract/
│   └── test_conditional_signal_schema.py  # vocabulary validation rules (mirrors
│                                           #  test_thesis_schema.py)
├── unit/
│   ├── common/
│   │   └── test_signals_conditions.py     # evaluate_condition + hypothesis_returns:
│   │                                       #  lookahead (SC-003), warmup, multi-clause AND,
│   │                                       #  multi-leg basket math, frozen pre-003 regression
│   │                                       #  fixture (SC-006)
│   ├── backtesting/
│   │   ├── test_costs_and_engine.py       # extended: turnover-scaled cost assertions (SC-004)
│   │   └── test_turnover_costs.py         # (NEW) entry/exit/in-market-day cost math in isolation
│   └── screening/
│       └── test_methods_and_multiplicity.py  # extended: family excludes inactivity refusals
└── integration/
    ├── test_conditional_screening_end_to_end.py  # (NEW) planted-signal fixture: conditional
    │                                              #  passes / unconditional fails and vice versa
    │                                              #  (SC-001, SC-002); one report entry checked
    │                                              #  for legs/activity completeness (SC-005)
    ├── test_research_cycle_end_to_end.py         # extended: unconditional path byte-equal to
    │                                              #  pre-003 (SC-006)
    └── test_reproducibility.py                   # extended: a pre-003 recorded cycle still
                                                    #  replays to its recorded shortlist
```

**Structure Decision**: In-place extension of the single existing `energy_research` project
(same choice 001 made and 002/the dashboard preserved for their own new top-level directories).
No new package boundary is needed here — condition evaluation is layered exactly like the
existing `hypothesis_returns` it extends, so it belongs in `common`, reused by `screening` and
`backtesting` under the same import-linter layers contract already in force (no changes needed
to `pyproject.toml`'s `[tool.importlinter]` section).

## Complexity Tracking

*No entries — the Constitution Check above recorded no violations to justify.*
