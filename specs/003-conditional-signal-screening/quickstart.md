# Quickstart: Conditional-Signal Screening & Honest Multi-Leg Evaluation

This describes how conditional theses work once implemented — the reference for User Story 1's
independent test and for `tests/unit/common/test_signals_conditions.py`.

## 1. Configure

Add the new section to `config/default.yaml` (Principle VI — no code change needed to adjust
these bounds):

```yaml
conditional_screening:
  max_clauses: 3
  max_lookback_days: 90
  min_active_days:
    discovery: 100
    refinement: 60
    final_evaluation: 30
```

These defaults are the Clarifications-session values; omitting the section entirely falls back
to these same defaults (backward compatible with every pre-003 config on disk).

## 2. A conditional thesis, end to end

A generation payload with a condition (schema per
[contracts/conditional-signal-contract.md](./contracts/conditional-signal-contract.md)):

```json
{
  "rationale": "SE/CO inflows have been running persistently below their long-term mean; when they are this depressed, spot prices historically drift up as thermal dispatch increases.",
  "hypothesis": {
    "instruments": ["BR_POWER_SE_SPOT"],
    "direction": "long",
    "horizon": "refinement_window",
    "condition": {
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
    "testable_claim": "Mean daily long return of BR_POWER_SE_SPOT is positive and statistically distinguishable from zero on days SE/CO inflows run below 80% of their long-term mean."
  }
}
```

What happens to it:
1. `generate_initial`/`generate_refinement` persists this as today, with `hypothesis.condition`
   stored as-is (JSON, same `hypothesis` column).
2. `ScreeningService.screen_cycle` calls `hypothesis_returns(discovery_prices, ["BR_POWER_SE_SPOT"],
   "long", condition)` → a return series that is zero on every day `BR_ENA_SE_MLT`'s prior-day
   level was `>= 80.0`, and the SE spot's actual return on every day it was `< 80.0` (one-day
   lag applied automatically). If fewer than `min_active_days.discovery` (100) days are active,
   the thesis is rejected with a reason naming the observed count — no block-bootstrap test runs.
   Otherwise, the (conditional) return series is block-bootstrapped exactly as any unconditional
   thesis's would be.
3. If it screens `pass`, `BacktestingService.run_refinement` runs the same masked-return
   computation on the refinement split, this time also computing `ActivityStats` and feeding
   `entries`/`exits`/`in_market_days` into `CostModel.compute` — costs reflect only the days and
   transitions actually taken.
4. The report entry shows: `condition_summary: "active when BR_ENA_SE_MLT < 80.0"`,
   `activity: {in_market_days: ..., total_days: ..., entries: ..., exits: ...}`, and
   `legs: [{"instrument_key": "BR_POWER_SE_SPOT", "weight": 1.0}]`.

## 3. Verify the unconditional path is unchanged

```bash
uv run pytest tests/unit/common/test_signals_conditions.py -k unconditional_regression -q
```

This is the SC-006 gate: `condition=None` (or an all-clauses-trivially-true condition covering
100% of days) must reproduce pre-003 numbers exactly, for both `hypothesis_returns` output and
the resulting cost breakdown.

## 4. Verify the lookahead guarantee

```bash
uv run pytest tests/unit/common/test_signals_conditions.py -k lookahead -q
```

Plants a single extreme return on the first day a condition becomes decidable and asserts it
never enters that day's masked return (SC-003).

## 5. Run a real cycle and inspect activity stats

```bash
uv run research-pipeline --config config/default.yaml run-cycle
```

Then inspect a thesis's persisted activity:

```python
from energy_research.datastore.repository import Repository
repo = Repository("data/research.sqlite", "data/lake")
result = repo.backtest_results_for("<thesis_id>", split_type="refinement")[0]
print(result["other_metrics"])  # {"sharpe": ..., "in_market_days": ..., "entries": ..., ...}
```
