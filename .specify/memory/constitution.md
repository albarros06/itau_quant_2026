<!--
SYNC IMPACT REPORT
==================
Version change: (template / unversioned) → 1.0.0
Bump rationale: Initial ratification. First concrete constitution replacing the
  unfilled template; MAJOR baseline established per semantic-versioning policy.

Modified principles: N/A (initial adoption)
Added principles:
  I.   Provider-Agnostic Data Ingestion
  II.  Statistical Rigor Before Backtesting
  III. Constrained LLM Autonomy
  IV.  Backtest Honesty
  V.   Mobile-First, Fully Responsive UI
  VI.  Configuration Over Hardcoding
  VII. Fail-Loud Observability
  VIII.Simplicity & Reproducibility
Added sections:
  - Core Principles (8 principles)
  - Engineering Constraints & Standards
  - Development Workflow & Quality Gates
  - Governance
Removed sections: None

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate is generic;
     no principle names hardcoded, remains compatible.
  ✅ .specify/templates/spec-template.md — no constitution-specific content to change.
  ✅ .specify/templates/tasks-template.md — task categories cover observability,
     config, and testing discipline; compatible as-is.
  ✅ .claude/skills/speckit-*/SKILL.md — generic references only; no updates needed.

Deferred TODOs: None. RATIFICATION_DATE set to first adoption date (2026-07-18).
-->

# Itaú Quant Research Platform Constitution

## Core Principles

### I. Provider-Agnostic Data Ingestion

All market-data sources MUST sit behind a single common connector interface. Downstream
logic — cleaning, analysis, thesis generation, validation, backtesting, and reporting — MUST
depend only on that interface, never on a concrete provider. Swapping, adding, or removing a
data provider MUST NOT require changes to any downstream component. Provider-specific quirks
(authentication, pagination, field naming, units) MUST be normalized inside the connector, so
what crosses the interface is already canonical.

**Rationale**: Vendor lock-in and scattered provider assumptions are the most common cause of
brittle data pipelines. A single seam keeps providers replaceable and downstream code stable.

### II. Statistical Rigor Before Backtesting

Every proposed thesis or signal MUST pass an explicit statistical validity test on training
data ONLY before it may be backtested or reported. Train, validation, and test splits MUST be
strictly separated, and the separation MUST be enforced in code, not merely by convention. The
test split is spent-once: it MAY be used at most one time per thesis, and any subsequent
evaluation of that thesis on that split is prohibited. A thesis that fails its validity test
MUST NOT proceed to backtest, capital simulation, or reporting as if it had.

**Rationale**: Backtesting an unvalidated or leaked signal manufactures false confidence.
One-shot test discipline is the only defense against silent overfitting and multiple-comparison
bias.

### III. Constrained LLM Autonomy

Any LLM-generated thesis or signal MUST be emitted as structured, schema-validated output only.
The LLM MUST NEVER produce free-form executable code, MUST NEVER trigger direct execution, and
MUST NEVER have direct access to capital, order placement, or trade execution. All LLM output
MUST be validated against an explicit schema before any downstream system consumes it;
output that fails validation MUST be rejected, not repaired silently and used. The LLM proposes;
deterministic, reviewable system code disposes.

**Rationale**: An LLM with an execution path or a capital path is an unbounded risk. Constraining
it to validated, inert, structured proposals keeps every action auditable and human-governable.

### IV. Backtest Honesty

Backtest results MUST always report net performance inclusive of transaction costs, slippage,
and funding/carry — never gross P&L alone. Any result that omits these costs MUST be labeled as
incomplete and MUST NOT be presented as a headline outcome. Synthetic, mock, sample, or
placeholder data MUST be clearly and unmistakably labeled as such everywhere it appears —
in logs, tables, charts, exports, and the dashboard — with no path by which synthetic results
can be mistaken for real ones.

**Rationale**: Gross-only backtests and unlabeled synthetic data are the two easiest ways to
mislead a decision-maker. Honesty about costs and provenance is non-negotiable for a research
platform whose output informs risk.

### V. Mobile-First, Fully Responsive UI

The interactive dashboard MUST be designed and verified for mobile screen widths FIRST, then
progressively enhanced for tablet and desktop. Every feature MUST be usable on mobile; no
feature may exist only on larger screens. Responsiveness MUST be verified, not assumed. The
dashboard MUST remain deployable via Streamlit.

**Rationale**: Designing for the smallest viewport first forces prioritization and guarantees
universal access; desktop-first designs routinely strand functionality on breakpoints users
never reach.

