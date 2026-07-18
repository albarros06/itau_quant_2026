# Contract: Screening Layer

Implements FR-013–FR-016, FR-030.

## Input

- One `TradingThesis` with `status = proposed` (schema already validated).
- A `DataSplitAllocation` reference with `split_type = discovery` — the layer receives data
  already scoped to discovery by `datastore`; it has no ability to request any other split.
- The cycle's configured statistical method + multiplicity method (from `config_snapshot`).
- The set of all theses being screened in this cycle (required input to compute the multiplicity
  adjustment — a per-thesis call cannot correctly adjust for multiplicity in isolation).

## Output

One `ScreeningResult` (see data-model.md) with:
- `verdict`: `pass` or `fail` — never any other value, never omitted.
- `reason`: specific and non-generic; MUST reference the statistic/threshold comparison that
  produced the verdict (FR-015, SC-002).
- `adjusted_threshold` and `multiplicity_method`: always populated, even when the method is
  configured to Bonferroni/BH/etc. with default parameters — there is no "unadjusted" output mode
  (FR-030).

## Contract rules

1. **Discovery-only**: this layer MUST NOT accept or read any data tagged `refinement` or
   `final_evaluation`. Enforced structurally: the only data-access path available to this layer's
   `datastore` client is the discovery-scoped query method.
2. **No thesis reaches `backtesting` without a `pass` verdict recorded here first** — this is a
   precondition `backtesting` MUST check (FR-013, SC-003).
3. **Multiplicity is mandatory, not optional** — a screening run over N theses must apply the
   family-level correction before emitting any `pass` verdicts; this cannot be configured off
   (FR-030, Clarification Q4).
