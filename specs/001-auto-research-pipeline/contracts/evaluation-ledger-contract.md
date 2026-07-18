# Contract: Evaluation Ledger (Spent-Once-Per-Lineage)

Implements FR-019 and the Clarification Q1/Q2 decisions. This is the single choke point through
which the final-evaluation split may ever be touched.

## Operation: `spend(lineage_id, thesis_id) -> SpendOutcome`

**Precondition**: an `EvaluationLedger` row exists for `lineage_id` (created alongside the
`ThesisLineage`, `spent = false`).

**Behavior**: executes, in one atomic transaction:

```sql
UPDATE evaluation_ledger
SET spent = true, spent_by_thesis_id = :thesis_id, spent_at = :now
WHERE lineage_id = :lineage_id AND spent = false;
```

- If rows affected = 1 → `SpendOutcome.GRANTED`. Caller may now run the `final_evaluation`-scoped
  backtest for `thesis_id`.
- If rows affected = 0 → `SpendOutcome.REFUSED`. Caller MUST NOT run any final-evaluation backtest
  and MUST record the refusal (who attempted, when, against which already-spent lineage) rather
  than silently doing nothing.

## Operation: `status(lineage_id) -> LedgerStatus`

Read-only; used by reporting/audit (User Story 4, spec Acceptance Scenario US4.3) to show whether
and by which thesis a lineage's entitlement was spent.

## Contract rules

1. **No caller-side check-then-act.** Callers MUST use `spend()`'s atomic result, never a
   separate `status()` read followed by a conditional call — that pattern is racy and defeats the
   guarantee.
2. **One ledger row per lineage, never per thesis** — this is what makes the spend-once-per-
   **lineage** (not per-variant) semantics from Clarification Q1 hold.
3. **Only `backtesting` calls `spend()`**, and only immediately before running the
   `final_evaluation`-scoped backtest (Clarification Q2: the final period is touched exactly once,
   at the end of refinement, on the single best variant) — `orchestration` decides *when* a
   lineage is ready for final evaluation and *which* variant is best, but the atomic spend itself
   lives in `backtesting`/`datastore`.
