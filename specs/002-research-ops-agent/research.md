# Phase 0 Research: Autonomous Research Operations Agent

Each section resolves one design decision needed before Phase 1. Format: Decision / Rationale /
Alternatives considered.

## 1. Process & scheduling model

**Decision**: `ops_agent` is a second CLI-invoked batch entry point (`research-ops-agent`), not a
resident daemon. Its `tick` subcommand does one bounded pass — check what's due against the
operating schedule, do it, log it, exit — and is itself idempotent (a no-op when nothing is due).
"Continuous" operation (spec Assumptions, FR-006) is achieved by an externally configured
scheduler (cron, CI schedule, systemd timer) invoking `tick` every few minutes, the same pattern
001 already established for `ingest` (001 plan.md Target Platform).

**Rationale**: The spec's own Assumptions section states this explicitly: "the agent runs as
scheduled, resumable activity rather than requiring a permanently resident service... 'continuous'
means the researcher experiences uninterrupted operation, not that a process must never exit."
Principle VIII (Simplicity) rules out an embedded async scheduler/daemon when a stateless,
idempotent CLI invocation under an external scheduler gives identical researcher-facing behavior
with far less code, no process-supervision story, and no new failure mode (a crashed daemon).
Idempotency also makes `tick` trivially safe to invoke more often than needed or to re-run after a
failure — there is no "in-flight" state to corrupt.

**Alternatives considered**: A long-running `asyncio` event loop with in-process timers —
rejected: adds a supervision/restart story, complicates the strict configuration-reload guarantee
(FR-015, a running process could drift from the file on disk), and buys nothing over cron given
the sub-hourly cadences in scope. A message-queue/worker architecture — rejected as speculative
complexity for a single-operator, tens-of-actions-per-day system (Principle VIII).

## 2. Package boundary: `ops_agent` vs. `energy_research`

**Decision**: `ops_agent` is a new top-level package that may import from `energy_research`
(`config.settings.load_config`, `orchestration.ingest.ingest_all`, `orchestration.cycle.run_cycle`
/`replay_cycle`, and read-only `datastore.repository.Repository` accessors for report/shortlist
data). `energy_research` never imports `ops_agent` — enforced by a new import-linter independence
contract alongside the existing layered-architecture contract (001 pyproject.toml
`[tool.importlinter]`).

**Rationale**: The spec's Assumption is explicit — "the 001 pipeline is the unchanged substrate...
it does not modify the pipeline's research logic." A one-directional dependency is the same
mechanism 001 already uses to keep `generation`/`screening`/`backtesting`/`critique`/`reporting`
independent of each other and of `orchestration`'s callers: mechanical enforcement, not review
discipline. It also gives FR-019 ("the agent's permitted surface MUST be structurally limited")
a literal proof: anything `ops_agent` cannot import, it cannot do.

**Alternatives considered**: Folding agent logic into `energy_research.orchestration` as new
functions — rejected: it would let the agent accumulate access to `generation`/`screening`/etc.
by proximity (nothing would stop a future edit from importing them), which is exactly what FR-019
must prevent structurally, not "by instruction" (spec Edge Case: "Attempt to exceed reach").

## 3. Storage: a second, small SQLite database

**Decision**: `ops_agent` state (activity log, proposal index, budget usage, schedule
last-fired timestamps, feed watermarks, drafted data source descriptors) lives in a new
`data/ops_agent.sqlite`, entirely separate from 001's `data/research.sqlite`. Proposed *pipeline*
configuration itself is never duplicated into SQLite — it lives only as the YAML files under
`config/`, and git is the record of its history (§7).

**Rationale**: A second database keeps 001's schema (`datastore/schema.py`) untouched — no
migration coupling between the ledger's spend-once semantics and the agent's own bookkeeping, and
no risk of an agent-side bug corrupting pipeline state through a shared connection. It costs one
extra SQLite file, which is negligible against Principle VIII's actual concern (unjustified
abstraction), not "more than one file."

**Alternatives considered**: Adding tables to `data/research.sqlite` — rejected: would require
touching `energy_research/datastore/schema.py`, violating the "unchanged substrate" assumption,
and would let the agent's write path share a connection/transaction scope with the
`EvaluationLedger`'s atomic spend-once operation, which is exactly the kind of proximity FR-019
and Principle II's ledger guarantee want to avoid. JSONL-only logging with no database — rejected:
budget usage and schedule "last fired at" need queryable, updatable state; append-only JSONL for
the activity log alone (no query needs) would be adequate but splitting storage mechanisms per
entity type is more complexity than one small SQLite file with a few tables.

