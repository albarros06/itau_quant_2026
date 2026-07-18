# Research: Automated Trading-Idea Research Pipeline

**Input**: [spec.md](./spec.md) · **Constitution**: [.specify/memory/constitution.md](../../.specify/memory/constitution.md)

This document resolves the technical unknowns for the plan. Each entry: Decision, Rationale,
Alternatives considered.

## 1. Layered architecture & boundary enforcement

**Decision**: A strict, single-direction layered architecture with a "hub-and-spoke via datastore"
rule: the mid-tier analysis layers (`generation`, `screening`, `backtesting`, `critique`,
`reporting`) never import each other directly. Each depends only on `config`, `common`, and
`datastore`; they communicate exclusively by writing/reading persisted records. Only the
`orchestration` layer is allowed to import and sequence all of them. Layer boundaries are enforced
mechanically with **import-linter** (grimp-based dependency contracts checked in CI/tests), not
just by convention or code review.

Dependency order (low → high): `config` → `common` → `ingestion` → `cleaning` → `datastore` →
{`generation`, `screening`, `backtesting`, `critique`, `reporting`} (siblings, mutually
independent) → `orchestration`.

**Rationale**: The user explicitly asked for a strict layered architecture with clean boundaries.
Routing all cross-stage communication through `datastore` (rather than direct calls between
`generation`→`screening`→`backtesting`→`critique`) gives two things for free: (a) it makes the
train/refinement/final-evaluation split enforcement (Principle II, FR-014/FR-018) a property of
one shared component instead of something every stage must independently respect, and (b) it makes
every intermediate artifact (thesis draft, screening verdict, backtest result, critique) durable
and auditable by construction — directly serving FR-023–FR-026 and User Story 4. An automated,
CI-enforced contract (import-linter) turns "clean boundaries" from a documentation aspiration into
a build-breaking guarantee, which the constitution's Simplicity & Reproducibility principle favors
over relying on reviewer vigilance.

**Alternatives considered**:
- *Direct pipeline calls* (`generation` calls `screening` calls `backtesting`...): rejected —
  couples stages, makes split-boundary violations easy to introduce accidentally, and makes it
  harder to resume/retry a cycle mid-pipeline.
- *Message queue / event bus between stages*: rejected as unjustified complexity for a
  single-process batch pipeline (Principle VIII) — there is no concurrency or scale requirement
  that warrants it.
- *Boundary enforcement by convention/review only*: rejected — the constitution requires split
  integrity to be "enforced by shared code, not reimplemented per feature"; an unenforced
  convention is exactly the failure mode that produces silent data leakage.

## 2. Storage: relational ledger + columnar data lake

**Decision**: **SQLite** for all structured/relational state — data-quality records, theses,
lineages, the evaluation ledger, split allocations, screening/backtest results, critiques, cycles,
and reports. **Parquet** files (partitioned by data category / instrument / date) for the market
time-series data lake itself.

**Rationale**: The spent-once-per-lineage rule (FR-019) is a correctness-critical invariant that
must survive concurrent or interrupted runs. SQLite gives ACID transactions and a `UNIQUE`
constraint on the evaluation ledger's lineage key essentially for free, so "attempt to spend an
already-spent lineage" fails atomically at the database layer rather than relying on
application-level locking. It requires no server process, satisfying Principle VIII. Parquet is
the standard columnar format for time series, is efficient for the read patterns here (scan a
series over a date range), and carries a `provenance`/`is_synthetic` column naturally, supporting
Principle IV's labeling requirement end to end.

**Alternatives considered**:
- *A single SQL database for everything (including series data)*: rejected — long time series in
  a row store is a poor fit and adds no benefit here; a hybrid store is simpler in practice, not
  more complex, for this access pattern.
- *A server-based database (Postgres, etc.)*: rejected as unjustified operational overhead for a
  single-researcher batch pipeline — no concurrent-writer or networked-access requirement exists
  yet.
- *Flat CSV/JSON files for structured state*: rejected — no transactional guarantee, which is
  disqualifying for the spent-once ledger.

## 3. LLM integration for thesis generation & critique