### VI. Configuration Over Hardcoding

Market-specific and provider-specific values — including tickers, tenors, thresholds, and risk
limits — MUST live in configuration, never embedded in code. Code MUST read such values from
config at runtime. Adding or changing a market, instrument, or limit MUST be achievable by
editing configuration alone, without modifying source logic.

**Rationale**: Hardcoded market parameters make the system unmaintainable and untraceable.
Externalized configuration keeps behavior inspectable, diffable, and adjustable without code review.

### VII. Fail-Loud Observability

Data-quality problems and misconfiguration MUST raise visible errors or warnings. The system
MUST NEVER silently degrade, silently drop records, or interpolate over missing or malformed
data without recording that it did so. Every automated correction, gap-fill, or fallback MUST
leave an explicit, retrievable record. When correctness is uncertain, the system MUST surface
the uncertainty rather than hide it.

**Rationale**: Silent degradation corrupts research conclusions invisibly. Loud failure and a
durable record of every automated intervention are what make results trustworthy and debuggable.

### VIII. Simplicity & Reproducibility

The platform MUST avoid speculative complexity and unjustified new abstractions; abstractions
MUST be introduced only in response to a demonstrated, present need. Every research run MUST be
fully reproducible from configuration plus pinned dependency versions and fixed random seeds
alone — no hidden state, no unrecorded manual steps. Given the same configuration and pins, a
run MUST reproduce its results.

**Rationale**: Simplicity keeps the system auditable; reproducibility is what separates research
from anecdote. Both are prerequisites for defensible, repeatable conclusions.

## Engineering Constraints & Standards

- **Interface boundaries**: The connector interface (Principle I), the LLM output schema
  (Principle III), and the config schema (Principle VI) are the platform's stable contracts.
  Changes to any of them MUST be treated as interface changes and reviewed as such.
- **Data provenance**: Every dataset carried through the pipeline MUST retain a provenance
  marker distinguishing real, synthetic, and derived data end to end (Principles IV, VII).
- **Split integrity**: Train/validation/test partitioning and the spent-once test rule
  (Principle II) MUST be enforced by shared code, not reimplemented per feature.
- **Determinism**: Randomness MUST be seeded and the seed recorded; dependency versions MUST be
  pinned (Principle VIII). Non-deterministic behavior in a research run is a defect.
- **No execution path from generation to capital**: There MUST be no code path by which
  LLM output reaches order placement or capital simulation without passing schema validation
  and the statistical and backtest gates (Principles II, III, IV).

## Development Workflow & Quality Gates

- **Constitution Check gate**: Every plan (`plan.md`) MUST pass a Constitution Check before
  design proceeds and be re-checked after design. Violations MUST be justified in the plan's
  Complexity Tracking section or the plan MUST be revised.
- **Spec alignment**: Feature specs (`spec.md`) and plans MUST carry project- and
  feature-level detail (specific tickers, submarkets, tenors, chart types, numeric
  thresholds). The constitution stays abstract; specifics live downstream.
- **Reviewability**: Changes touching a stable contract (connector interface, LLM schema,
  config schema, split logic) MUST be reviewed with explicit attention to the affected
  principle.
- **Verification of UI**: Any dashboard change MUST be verified at mobile width before it is
  considered complete (Principle V).
- **Honest reporting gate**: No backtest or performance result may be reported without net-of-cost
  figures and correct real/synthetic labeling (Principle IV).

## Governance

This constitution supersedes all other development practices where they conflict. It governs how
features are specified, planned, built, and reviewed on this platform.

- **Amendments**: Changes to this constitution MUST be proposed in writing with rationale,
  reviewed, and recorded via a version bump and an updated Sync Impact Report at the top of this
  file. Dependent templates and guidance MUST be checked for consistency as part of any amendment.
- **Versioning policy** (semantic versioning of governance):
  - **MAJOR**: Backward-incompatible governance changes — removing or redefining a principle,
    or removing a required gate.
  - **MINOR**: Adding a new principle or section, or materially expanding existing guidance.
  - **PATCH**: Clarifications, wording, and non-semantic refinements.
- **Compliance review**: Plans and reviews MUST verify compliance with these principles.
  Complexity that violates Principle VIII MUST be justified or removed. Unjustified violations
  block merge.
- **Precedence**: Where a feature spec or plan appears to conflict with a principle, the
  principle prevails until the constitution is formally amended.

**Version**: 1.0.0 | **Ratified**: 2026-07-18 | **Last Amended**: 2026-07-18