## 4. Config-only vendor onboarding

**Decision**: One new, shared connector module,
`energy_research.ingestion.providers.declarative`, implements both `MarketDataConnector` and
`QualitativeContextConnector` purely by interpreting a **Data Source Descriptor**: credential
reference (env-var name), base URL, per-category endpoint template, a JMESPath expression per
canonical field (`instrument_key`/`category`/`ts`/`value`/`provenance` for market data;
`source`/`ts`/`text`/`provenance` for context docs), and a pagination mode (`none` | `offset` |
`cursor`, each with named parameters). `ingestion/registry.py` gains a `connector_kind` field on
each provider entry (`python_module` default — today's unchanged behavior — or `declarative`);
when `declarative`, the registry loads the one shared module and hands it the descriptor from
`options` instead of importing `energy_research.ingestion.providers.<provider_id>`. The agent
drafts descriptors (§5) and submits them through the normal proposal path (§7); nothing about
onboarding writes a `.py` file.

**Rationale**: FR-016/017/018 require onboarding "entirely as configuration... with no per-vendor
program code," and Constitution Principle III forbids the LLM from ever producing free-form
executable code. A single, pre-written, thoroughly-tested interpreter for descriptor *data*
satisfies both: the LLM only ever emits a schema-validated `DataSourceDescriptor` (§5), never
code, and every new vendor that fits the descriptor's expressiveness (bearer/API-key/header auth,
templated REST endpoints, JMESPath-mappable JSON responses, offset/cursor pagination) is
onboarded without touching `ingestion/providers/`. Vendors that don't fit — non-REST protocols,
response shapes JMESPath can't flatten, exotic auth handshakes — hit FR-018's required path: the
agent reports the specific limitation (an `OnboardingLimitation` result, contracts/
declarative-connector.md) rather than guessing.

**Alternatives considered**: LLM drafts a new Python connector module per vendor — explicitly
forbidden by Constitution III and FR-016; would also reopen the "no per-vendor program code" gate
FR-016 exists to close. A general-purpose plugin DSL (arbitrary transform pipeline, scripting
hooks) — rejected as speculative complexity beyond the vendors in scope (Principle VIII); JMESPath
plus three pagination modes covers the realistic REST-API surface without inventing a language.

## 5. Vendor discovery

**Decision**: `MarketDataConnector`/`QualitativeContextConnector` implementations may optionally
expose a `discover() -> VendorCatalog` method (default: an empty catalog when unsupported); the
declarative connector's `discover()` probes the descriptor's configured endpoints and returns
whatever categories/series metadata the response describes. `ops_agent.discovery.interpret`
sends the catalog (plus, for not-yet-onboarded vendors, the researcher-supplied interface
description) to the LLM through 001's existing structured-output adapter, and the LLM's *only*
output is a schema-validated draft: `ProvisioningProposal` (data sources, instrument universe
entries, feed schedules) or `DataSourceDescriptor` (onboarding). The LLM never calls a vendor
directly and never sees raw credential values (only the env-var name, per FR-001).

**Rationale**: Keeps discovery inside the same connector protocol Principle I already governs
(discovery is "what can this connector supply," a natural extension of `fetch_series`/
`fetch_context`, not a new integration seam) and keeps the LLM's role exactly where Constitution
III allows it: producing structured, schema-validated proposals from evidence it's handed, never
acting directly on a vendor or on capital-adjacent systems.

**Alternatives considered**: LLM-driven, free-form vendor API exploration (the LLM decides what
HTTP calls to make) — rejected: violates Principle III's "no direct execution" spirit and would
make discovery unauditable (SC-003 requires every action logged with target and reason, which is
hard to guarantee for LLM-improvised calls); a fixed per-vendor discovery script — rejected,
reopens the "no per-vendor code" problem §4 already solves for onboarding.

## 6. `ops_agent`'s own configuration

