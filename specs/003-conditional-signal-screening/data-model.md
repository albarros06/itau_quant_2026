# Phase 1 Data Model: Conditional-Signal Screening & Honest Multi-Leg Evaluation

All entities here are **additive** to 001's data model (data-model.md in
`specs/001-auto-research-pipeline/`). No existing column changes type or meaning; two new
optional structures appear inside existing extension points (`hypothesis` JSON,
`other_metrics` JSON), and one new JSON column is added to `screening_results`.

## SignalCondition (new — lives inside `TradingThesis.hypothesis`)

The structured, schema-validated replacement for the free-text `condition` field. Absent (`null`)
means unconditional (always in-market) — the pre-003 behavior.

| Field | Type | Notes |
|---|---|---|
| `clauses` | `list[ConditionClause]` | 1..`max_clauses` (config, default 3). Combined with all-of (AND) semantics. |

### ConditionClause

| Field | Type | Notes |
|---|---|---|
| `instrument_key` | `str` | MUST be in the configured instrument universe (validated identically to `hypothesis.instruments`). |
| `subject_transform` | `"level" \| "sma" \| "change"` | Transform applied to the instrument's series. |
| `subject_lookback` | `int \| null` | Required (`> 0`, `<= max_lookback_days`) for `sma`/`change`; MUST be null for `level`. |
| `comparator` | `"<" \| "<=" \| ">" \| ">="` | |
| `reference_kind` | `"constant" \| "sma" \| "rolling_quantile"` | What the subject is compared against. |
| `reference_value` | `float` | The constant, for `reference_kind="constant"`; unused otherwise. |
| `reference_lookback` | `int \| null` | Required (`> 0`, `<= max_lookback_days`) for `sma`/`rolling_quantile`; null for `constant`. |
| `reference_quantile` | `float \| null` | Required, `∈ [0, 1]`, only for `reference_kind="rolling_quantile"` (`0` = rolling minimum). Null otherwise. |

**Validation rules** (schema-level, `generation/schemas.py`):
- Exactly one of the lookback/quantile fields required per the `subject_transform` /
  `reference_kind` chosen; any other combination is schema-invalid (`extra`/`missing` style
  Pydantic error), not silently defaulted.
- `subject_lookback`/`reference_lookback` bounded by `conditional_screening.max_lookback_days`.
- `len(clauses) <= conditional_screening.max_clauses`.

## PositionSeries (ephemeral — never persisted)

The deterministic daily 0/1 exposure series produced by
`common.conditions.evaluate_condition(prices, condition)`, indexed identically to the
split-scoped price panel it was derived from. Reproducible at any time from
`(SignalCondition, split-scoped prices)` alone — persisting it would be redundant state
(Principle VIII) and would risk drifting from the condition that "really" produced a result.

- Index: same `DatetimeIndex` as the input `prices` panel (one split).
- Values: `0.0` or `1.0`. `NaN` clauses (insufficient warmup) resolve to `0.0` (out-of-market),
  never left as `NaN` in the final series.
- Already lag-shifted: value at day *t* reflects information available through day *t-1*
  (FR-004) — this series, unshifted again, is what gets multiplied into leg returns.

## ActivityStats (new — nested inside existing JSON extension columns)

Persisted per split, per evaluation (screening OR backtest), inside the existing/new
`other_metrics` JSON column (§ below) — not a new table, not new fixed columns.

| Key | Type | Meaning |
|---|---|---|
| `in_market_days` | `int` | Days the position was active (post-shift) within the split. |
| `total_days` | `int` | Total days in the split's price panel (after the leg-availability intersection `hypothesis_returns` already computes). |
| `entries` | `int` | Count of 0→1 transitions in the position series. |
| `exits` | `int` | Count of 1→0 transitions, plus 1 if still in-market at the split's last day (closing the position at split end, matching the existing "round trip" cost assumption). |

For an unconditional thesis: `in_market_days == total_days`, `entries == exits == 1` — identical
to the implicit accounting the pre-003 `CostModel` already assumed (FR-012).

