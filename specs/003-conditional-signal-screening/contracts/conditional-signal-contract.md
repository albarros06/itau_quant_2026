# Contract: Conditional-Signal Vocabulary & Evaluation

Extends [thesis-schema.md](../../001-auto-research-pipeline/contracts/thesis-schema.md) (the
`condition` field's shape) and
[screening-contract.md](../../001-auto-research-pipeline/contracts/screening-contract.md) (what
return stream gets tested). Implements FR-001 through FR-006, FR-011, FR-012.

## JSON Schema (the `condition` field of `HypothesisDraft`)

```json
{
  "condition": {
    "type": ["object", "null"],
    "required": ["clauses"],
    "additionalProperties": false,
    "properties": {
      "clauses": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": [
            "instrument_key", "subject_transform", "subject_lookback",
            "comparator", "reference_kind", "reference_value",
            "reference_lookback", "reference_quantile"
          ],
          "additionalProperties": false,
          "properties": {
            "instrument_key": { "type": "string" },
            "subject_transform": { "type": "string", "enum": ["level", "sma", "change"] },
            "subject_lookback": { "type": ["integer", "null"], "minimum": 1 },
            "comparator": { "type": "string", "enum": ["<", "<=", ">", ">="] },
            "reference_kind": { "type": "string", "enum": ["constant", "sma", "rolling_quantile"] },
            "reference_value": { "type": "number" },
            "reference_lookback": { "type": ["integer", "null"], "minimum": 1 },
            "reference_quantile": { "type": ["number", "null"], "minimum": 0, "maximum": 1 }
          }
        }
      }
    }
  }
}
```

`null` means unconditional. All fields are always present (Pydantic-required with explicit
`null`s for the inapplicable ones) rather than optional — a structured-output model is more
reliable emitting a fixed field set than reasoning about which fields to omit (matches
`common/llm.py`'s existing `_strip_unsupported` treatment of the rest of the thesis schema).

## Contract rules

1. **Closed vocabulary, no free text**: the pre-003 `condition: string` field is removed from the
   schema entirely, not kept as an alternative — a payload emitting free text where structured
   data is required fails Pydantic validation and is recorded `invalid_schema`, exactly like any
   other malformed draft (thesis-schema.md rule 2; Principle III). Prose reasoning belongs in
   `rationale`/`testable_claim`, unchanged.
2. **`instrument_key` universe check**: identical to thesis-schema.md rule 3 for
   `hypothesis.instruments` — a clause referencing an instrument outside the configured universe
   is a validation failure with a specific reason, applied per-clause.
3. **Field-combination validity per transform/reference**: `subject_transform="level"` requires
   `subject_lookback=null`; `"sma"`/`"change"` require `subject_lookback` set and
   `1 <= subject_lookback <= max_lookback_days`. `reference_kind="constant"` requires
   `reference_lookback=null, reference_quantile=null`; `"sma"` requires `reference_lookback` set
   (same bound), `reference_quantile=null`; `"rolling_quantile"` requires both
   `reference_lookback` and `reference_quantile` set (`0 <= reference_quantile <= 1`). Any other
   combination is a validation failure, never defaulted (Edge Case: inexpressible conditions).
4. **Clause count bound**: `1 <= len(clauses) <= max_clauses` (config,
   `conditional_screening.max_clauses`).
5. **Evaluation is a pure, shared, split-scoped function**: `common.conditions.evaluate_condition`
   takes only `(prices: pd.DataFrame, condition: SignalCondition | None)` where `prices` is
   already one split's data (as returned by `Repository.read_{discovery,refinement,
   final_evaluation}_data` — never a wider range); it performs no I/O, no randomness, and its
   output depends only on its inputs (research.md §2–3).
6. **Warmup is strictly in-split**: every rolling/diff/quantile computation draws only from the
   provided `prices` panel; the first `max(lookback)-1` rows of any clause are `NaN` (insufficient
   history) and resolve to inactive, never to observations from outside the split
   (Clarification 2026-07-21; no widening of the split-scoped read API).
7. **No lookahead**: the combined boolean condition is shifted forward exactly one day before
   being used as an exposure mask — a value observable at close of day *t* can influence exposure
   starting day *t+1* only (FR-004). This is verified mechanically (SC-003): shifting every input
   signal forward by one day must change the resulting position series.
8. **Multi-clause combination is all-of (AND)**: a condition is active on a day only if every
   clause resolves `True` (not `NaN`) that day.
9. **Screening tests the conditional return stream**: `ScreeningService` continues to call
   `common.signals.hypothesis_returns`, now passing the thesis's `condition` through; the
   block-bootstrap test (screening-contract.md, unchanged) runs on whatever stream that function
   returns — masked-conditional or unconditional, the statistical machinery does not know or care
   which (FR-005).
10. **Multiplicity family membership**: a thesis refused by the `min_active_days` gate
    ([turnover-cost-contract.md](./turnover-cost-contract.md) §activity gate is backtesting-side;
    the discovery-split gate lives here) never enters the wave's BH/Bonferroni family — no p-value
    exists for it (Clarification 2026-07-21). It is excluded from the family the same way an
    `invalid_schema` thesis already is (never screened at all).
11. **Under-observed conditions are refused, not tested**: before running the block-bootstrap
    test, `ScreeningService` checks the discovery-split `ActivityStats.in_market_days` against
    `conditional_screening.min_active_days.discovery`; below it, the thesis is rejected with a
    reason naming both counts and no `ScreeningResult` row is inserted for it (FR-006). The same
    gate, using `min_active_days.refinement`/`.final_evaluation`, applies before
    `BacktestingService.run_refinement`/`run_final_evaluation` compute costs.
