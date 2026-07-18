# Quickstart: Automated Trading-Idea Research Pipeline

This describes how the pipeline is operated once implemented (`/speckit-tasks` +
`/speckit-implement`). It is the reference for User Story 1's independent test and for
`tests/integration/`.

## 1. Configure

All market-, provider-, and threshold-specific values live in config — nothing here is
hardcoded (Principle VI). A minimal config sketch:

```yaml
# config/default.yaml
providers:
  market_data:
    - provider_id: sample_provider
      categories: [spot, forward_curve, hydrology, interest_rate, fx]
  qualitative_context:
    - provider_id: sample_news_provider
      categories: [news, hydrology_outlook, macro_regime]

instrument_universe:
  - key: <config-defined instrument/tenor>

data_quality:
  freshness_tolerance: <config-defined duration>

screening:
  method: block_bootstrap
  multiplicity_method: benjamini_hochberg
  alpha: <config-defined>

backtesting:
  transaction_cost_model: <config-defined>
  slippage_model: <config-defined>
  financing_model: <config-defined>

refinement:
  max_refinement_depth_per_lineage: <config-defined>
  max_lineages_per_run: <config-defined>

reproducibility:
  seed: <config-defined, or omit to auto-generate and record>
```

## 2. Ingest data

```bash
research-pipeline ingest --config config/default.yaml
```

Fetches and cleans all configured categories through the connector interface, writes to the
Parquet data lake, records freshness/provenance, and raises visibly on any data-quality issue
(never silently interpolates).

## 3. Run a research cycle

```bash
research-pipeline run-cycle --config config/default.yaml
```

End-to-end, no manual steps between trigger and report (User Story 1):
1. Refuses to start if required data is stale beyond tolerance (surfaces why).
2. Generates candidate theses (schema-validated LLM output) grounded in current
   data + qualitative context.
3. Screens each on discovery-split data only, with mandatory multiplicity control; records a
   verdict + reason for every thesis.
4. Backtests screening survivors on refinement-split data (realistic costs/slippage/financing).
5. Critiques rejected/underperforming theses and generates improved variants, bounded by the
   configured per-lineage and per-run limits.
6. For each lineage's best variant, spends its one-time final-evaluation entitlement and runs the
   final backtest.
7. Writes a `ResearchReport` covering every thesis tried across every iteration.

## 4. Inspect the report

The report is a self-contained artifact (per
[contracts/report-contract.md](./contracts/report-contract.md)) — every thesis, its verdict/reason,
and net-of-cost performance for anything promoted, readable without opening any source file
(User Story 4).

## 5. Verifying User Story 1 independently

Before continuous ingestion (User Story 2) is implemented, point `run-cycle` at a clearly labeled
sample dataset (`provenance: synthetic` throughout) to exercise generation → screening →
backtesting → report end to end. Every artifact produced from this dataset carries the synthetic
label (Principle IV) — it is never presented as if it were a real result.

## 6. Reproducing a run

```bash
research-pipeline replay --cycle-id <id>
```

Reads the persisted `config_snapshot` + `seed` from the named `ResearchCycle` and re-executes,
expected to reproduce the same shortlist and verdicts (FR-028, SC-009).
