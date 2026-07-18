# Contract: Research Report Artifact

Implements FR-023–FR-026, SC-002, SC-008.

## Required content

For **every** `TradingThesis` created during the cycle (all iterations, not just the final one —
FR-026), the report MUST include an entry with:

| Field | Required | Source |
|---|---|---|
| rationale, hypothesis | always | `TradingThesis` |
| lineage id + iteration index | always | `TradingThesis`, `ThesisLineage` |
| screening verdict + reason | always, unless thesis failed schema validation (then: that reason) | `ScreeningResult` |
| refinement backtest result(s), net of costs | if screening passed | `BacktestResult` (split=refinement) |
| final-evaluation result, net of costs | only for the one lineage-best variant that was evaluated | `BacktestResult` (split=final_evaluation) |
| final status + specific reason | always | `TradingThesis.status` |

## Contract rules

1. **Completeness**: a thesis with no entry in the report is a contract violation — this is the
   mechanical check behind SC-002 ("100% of theses that do not advance carry a specific, recorded
   rejection reason").
2. **No gross-only performance**: any final-evaluation or refinement performance figure shown MUST
   include the cost breakdown, never net-only or gross-only without the components (Principle IV).
3. **Readable without code**: the report is a self-contained human-readable artifact (e.g.
   structured document/table); a reviewer must be able to answer "why was thesis X rejected /
   promoted?" from the report alone (FR-025, SC-008). This is a `reporting`-layer responsibility,
   built only from persisted `datastore` records — `reporting` never re-derives verdicts by
   recomputing statistics.
4. **Synthetic labeling carries through**: if any input series behind a thesis was `synthetic`
   provenance, the report entry MUST surface that label (Principle IV) — never presented
   indistinguishably from a real-data result.
