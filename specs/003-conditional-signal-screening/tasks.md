---

description: "Task list for Conditional-Signal Screening & Honest Multi-Leg Evaluation"
---

# Tasks: Conditional-Signal Screening & Honest Multi-Leg Evaluation

**Input**: Design documents from `/specs/003-conditional-signal-screening/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md,
data-model.md, contracts/, quickstart.md — all present.

**Tests**: Requested implicitly — plan.md's Testing subsection and quickstart.md name specific
test files as first-class deliverables (the mechanical enforcement of SC-001–SC-008), mirroring
001's own precedent of treating constitution-mandated guarantees as required test tasks, not
optional scaffolding.

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Single project (see plan.md Project Structure): `src/energy_research/`, `tests/`, `config/` at
repository root — this feature extends the existing package in place, no new top-level directory.

---

## Phase 1: Setup

**Purpose**: Confirm this feature needs no new scaffolding

- [X] T001 Confirm target locations already exist and no new dependency is required: `src/energy_research/common/`, `tests/unit/common/`, `tests/contract/`, `tests/unit/backtesting/`, `tests/unit/screening/`, `tests/integration/` all pre-exist (verified in plan.md's Structure Decision); no `pyproject.toml` change needed — `pandas`/`pydantic`/`numpy` already cover every primitive this feature uses (research.md Technical Context)

**Checkpoint**: Nothing to scaffold — proceed directly to Foundational.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared condition-evaluation engine, the extended return/cost seam, the schema
change, and the one required datastore migration — every user story depends on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 [P] `src/energy_research/common/conditions.py` — `SignalCondition`/`ConditionClause` pydantic models (data-model.md) and `evaluate_condition(prices, condition) -> pd.Series` (0/1 position mask; pandas rolling/diff/quantile for warmup-as-NaN; AND-combination with `NaN → False`; one forward shift for lookahead-freedom) per `contracts/conditional-signal-contract.md` rules 3, 5–8
- [X] T003 [P] `src/energy_research/config/settings.py` — add `ConditionalScreeningConfig` (`max_clauses`, `max_lookback_days`, `min_active_days.{discovery,refinement,final_evaluation}`) nested under `PipelineConfig`, defaults per data-model.md §`ConditionalScreeningConfig`
- [X] T004 `config/default.yaml` — add the `conditional_screening:` block with the Clarifications-session defaults (100/60/30, max_clauses 3, max_lookback_days 90) per quickstart.md §1 (depends on T003 — the key is schema-`extra="forbid"`-rejected until the model exists)
- [X] T005 [P] `src/energy_research/datastore/schema.py` — inside `create_schema`, after the existing `CREATE TABLE IF NOT EXISTS screening_results`, guard-and-run `ALTER TABLE screening_results ADD COLUMN other_metrics TEXT NOT NULL DEFAULT '{}'` via a `PRAGMA table_info` check — this codebase's first schema migration (research.md §5)
- [X] T006 `src/energy_research/datastore/repository.py` — `insert_screening_result()` accepts an optional `other_metrics: dict` param, persisted as JSON into the new column (depends on T005)
- [X] T007 `src/energy_research/common/signals.py` — extend `hypothesis_returns(prices, instruments, direction, condition=None)` to return `(returns: pd.Series, activity: ActivityStats)`: equal-weight `1/n` basket combination for `long`/`short` across all declared instruments (`multi-leg-evaluation-contract.md` rule 1; `n=1` reduces to the exact pre-003 formula), unchanged `leg1 - leg2` for `spread`/`relative_value`, with the condition mask (T002) multiplied into each leg's return series before combining (depends on T002)
- [X] T008 [P] `src/energy_research/backtesting/costs.py` — `CostModel.compute(n_legs, entries, exits, in_market_days, gross_exposure=1.0)`: `traded_notional = (entries + exits) * n_legs * gross_exposure` (replacing the hardcoded `2.0 *`), `financing_carry` computed over `in_market_days` (replacing `n_days`) per `contracts/turnover-cost-contract.md` rules 1–2
- [X] T009 `src/energy_research/generation/schemas.py` — `HypothesisDraft.condition: SignalCondition | None` (imports `common.conditions`); tighten `validate_draft`'s `spread`/`relative_value` check from "at least two" to "exactly two" instruments per `contracts/multi-leg-evaluation-contract.md` rule 2 (depends on T002)
- [X] T010 [P] `tests/contract/test_conditional_signal_schema.py` — mirrors `test_thesis_schema.py`: valid conditions accepted; each field-combination-validity rule (contracts rule 3) rejects malformed clauses; clause-count bound (rule 4) enforced; out-of-universe `instrument_key` rejected (mirrors thesis-schema.md rule 3); a free-text `condition` string is schema-invalid, not silently accepted (depends on T009)
- [X] T011 [P] `tests/unit/common/test_signals_conditions.py` — frozen pre-003 output fixture: `hypothesis_returns(..., condition=None)` byte-equal (`np.array_equal`) to the pre-change reference for every direction (SC-006); lookahead probe — an extreme return on the first decidable day never enters that day's masked return, and shifting all signals forward by one day changes the result (SC-003); warmup days resolve inactive, not `NaN`-as-active; multi-clause AND combination; multi-leg equal-weight basket math (`n=2` basket return equals the average of the two single-instrument returns) (depends on T007)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - A thesis's condition is actually tested (Priority: P1) 🎯 MVP

**Goal**: The LLM emits conditions in the closed vocabulary; screening evaluates the *conditional*
return stream (not a shared unconditional shortcut) with the existing block-bootstrap +
multiplicity machinery; two theses differing only in condition produce different, honest
statistics; the unconditional path is provably unchanged.

**Independent Test**: On the planted-signal fixture (instrument X's returns positive only when
signal S < SMA(S, 20)), a conditional thesis passes screening while the unconditional one fails;
inverting the condition flips the result (spec.md US1 Independent Test).

### Implementation for User Story 1

- [X] T012 [P] [US1] `src/energy_research/generation/llm_client.py` — `_SYSTEM` prompt gains the condition-vocabulary paragraph (subjects, transforms, references, comparators, `max_clauses`, `max_lookback_days`) alongside the existing `universe_keys` list (research.md §8)
- [X] T013 [P] [US1] `src/energy_research/critique/service.py` — critique prompt gains the same condition-vocabulary note so refinements can propose/adjust conditions
- [X] T014 [US1] `src/energy_research/screening/service.py` — pass `thesis["hypothesis"].get("condition")` through to `hypothesis_returns` (T007); persist the returned `ActivityStats` into the new `other_metrics` column via `insert_screening_result` (T006) (depends on T007, T006)
- [X] T015 [P] [US1] `src/energy_research/reporting/report_builder.py` — render `condition_summary`: deterministic plain-language rendering of the clause list (e.g. `"active when BR_ENA_SE_MLT < 80.0"`), or `null` for unconditional theses (data-model.md report entry extensions, FR-010)
- [X] T016 [P] [US1] `tests/integration/test_conditional_screening_end_to_end.py` — planted-signal fixture: the conditional thesis passes screening while the unconditional one fails; inverting the condition flips the result (SC-002); two theses differing only in condition produce differing screening statistics (SC-001) (depends on T014)
- [X] T017 [US1] `tests/integration/test_research_cycle_end_to_end.py` — extend: an unconditional thesis's screening statistics are byte-equal to the pre-003 recorded reference (SC-006) (depends on T014)

**Checkpoint**: User Story 1 is fully functional and independently testable (MVP) — conditions
differentiate screening outcomes; the unconditional path is provably unchanged.

---

## Phase 4: User Story 2 - Costs reflect real turnover (Priority: P2)

**Goal**: Transaction costs and slippage scale with realized entry/exit events per leg;
financing/carry accrues only on in-market days; an unconditional always-in strategy's costs are
numerically unchanged from pre-003.

**Independent Test**: Two fixture strategies with identical gross conditional returns but 2×
difference in entry/exit count show ~2× difference in persisted transaction+slippage; a strategy
in-market 50% of days accrues ~half the financing of an always-in one (spec.md US2 Independent
Test).

### Implementation for User Story 2

- [X] T018 [US2] `src/energy_research/backtesting/engine.py` — `run_backtest` now receives `ActivityStats` from the extended `hypothesis_returns` (T007) and calls `CostModel.compute` (T008) with `entries`/`exits`/`in_market_days`; persists `ActivityStats` into `BacktestComputation.other_metrics` alongside existing keys; the pre-existing non-finite guard (engine + datastore) is untouched (depends on T007, T008)
- [X] T019 [P] [US2] `tests/unit/backtesting/test_turnover_costs.py` — doubling a fixture's entries+exits doubles persisted transaction+slippage; halving in-market days halves financing (SC-004); the unconditional case (`entries=1, exits=1, in_market_days=total_days`) reproduces the exact pre-003 constants (SC-006) (depends on T008)
- [X] T020 [US2] `tests/unit/backtesting/test_costs_and_engine.py` — extend: recomputing `CostModel.compute` from a persisted result's `other_metrics` (entries/exits/in_market_days) reproduces the persisted `transaction_costs`/`slippage`/`financing_carry` exactly (SC-004) (depends on T018)

**Checkpoint**: User Story 1 and User Story 2 both work — conditional theses are screened AND
their backtests charge turnover-real costs.

---

## Phase 5: User Story 3 - A thesis trades exactly the legs it declares (Priority: P2)

**Goal**: Every instrument listed on a `long`/`short` thesis participates in its result at equal
weight; `spread`/`relative_value` stays exactly two legs; every report entry states the traded
weights, closing the standing gap where a report displayed untraded instruments.

**Independent Test**: A two-instrument long basket's returns equal the average of the two
single-instrument longs' returns (before costs); its report entry lists both legs at weight 0.5
each (spec.md US3 Independent Test).

### Implementation for User Story 3

- [X] T021 [US3] `src/energy_research/reporting/report_builder.py` — render `legs`: `[{"instrument_key", "weight"}]` — `1/n` each for `long`/`short`, `+1.0`/`-1.0` for the two `spread`/`relative_value` legs — computed at render time from `hypothesis.instruments`/`hypothesis.direction` (`contracts/multi-leg-evaluation-contract.md` rule 4) (depends on T015, same file)
- [X] T022 [P] [US3] `tests/integration/test_report_transparency.py` — extend: every report entry with a backtest lists every traded leg with its weight, and no entry lists an untraded instrument, checked mechanically over a full cycle's report (SC-005) (depends on T021)

**Checkpoint**: User Stories 1–3 all work independently — multi-leg baskets trade, and report,
exactly their declared legs.

---

## Phase 6: User Story 4 - Under-observed conditions are refused, and activity is visible (Priority: P3)

**Goal**: A condition active on too few days of a split is refused with a reason naming the
observed and required counts, before any statistic or cost is computed for it; it never enters
the wave's multiplicity family; every screened/backtested entry shows its activity stats.

**Independent Test**: A fixture condition active on fewer than the configured minimum days is
marked rejected with a reason naming both counts; no screening statistic is recorded for it
(spec.md US4 Independent Test).

### Implementation for User Story 4

- [X] T023 [US4] `src/energy_research/screening/service.py` — before running the block-bootstrap test, check `ActivityStats.in_market_days` (discovery split) against `conditional_screening.min_active_days.discovery`; below it, reject with a reason naming both counts, insert no `ScreeningResult`, and exclude the thesis from the wave's multiplicity family (`contracts/conditional-signal-contract.md` rules 10–11) (depends on T014)
- [X] T024 [P] [US4] `src/energy_research/backtesting/service.py` — analogous gates in `run_refinement`/`run_final_evaluation` against `min_active_days.refinement`/`.final_evaluation`; below threshold, reject with a reason naming both counts and persist no `BacktestResult` for that split (`contracts/turnover-cost-contract.md` rule 5) (depends on T018)
- [X] T025 [US4] `src/energy_research/reporting/report_builder.py` — render `activity`: `in_market_days`/`total_days`/`entries`/`exits` per split, alongside the existing cost breakdown (data-model.md report entry extensions) (depends on T021, same file)
- [X] T026 [P] [US4] `tests/unit/screening/test_methods_and_multiplicity.py` — extend: a thesis refused by the `min_active_days` gate is excluded from the BH/Bonferroni family size `m` — the family consists only of tests actually performed (Clarification 2026-07-21) (depends on T023)
- [X] T027 [P] [US4] `tests/integration/test_conditional_screening_end_to_end.py` — extend: a fixture condition active on fewer than `min_active_days` days is rejected with a reason naming the observed and required counts, no p-value recorded (SC-007); a condition that never becomes active (0 active days) hits the same refusal path with no divide-by-zero/NaN (depends on T023, T024)

**Checkpoint**: All four user stories independently functional — conditions are tested, honestly
costed, honestly reported, and guarded against small-sample abuse.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Verify the whole feature against the Constitution and against every pre-003
guarantee it must not have disturbed

- [X] T028 [P] Ruff lint pass across `src/energy_research/` and `tests/` for every file touched in Phases 2–6; fix violations
- [X] T029 Re-verify the Constitution Check table in `plan.md` against the implemented code (walk all 8 principles); record any drift
- [X] T030 [P] `tests/integration/test_reproducibility.py` — extend: a pre-003-recorded cycle (whose `config_snapshot` predates `conditional_screening`) replays to its recorded shortlist unchanged (SC-006, FR-012) (depends on T017, T020)
- [X] T031 Run `quickstart.md`'s end-to-end walkthrough against a real config (`uv run research-pipeline run-cycle`); confirm activity stats appear in a persisted `backtest_results.other_metrics` row and a `condition_summary`/`legs`/`activity`-populated entry appears in the rendered report (depends on all of Phases 3–6)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends only on Foundational. True MVP.
- **User Story 2 (Phase 4)**: Depends only on Foundational (`hypothesis_returns`'s `ActivityStats`,
  `CostModel`'s new signature) — genuinely independent of US1's screening/prompt work; touches
  `backtesting/` exclusively. Can proceed **in parallel** with US1 by a different developer.
- **User Story 3 (Phase 5)**: Depends on Foundational for the multi-leg return math (already
  correct once T007 lands) and on US1's `report_builder.py` `condition_summary` addition (T015)
  purely to avoid a same-file merge conflict — **build after US1** for that reason, not a deeper
  logical dependency.
- **User Story 4 (Phase 6)**: Extends US1's `screening/service.py` (T014) and US2's
  `backtesting/service.py`/`engine.py` (T018) directly, and shares `report_builder.py` with US3
  (T021). **Requires User Story 1 and User Story 2 complete**; for full report coverage, ideally
  after User Story 3 too.
- **Polish (Phase 7)**: Depends on all desired user stories being complete.

### User Story Dependencies (implementation, not just acceptance)

- **US1 (P1)**: No dependency on other stories. True MVP.
- **US2 (P2)**: No dependency on US1's screening/prompt files; shares only Phase 2 foundations.
  Independently buildable in parallel with US1.
- **US3 (P2)**: Logically independent of US1/US2 (multi-leg math is a Foundational property); build
  after US1 only to avoid both touching `report_builder.py` at once.
- **US4 (P3)**: Extends US1's and US2's files directly — build after both, and after US3 for
  complete report coverage.

### Within Each User Story

- Prompt/schema changes before service wiring.
- Service wiring before report rendering.
- Report rendering before the story's integration test.

---

## Parallel Example: Phase 2 (Foundational)

These Phase 2 tasks touch disjoint files and share no in-phase dependency, so they can run
together:

```bash
Task: "common/conditions.py — SignalCondition/ConditionClause + evaluate_condition() (T002)"
Task: "config/settings.py — ConditionalScreeningConfig (T003)"
Task: "datastore/schema.py — guarded ALTER TABLE screening_results (T005)"
Task: "backtesting/costs.py — turnover-aware CostModel.compute() (T008)"
```

`T004` (the `config/default.yaml` edit), `T006` (`repository.py`), `T007` (`common/signals.py`),
and `T009` (`generation/schemas.py`) each have an explicit same-phase dependency above and must
follow in order; `T010`/`T011` (contract/unit tests) follow once their respective dependencies
(`T009`/`T007`) land, and can then run together (different files).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (confirms no scaffolding needed).
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run the planted-signal fixture; confirm the conditional thesis passes
   screening while the unconditional one fails, and that inverting the condition flips the
   result (spec.md US1 Independent Test).
5. This alone fixes the defect the feature exists for — conditions stop being decorative.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add User Story 1 → validate independently → conditions are tested (MVP).
3. Add User Story 2 (can be built in parallel with US1 by a second developer) → validate
   independently → costs stop rewarding condition churn.
4. Add User Story 3 → validate independently → reports stop implying untraded exposure.
5. Add User Story 4 → validate independently → small-sample conditions can no longer pass by
   luck, and every entry shows the activity behind its numbers.

### Parallel Team Strategy

With two developers: both complete Setup + Foundational together; then Developer A takes User
Story 1, Developer B takes User Story 2 (genuinely independent — disjoint files, sharing only the
Phase 2 `common`/`backtesting.costs` foundations). User Story 3 is then sequenced after User
Story 1 (shared `report_builder.py` file, not a logical dependency), and User Story 4 after both
US1 and US2 land.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete same-phase task (or the task is a
  test whose only same-phase dependency is a wiring task that will already be complete by the
  time siblings run — matching 001's own tasks.md convention).
- [Story] label maps each task to its user story for traceability; Setup/Foundational/Polish tasks
  carry no story label by design.
- The contract test (T010) and the core evaluation unit test (T011) exist to make FR-002's
  vocabulary bounds and FR-004's lookahead-freedom build-breaking, not just documented — see
  plan.md's Constitution Check (Principles II, III).
- T004's ordering note (config edit after the settings model exists) is a real hazard, not
  pedantry: `PipelineConfig` uses `extra="forbid"`, so an unrecognized `conditional_screening:`
  key would break every config load, not just be ignored.
- Commit after each task or logical group.
- Stop at any checkpoint to validate a story independently before continuing.
- Avoid: cross-story dependencies beyond the documented shared-file (not logical) ordering between
  US1→US3 and US1/US2→US4.