## TurnoverCostBreakdown (extends `BacktestResult`'s existing fields — no new columns)

`CostBreakdown` (backtesting/costs.py) is unchanged in shape
(`transaction_costs`, `slippage`, `financing_carry`, `.total`); only the **inputs** to
`CostModel.compute` change, from `(n_legs, n_days)` to `(n_legs, entries, exits,
in_market_days)` (research.md §4). The persisted `BacktestResult` row's three cost columns and
`net_return` are unaffected in type/nullability — still `NOT NULL`, still rejected if non-finite
(existing guard, unchanged).

## Extended `TradingThesis.hypothesis` (JSON, no schema migration — same TEXT column)

```jsonc
{
  "instruments": ["BR_POWER_SE_SPOT", "BR_ENA_SE_MLT"],  // long/short: 1..N, equal-weighted;
                                                           // spread/relative_value: exactly 2
  "direction": "long",
  "horizon": "...",
  "condition": {                                          // NEW: null | SignalCondition
    "clauses": [
      {
        "instrument_key": "BR_ENA_SE_MLT",
        "subject_transform": "level",
        "subject_lookback": null,
        "comparator": "<",
        "reference_kind": "constant",
        "reference_value": 80.0,
        "reference_lookback": null,
        "reference_quantile": null
      }
    ]
  },
  "testable_claim": "..."
}
```

Persisted exactly as today (`trading_theses.hypothesis TEXT`, `json.dumps`/`json.loads` — see
`Repository.insert_thesis`/`get_thesis`); the free-text `condition: str` field this replaces is
removed from the schema (FR-001), not kept alongside it.

## `screening_results` table — one new column

```sql
ALTER TABLE screening_results ADD COLUMN other_metrics TEXT NOT NULL DEFAULT '{}';
```
Applied idempotently inside `create_schema` (guarded by `PRAGMA table_info` — research.md §5),
after the existing `CREATE TABLE IF NOT EXISTS screening_results (...)` statement, so both fresh
databases (created with the column already in the `CREATE TABLE`) and pre-003 databases (needing
the `ALTER`) converge to the same shape. Carries `ActivityStats` for the discovery-split
evaluation; empty object `{}` for any screening result predating this feature (read as "no
activity stats recorded", never misread as "zero active days").

`backtest_results.other_metrics` (already `TEXT NOT NULL DEFAULT '{}'`, already used for
`sharpe`/`max_drawdown`/etc.) gains the same four `ActivityStats` keys per row — no schema change
needed there at all.

## `ConditionalScreeningConfig` (new — nested under `PipelineConfig`)

| Field | Type | Default |
|---|---|---|
| `max_clauses` | `int` (`>= 1`) | `3` |
| `max_lookback_days` | `int` (`> 0`) | `90` |
| `min_active_days.discovery` | `int` (`>= 0`) | `100` |
| `min_active_days.refinement` | `int` (`>= 0`) | `60` |
| `min_active_days.final_evaluation` | `int` (`>= 0`) | `30` |

Serialized verbatim by `PipelineConfig.snapshot()` (already recursive over the whole model) into
every cycle's recorded `config_snapshot` — no extra code needed for FR-013's reproducibility
requirement.

## Report entry extensions (`research_reports.thesis_entries[]` — no schema change, same JSON list)

Each entry's existing `screening` and `refinement_backtests`/`final_evaluation` blocks gain:
- `condition_summary`: deterministic plain-language rendering of the clause list (e.g.
  `"active when BR_ENA_SE_MLT < 80.0"`), or `null` for unconditional theses (FR-010).
- `activity`: the `ActivityStats` dict, read straight from the corresponding `other_metrics`.
- `legs`: `[{"instrument_key": ..., "weight": 1/N}, ...]` for `long`/`short`;
  `[{"instrument_key": leg1, "weight": 1.0}, {"instrument_key": leg2, "weight": -1.0}]` for
  `spread`/`relative_value` (sign indicates the long/short side of the spread) — computed at
  render time from `hypothesis.instruments`/`direction`, not a new persisted field (FR-009/FR-010).