**Decision**: Thesis generation and critique call the LLM through a thin `LLMClient` adapter
isolated inside the `generation` and `critique` layers. The LLM is required to return output
conforming to a fixed JSON Schema (via the provider's structured-output/tool-use mechanism); the
raw response is then independently re-validated against the same Pydantic model before anything
downstream sees it. Any response failing validation is rejected outright — logged as an invalid
generation attempt — never partially parsed or auto-repaired.

**Rationale**: This directly implements Constitution Principle III (Constrained LLM Autonomy) and
FR-010/FR-011: the LLM never produces code, is never executed, and its only channel to the rest of
the system is a schema-validated data record. Double validation (provider-side structured output +
independent Pydantic re-validation) means the system's safety property does not depend on trusting
the provider's enforcement alone.

**Alternatives considered**:
- *Free-form text completion parsed with regex/heuristics*: rejected outright — directly violates
  Principle III's schema-validated-only requirement.
- *Let the LLM call tools/functions that touch the datastore directly*: rejected — collapses the
  "LLM proposes, system disposes" boundary the constitution requires; the adapter must be a pure
  function (context in → structured thesis/critique out).

## 4. Statistical screening method & multiplicity control

**Decision**: Screening applies a configurable statistical test (default: a block-bootstrap
significance test on the thesis's hypothesized effect, robust to serial autocorrelation in
financial time series) evaluated on discovery-split data only. Because a run screens many
theses/lineages, verdicts are computed on **multiplicity-adjusted** significance (default:
Benjamini-Hochberg false-discovery-rate control across all theses screened in a cycle); an
unadjusted per-thesis p-value alone is never sufficient for a "pass" verdict. Both the base test
and the multiplicity method are configuration-selected, but the presence of *some* multiplicity
control is not optional (FR-030).

**Rationale**: Directly resolves the clarified FR-030/SC-011 requirement and Constitution
Principle II's "one-shot test discipline is the only defense against ... multiple-comparison
bias" — screening many candidate theses without multiplicity correction would silently promote
chance winners. Block bootstrap (vs. a naive t-test) is chosen as the sensible statistical default
for autocorrelated market data, but is swappable via config per Principle VI.

**Alternatives considered**:
- *Fixed per-thesis significance threshold with no multiplicity correction*: rejected — this is
  exactly the failure mode the clarification (Q4) ruled out.
- *Hardcoding a single specific statistical test with no configuration*: rejected — violates
  Configuration Over Hardcoding; different theses/hypotheses may warrant different tests.

## 5. Backtesting engine

**Decision**: Build a small, purpose-built vectorized backtest engine (pandas-based) rather than
adopt a general-purpose backtesting framework. The engine is parameterized by cost, slippage, and
financing/carry models (config-driven) and by which data split (`refinement` or
`final_evaluation`) it is allowed to read — enforced by only accepting data already filtered by
`datastore`'s split-scoped query methods, never a raw date range.

**Rationale**: The unusual constraint here — a backtest call must be structurally prevented from
seeing the final-evaluation split except in the single, ledger-gated, once-per-lineage call — is
not something general backtesting libraries model. Retrofitting that guarantee onto a third-party
engine's abstractions would add more integration complexity than writing a focused, auditable
engine (Principle VIII: avoid unjustified complexity, but also avoid the complexity of fighting a
framework's assumptions).

**Alternatives considered**:
- *vectorbt / backtrader / zipline*: rejected — powerful for general strategy backtesting, but the
  split-isolation and cost-honesty requirements (FR-017, FR-018, Principle IV) are the core
  business rules here, and none of these frameworks were designed to prevent a caller from feeding
  in the wrong data split. Bolting that on is more code than the custom engine needs.

## 6. Scheduling & orchestration trigger

**Decision**: No embedded scheduler process. Ingestion refresh and research-cycle triggering are
both exposed as CLI entry points, invoked on demand by a researcher or via an externally configured
scheduler (cron, CI scheduled job). The refresh interval and freshness tolerance are configuration
values, not code.

**Rationale**: FR-001/FR-006 require "continuous"/current data and a configurable freshness
tolerance, not an in-process scheduling daemon. An external scheduler triggering a stateless CLI
command is simpler to operate, test, and reason about than an embedded scheduler library, and adds
zero new runtime dependencies (Principle VIII).

**Alternatives considered**:
- *Embedded scheduler (APScheduler, Celery beat, etc.) running as a long-lived service*: rejected
  as unjustified complexity — there is no requirement for the pipeline itself to be a persistent
  service, and a long-lived process adds operational surface (crash recovery, state) the spec
  doesn't ask for.

## 7. Dependency & environment management

**Decision**: `pyproject.toml` with a committed lockfile (`uv.lock`), pinning all direct and
transitive dependencies. Python 3.11+.

**Rationale**: Constitution Principle VIII requires reproducibility "from configuration plus
pinned dependency versions ... alone." A lockfile is the mechanism that makes that guarantee real
rather than aspirational.

**Alternatives considered**:
- *Unpinned `requirements.txt`*: rejected — does not guarantee reproducibility across installs.

## 8. Determinism / seed management

**Decision**: A single `common.seed.set_seed(seed)` entry point invoked once at the start of every
research cycle, seeding all randomness sources used anywhere in the pipeline (bootstrap resampling,
any stochastic generation-adjacent logic). The seed is generated (or accepted from config) per
cycle and persisted on the `ResearchCycle` record alongside the full resolved configuration
snapshot.

**Rationale**: Directly implements FR-028/FR-029 and Principle VIII's determinism requirement, and
is what makes User Story 4's "re-run reproduces the same shortlist" acceptance scenario testable.

**Alternatives considered**:
- *Per-module ad hoc seeding*: rejected — fragments the determinism guarantee and makes it easy to
  miss a randomness source; a single seeding entry point is simpler and auditable.

## 9. Qualitative context ingestion (news, hydrology outlook, macro regime)

**Decision**: Qualitative context sources are modeled as a second connector family behind the same
common ingestion interface used for numeric market data (Principle I extended, not special-cased):
a `QualitativeContextConnector` protocol returns normalized context documents (source, timestamp,
category, text/summary, provenance) the same way a `MarketDataConnector` returns normalized series.
Both are provider-swappable through configuration.

**Rationale**: Keeps the "swap a provider without touching downstream logic" guarantee uniform
across numeric and qualitative data, rather than creating a second, bespoke integration pattern
for news/hydrology-outlook/macro-regime sources that would sit outside Principle I's protection.

**Alternatives considered**:
- *Ad hoc, provider-specific news/context fetching inside the `generation` layer*: rejected —
  directly violates Provider-Agnostic Data Ingestion; would hardcode a provider dependency into
  the layer that most needs to stay swappable and testable.