**Decision**: A new `config/ops_agent.yaml`, validated by a `pydantic` `StrictModel`
(`extra="forbid"`) mirroring 001's config discipline exactly: `llm` (api_key_env, model),
`operating_schedule` (cycle/market-refresh/qualitative-poll cadences), `resource_budgets`
(period, max_llm_calls, max_vendor_requests — §9), `git` (proposal branch prefix, operating
branch name), `notifications` (sink kind), `pipeline_config_path` (points at 001's
`config/default.yaml`). The researcher's risk-side parameters (statistical evidence standard,
cost/slippage/financing assumptions, refinement-loop bounds) are **not** duplicated here — they
already exist as 001's `screening`/`backtesting`/`refinement` config sections and are edited via
the normal proposal path like any other pipeline config.

**Rationale**: Keeps 001's `PipelineConfig` schema (Principle VI's stable contract, per 001's
Engineering Constraints) completely untouched — the ops agent's operating parameters (cadences,
budgets, git/notification wiring) are a different concern from the pipeline's research parameters
and don't belong in the same schema. Reusing the `StrictModel` pattern means a misconfigured
`ops_agent.yaml` fails loudly at load time exactly like 001's config does, with no silent defaults
for required sections.

**Alternatives considered**: Extending `PipelineConfig` with agent-specific sections — rejected:
would make 001's config schema (a stable contract per its own plan.md) depend on 002's concerns,
and would mean every pipeline-only user (running 001 standalone, as the spec's Assumptions
imply remains possible) carries fields it never uses.

## 7. Proposal drafting & approval: git branches, not a bespoke review system

