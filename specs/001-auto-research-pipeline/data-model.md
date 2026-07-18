# Data Model: Automated Trading-Idea Research Pipeline

Derived from [spec.md](./spec.md) Key Entities, refined per [Clarifications](./spec.md#clarifications)
and [research.md](./research.md) decisions (SQLite for structured entities, Parquet for series data).

## Entity Overview

```text
ResearchCycle ─┬─< TradingThesis >─┬─ ScreeningResult
               │                    ├─ BacktestResult
               │                    └─ Critique
               └─ ResearchReport

ThesisLineage ─< TradingThesis (lineage_id FK)
              └─ EvaluationLedger (1:1, spent-once gate)

DataSeries ── DataQualityRecord (0..N per series/ingestion event)
DataSplitAllocation ── scoped to a ThesisLineage + split_type
```

## Entities

### DataSeries
A time-ordered set of values for one market data category from one provider.

| Field | Type | Notes |
|---|---|---|
| series_id | string (PK) | stable identity: category + instrument_key + provider |
| category | enum | spot, forward_curve, hydrology, interest_rate, fx, ... (config-defined universe) |
| instrument_key | string | config-defined instrument/tenor identifier |
| provider_id | string | which configured connector produced this |
| provenance | enum | `real` \| `synthetic` — MUST be set, never inferred (Principle IV) |
| freshness_ts | timestamp | as-of time of the most recent observation |
| ingested_at | timestamp | when this record was written |
| storage_ref | string | pointer into the Parquet data lake (path/partition) |
| quality_status | enum | `clean`, `flagged`, `stale` |

**Rules**: `provenance = synthetic` MUST propagate to every downstream artifact (thesis,
backtest result, report) that touches this series (FR-007). A series with
`freshness_ts` older than the configured tolerance is `stale` and MUST NOT be used to start a
research cycle (FR-006, Edge Case: stale data).

### DataQualityRecord
A recorded data-quality issue or automated intervention.

| Field | Type | Notes |
|---|---|---|
| record_id | string (PK) | |
| series_id | string (FK) | |
| detected_at | timestamp | |
| issue_type | enum | `gap`, `outlier`, `stale_feed`, `schema_mismatch`, `misconfiguration` |
| intervention | enum | `none_raised`, `gap_fill`, `correction`, `fallback`, `rejected` |
| detail | text | human-readable specifics of what was found/done and why |

**Rules**: Created for every detected issue, whether or not an automated correction was applied
(FR-004, FR-005). Never deleted; `intervention = none_raised` records issues surfaced without a
fix, satisfying "raise, don't silently degrade."

### ThesisLineage
A thesis and all improved/alternative variants derived from it through refinement; the unit at
which the final-evaluation entitlement is spent (Clarification Q1).

| Field | Type | Notes |
|---|---|---|
| lineage_id | string (PK) | |
| cycle_id | string (FK) | originating ResearchCycle |
| root_thesis_id | string (FK) | first thesis in the lineage |
| refinement_depth | int | count of improvement attempts so far, ≤ configured per-lineage cap (FR-022a) |

### EvaluationLedger
The transactional gate enforcing "final-evaluation period spent at most once per lineage"
(FR-019). One row per lineage, created at lineage creation with `spent = false`.

| Field | Type | Notes |
|---|---|---|
| lineage_id | string (PK, FK, UNIQUE) | one-to-one with ThesisLineage |
| spent | bool | default `false` |
| spent_by_thesis_id | string, nullable | which variant consumed the entitlement |
| spent_at | timestamp, nullable | |

**Rules**: Spending is an atomic transaction: `UPDATE ... SET spent=true, spent_by_thesis_id=?,
spent_at=? WHERE lineage_id=? AND spent=false`, checked against rows-affected = 1. A second attempt
(rows-affected = 0) MUST be treated as a refusal and produce a `DataQualityRecord`-style refusal
log (Edge Case: attempt to reuse a spent evaluation period), never a silent no-op.

### TradingThesis
A candidate idea.

| Field | Type | Notes |
|---|---|---|
| thesis_id | string (PK) | |
| lineage_id | string (FK) | |
| parent_thesis_id | string, nullable (FK, self) | null for a lineage's root thesis |
| cycle_id | string (FK) | |
| iteration_index | int | which refinement iteration produced this variant (0 = initial) |
| rationale | text | plain-language, required (FR-009) |
| hypothesis | structured (JSON) | instrument(s)/direction/horizon/condition — schema-validated (FR-010) |
| status | enum | see State Transitions below |
| created_at | timestamp | |

**Validation**: `hypothesis` MUST validate against the thesis JSON Schema (see
[contracts/thesis-schema.md](./contracts/thesis-schema.md)); a thesis failing validation is
persisted with `status = invalid_schema` and excluded from all further processing (FR-011).

**State transitions**:

```text
proposed ──(schema invalid)──> invalid_schema [terminal]
proposed ──(screening: fail)──> screened_rejected [terminal]
proposed ──(screening: pass)──> screened_passed
screened_passed ──(refinement backtest)──> backtested
backtested ──(underperforms threshold)──> rejected_underperform [terminal, may spawn critique → new thesis in same lineage]
backtested ──(selected as lineage's best variant, loop ended)──> final_evaluation_pending
final_evaluation_pending ──(ledger spend succeeds, result clears bar)──> promoted [terminal]
final_evaluation_pending ──(ledger spend succeeds, result misses bar)──> rejected_after_final [terminal]
final_evaluation_pending ──(ledger already spent)──> refused [terminal, logged refusal]
```

### DataSplitAllocation
The discovery / refinement / final-evaluation partitioning applied within a cycle.

| Field | Type | Notes |
|---|---|---|
| allocation_id | string (PK) | |
| cycle_id | string (FK) | |
| split_type | enum | `discovery`, `refinement`, `final_evaluation` |
| date_range_start / end | date | |
| instrument_scope | string | config-defined universe reference |

**Rules**: Screening queries MUST be scoped to `discovery` only (FR-014); refinement-loop backtests
MUST be scoped to `refinement` only; the single per-lineage final run MUST be scoped to
`final_evaluation` only (FR-018). This scoping is enforced by `datastore` query methods, not by
caller discipline (research.md §1).

### ScreeningResult
Evidence and verdict for a thesis, computed on discovery data only.

| Field | Type | Notes |
|---|---|---|
| result_id | string (PK) | |
| thesis_id | string (FK) | |
| method | string | statistical test used (config-selected) |
| statistic_value | float | |
| multiplicity_method | string | e.g. `benjamini_hochberg` (FR-030) |
| adjusted_threshold | float | the multiplicity-corrected bar actually applied |
| verdict | enum | `pass`, `fail` |
| reason | text | specific, human-readable (FR-015) |
| evaluated_at | timestamp | |

### BacktestResult
Realistic performance for a thesis on a given split.

| Field | Type | Notes |
|---|---|---|
| result_id | string (PK) | |
| thesis_id | string (FK) | |
| split_type | enum | `refinement` \| `final_evaluation` |
| gross_return | float | |
| transaction_costs | float | required, non-null (FR-017) |
| slippage | float | required, non-null |
| financing_carry | float | required, non-null |
| net_return | float | = gross_return − costs − slippage − financing_carry |
| other_metrics | JSON | sharpe, drawdown, etc. (config-defined set) |
| evaluated_at | timestamp | |

**Rules**: A `BacktestResult` missing any of `transaction_costs`/`slippage`/`financing_carry` is
invalid and MUST NOT be persisted or reported (Principle IV, FR-017, SC-004).

### Critique
Assessment of a rejected or underperforming thesis.

| Field | Type | Notes |
|---|---|---|
| critique_id | string (PK) | |
| thesis_id | string (FK) | the thesis being critiqued |
| weaknesses | text/list | specific, not generic |
| suggested_direction | text | informs the next generation call |
| created_at | timestamp | |
| feeds_iteration_index | int | which next iteration consumes this |

### ResearchCycle
One end-to-end run.

| Field | Type | Notes |
|---|---|---|
| cycle_id | string (PK) | |
| started_at / completed_at | timestamp | |
| config_snapshot | JSON | full resolved configuration used (FR-029) |
| seed | int | (FR-028) |
| max_refinement_depth | int | per-lineage cap (Clarification Q3) |
| max_lineages_or_iterations | int | per-run cap (Clarification Q3) |
| status | enum | `running`, `completed`, `failed` |

### ResearchReport
The end-of-cycle artifact.

| Field | Type | Notes |
|---|---|---|
| report_id | string (PK) | |
| cycle_id | string (FK) | |
| generated_at | timestamp | |
| thesis_entries | JSON/list | one entry per thesis across ALL iterations (FR-026): rationale, hypothesis, screening verdict+reason, backtest result (if any), final status |

**Rules**: MUST include every thesis regardless of outcome (FR-023), MUST include net-of-cost
performance for every promoted thesis (FR-024), and MUST be renderable/readable without inspecting
source code (FR-025).

## Cross-Entity Invariants

1. **Split isolation**: No `ScreeningResult` may reference `refinement`/`final_evaluation` data;
   no refinement-loop `BacktestResult` may reference `final_evaluation` data (FR-018).
2. **Spend-once**: For any `ThesisLineage`, at most one `BacktestResult` with
   `split_type=final_evaluation` may exist, and it must correspond to the `EvaluationLedger` row's
   `spent_by_thesis_id` (FR-019).
3. **No silent drops**: Every `TradingThesis` not reaching `promoted` MUST have either a
   `ScreeningResult` with `verdict=fail` and a reason, or a terminal status with a recorded reason
   (SC-002).
4. **Reproducibility**: Given the same `ResearchCycle.config_snapshot` + `seed`, replaying
   ingestion-through-report MUST yield identical `TradingThesis`/`ScreeningResult`/`BacktestResult`
   sets (FR-028, SC-009).
