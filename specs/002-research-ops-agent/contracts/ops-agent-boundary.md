# Contract: Operations Agent Reach Boundary

Implements FR-019 ("the agent's permitted surface MUST be structurally limited") and the Edge
Case "Attempt to exceed reach must be structurally impossible, not merely prohibited by
instruction."

## Allowlist: what `ops_agent` may import from `energy_research`

```text
energy_research.config.settings           # load_config, PipelineConfig (read + trigger reload)
energy_research.orchestration.ingest       # ingest_all(config) — the ONLY ingestion entry point
energy_research.orchestration.cycle        # run_cycle(config), replay_cycle(config, cycle_id)
energy_research.datastore.repository       # Repository — READ-ONLY methods only (report lookup,
                                            #   cycle history, freshness checks already exposed
                                            #   for CLI use); no write method may be called
energy_research.common.logging             # shared logger setup, for consistent log format only
energy_research.common.llm                 # shared structured-output transport (StructuredRequest
                                            #   -> validated JSON payload) — the same transport
                                            #   generation/critique use; ops_agent supplies its own
                                            #   task name + JSON schema (discovery interpretation,
                                            #   proposal/onboarding drafting), never a thesis or
                                            #   critique schema, and never imports generation/critique
                                            #   themselves to get it (research.md §5)
```

## Denylist: no code path may exist to

```text
energy_research.generation      # thesis authorship
energy_research.screening       # statistical tests, multiplicity control
energy_research.backtesting     # backtest engine
energy_research.critique        # critique generation
energy_research.reporting       # report construction
energy_research.datastore.ledger  # EvaluationLedger — the spend-once write API
energy_research.datastore.repository.Repository.<any write method>
```

## Contract rules

1. **One-directional dependency.** `ops_agent` may import from `energy_research`; `energy_research`
   MUST NEVER import from `ops_agent`. Enforced by an import-linter `independence` contract in
   `pyproject.toml` alongside 001's existing layered-architecture contract.
2. **Allowlist is exhaustive, not illustrative.** A contract test statically enumerates every
   `energy_research.*` symbol imported anywhere under `src/ops_agent/` and asserts each import
   path is a prefix of an allowlist entry above. A new import outside the allowlist fails the
   test, not just a future code review.
3. **No mechanism to write theses, verdicts, results, ledger state, or reports.** This is a
   corollary of rule 2: none of `generation`/`screening`/`backtesting`/`critique`/`reporting`/
   `datastore.ledger` is importable, so no such write is reachable from any `ops_agent` code path
   (spec Acceptance Scenario US3.4).
4. **Cycle triggering is opaque.** `ops_agent` calls `run_cycle`/`replay_cycle` and reads the
   returned `CycleResult`; it passes no thesis, verdict, or override into the call and receives
   no hook to alter what happens inside it (FR-010).
5. **Configuration influence is file-level, not API-level.** `ops_agent` never calls a mutating
   method on `PipelineConfig`; its only channel into pipeline behavior is writing YAML files that
   `load_config` reads fresh on the next `ingest`/`run_cycle` invocation (proposal-lifecycle.md).
6. **Swapping/removal test.** Deleting `src/ops_agent/` entirely MUST leave `energy_research`
   fully functional via its own CLI (`research-pipeline ingest|run-cycle|replay`), with zero
   code changes required — proving the dependency is genuinely one-directional.