**Decision**: Every agent-drafted configuration change (universe edit, new/changed data source,
feed schedule change, onboarding descriptor) is committed to a fresh branch
`ops-proposal/<slug>-<short-id>`, branched from the current operating branch, touching only
`config/default.yaml` and/or `config/providers.yaml`. The commit message carries the rationale
and discovery evidence pointer. A matching row is written to `ops_agent.sqlite`'s `proposals`
table (status `proposed`) purely as an index (§3) — the diff itself is always the live git diff,
never a stored duplicate that could drift. **Approval is a `git merge` of that branch into the
operating branch, performed by the human as themselves** (their own git identity/commit, not the
agent's) — `research-ops-agent approve <id>` is a thin convenience wrapper around exactly that
merge, runnable only interactively by the researcher, never by the scheduled `tick` process.
`reject` marks the row `rejected` and leaves the branch unmerged. Because 001's `load_config`
always reads whatever is on disk on the operating branch at cycle-start time, a pending proposal
branch has *zero* effect on running cycles until merged (spec Edge Case, FR-011).

**Rationale**: The spec calls for "a human-readable, diffable proposal" and an attributable
"who, when" decision (FR-011/012) — `git diff`/`git log` give both for free, with no new storage
format, no new UI, and reviewer tooling researchers already have (`git diff`, `gh pr review`, an
editor). FR-013 ("the agent MUST NOT be able to approve... its own proposals") becomes a
deployment-level, structural guarantee rather than an application-level check: the scheduled
agent process is provisioned with a git credential that can push `ops-proposal/*` branches but
has no merge/write access to the operating branch (documented as a deployment requirement in
quickstart.md) — there is no code path, credentialed or not, by which `tick` can move a proposal
to `approved`. This is a direct, low-cost instance of Principle VIII: reuse the tool the whole
project already runs on (this very repository is git-and-branch-based Spec Kit workflow) instead
of building a proposal database + review UI.

**Alternatives considered**: A `proposals` table with an `apply` flag flippable via CLI/DB —
rejected: "who decided" would only be as strong as whatever authenticates that CLI call, which
this codebase has no existing identity system for, whereas git commit authorship is already
solved and audited infrastructure; a full web review UI — rejected as out of scope (spec: "the
interactive review dashboard (separate feature)") and unjustified complexity for a
single-operator tool (Principle VIII).

## 8. Notifications (shortlists, escalations, budget exhaustion)

**Decision**: A single `notify(event)` sink writes a structured line to
`data/ops_agent/notifications.jsonl` (append-only) and a human-readable line to the standard
logger, for every: completed-cycle shortlist (FR-009), remediation escalation (FR-008), budget
exhaustion (FR-022), and vendor/credential failure (Edge Cases). The sink is a small interface
(`NotificationSink.send(event)`) so a future channel (email, Slack) is a new implementation, not a
rewrite — but only the file+log sink ships with this feature.

**Rationale**: The spec deliberately leaves the channel unspecified: "any medium that presents a
diffable proposal and records an attributable decision satisfies the spec... surfacing
obligations are met by notifications plus the pipeline's report artifacts" (Assumptions). A
durable, greppable local file meets FR-009/FR-014's "retrievable by a reviewer" bar without
inventing integration work the spec doesn't ask for.

**Alternatives considered**: Building a Slack/email integration now — rejected as speculative
(Principle VIII) and explicitly out of scope; a "notification" concept folded entirely into the
activity log (no separate sink) — rejected because the activity log's audience is an auditor
reconstructing history (SC-003), while notifications need to be the *current, actionable* surface
a researcher checks first — conflating them would make either job harder.

## 9. Resource budgets: scope and enforcement

**Decision**: Budgets (FR-022) bound only the agent's **discretionary** activity: LLM calls made
by `ops_agent` itself (discovery interpretation, proposal/onboarding drafting) and vendor
requests the agent makes for discovery/health-check/onboarding probing. They do **not** cover
001's own per-cycle LLM usage inside `generation`/`critique`, nor the routine market/qualitative
fetches `ingest_all` performs on the configured cadence — those are already bounded by 001's own
`refinement`/cadence configuration (FR-020/SC-008: 001's guarantees hold unchanged). A guard in
`ops_agent.budget` wraps every discretionary call, incrementing a per-period counter in
`ops_agent.sqlite`; on exhaustion it raises a typed `BudgetExhausted` the caller turns into a
logged event + notification (§8), and further discretionary calls are skipped (not queued, not
retried) for the remainder of the period. Scheduled `ingest`/cycle-trigger ticks continue
unaffected by discretionary-budget exhaustion — FR-008's cycle-blocking logic is a separate,
data-freshness concern from resource budgeting.

**Rationale**: The Edge Case that motivates FR-022 ("Resource-consumption runaway") is about
*agent* activity — LLM calls and vendor requests the agent chooses to make — not the pipeline's
already-bounded, already-configured normal operation. Conflating the two would mean a busy
discovery day could starve routine ingestion, which would itself become an availability bug the
spec doesn't ask for.

**Alternatives considered**: One global budget covering all LLM/vendor activity including 001's
own — rejected: it would make `ops_agent` a gatekeeper in front of 001's generation/critique
calls, which is exactly the kind of pipeline-behavior influence FR-010/FR-020 forbid the agent
from having.

## 10. Remediation before escalation

**Decision**: When a scheduled `tick` finds required data stale or a vendor unreachable
(FR-008), `ops_agent.remediation` retries the exact same 001 operation that would normally run —
`orchestration.ingest.ingest_all` scoped to the affected provider/category — up to
`OpsAgentConfig.remediation.max_retries` times with `backoff_seconds` between attempts (both
configured in `config/ops_agent.yaml`, never hardcoded — Constitution Principle VI), logging each
attempt. If freshness is restored, the cycle proceeds normally; if not, it escalates (§8) and does
**not** trigger `run_cycle` on data 001 itself would deem unfit (001's own `Repository.assert_fresh`
gate is the final word either way).

**Rationale**: Reuses 001's existing fetch/clean/quality path verbatim instead of duplicating any
part of it inside `ops_agent` — consistent with the package-boundary decision (§2: `ops_agent`
calls `ingest_all`, it doesn't reimplement it) and Principle VIII.

**Alternatives considered**: A bespoke retry/backoff/circuit-breaker library — rejected as
unjustified complexity for "retry a CLI-equivalent call N times" (Principle VIII).

## 11. Testing strategy

**Decision**: Contract tests prove the structural guarantees (§2's import boundary + a static
reach-audit against the FR-019 allowlist, declarative-connector protocol conformance, activity-log
append-only-ness, budget enforcement). Integration tests exercise each user story's Independent
Test verbatim against the existing synthetic `sample_provider` data (no live vendor credentials
needed, matching 001's existing test posture).

**Rationale**: Mirrors 001's own contract/integration split (001 research.md's testing decisions)
so both features are audited the same way; the structural guarantees (FR-019, FR-013) are exactly
the kind of property 001 already treats as "enforced mechanically, not by convention" for its own
architecture boundaries and multiplicity control.

**Alternatives considered**: None — this directly extends 001's established, already-justified
testing approach rather than introducing a new one.
