# Implementation Plan: Autonomous Research Operations Agent

**Branch**: `002-research-ops-agent` | **Date**: 2026-07-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-research-ops-agent/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Add a new, structurally-separate `ops_agent` package that operates the existing 001 research
pipeline end to end — discovering vendor offerings, drafting provisioning/onboarding proposals,
keeping data fresh, triggering cycles on a cadence, and surfacing shortlists — while the 001
pipeline itself stays the unchanged substrate (spec Assumptions). `ops_agent` depends on
`energy_research` one-directionally (may call its CLI-equivalent entry points and read its
datastore; `energy_research` never imports `ops_agent`), so the agent's reach is exactly the
surface FR-019 grants: configuration proposals, data ingestion, cycle triggering, and reading
outputs. Two design choices carry most of the weight: (1) **proposals ride on git** — the agent
drafts config changes as commits on `ops-proposal/*` branches with rationale in the commit
message, and a human's `git merge` into the operating branch *is* the approval record (who/when
come from git's own metadata), so no bespoke review UI is needed and the agent structurally
cannot self-approve (it has no credential that can write to the operating branch); (2)
**config-only vendor onboarding** is realized by one new shared connector,
`energy_research.ingestion.providers.declarative`, that satisfies the existing
`MarketDataConnector`/`QualitativeContextConnector` protocol purely from a data-driven "Data
Source Descriptor" (auth-by-env-var-reference, endpoint templates, JMESPath field mapping) — so
onboarding a vendor never requires writing a new Python module. See
[research.md](./research.md) for the full rationale behind each decision.

## Technical Context

**Language/Version**: Python 3.11+ (matches 001; same interpreter, same virtualenv/package).

**Primary Dependencies**: `httpx` (HTTP transport for the declarative connector and vendor
discovery probes — already present transitively via the `anthropic` SDK; promoted to a direct
dependency), `jmespath` (response-to-canonical-field mapping expressions for Data Source
Descriptors, FR-016), `pydantic` (Proposal/DataSourceDescriptor/ActivityLogEntry/budget/schedule
models, same `StrictModel`/`extra="forbid"` discipline as 001), `anthropic` SDK (reused via
001's existing structured-output adapter for discovery interpretation and proposal drafting —
no new LLM transport), the system `git` CLI via `subprocess` (proposal branches/commits/diffs —
no new git library; Simplicity). No web framework, no broker/execution SDK, no scheduler
daemon library (research.md §1).

**Storage**: A second, purpose-built SQLite database, `data/ops_agent.sqlite` (separate from
001's `data/research.sqlite`), holding only the agent's own state: activity log, proposal index,
resource-budget usage, operating-schedule last-fired timestamps, feed watermarks, and drafted/
approved data source descriptors. 001's schema and database are never touched (research.md §3).
Proposed *pipeline* configuration changes themselves live as ordinary file edits to
`config/default.yaml` / `config/providers.yaml`, version-controlled and diffed via git — not
duplicated into SQLite.

**Testing**: `pytest`, mirroring 001's split. New `tests/contract/` cases: an import-linter
independence contract (`ops_agent` → `energy_research` one-directional) plus a static reach-audit
test enumerating every module/symbol `ops_agent` imports from `energy_research` against the
FR-019 allowlist; a declarative-connector protocol-conformance test; an activity-log
append-only/immutability test; a budget-exhaustion test. New `tests/integration/` cases per user
story: US1 (credentials → proposals → approval → first cycle → shortlist, against the existing
synthetic `sample_provider`), US2 (cadence-driven tick ingests new qualitative material and
triggers a cycle unprompted; a staleness scenario that remediates or escalates), US3 (a pending
proposal has zero effect on the running config; full activity-log reconstruction), US4
(config-only onboarding of a not-yet-integrated vendor via a Data Source Descriptor, and the
explicit-limitation path for an unsupported interface).

**Target Platform**: Linux server or local developer machine, identical to 001. `ops_agent` is a
second CLI-invoked batch entry point (`research-ops-agent bootstrap|tick|approve|reject|status|
log`), not a resident daemon; "continuous" operation is an externally configured scheduler
(cron) invoking `tick` on a short interval, exactly the pattern 001 already established for
`ingest` (research.md §1). `tick` is idempotent and a no-op when nothing is due.

**Project Type**: Single repository, two packages: the existing `src/energy_research/` (001,
unchanged in its research logic) plus a new sibling `src/ops_agent/` (002). No frontend; the
interactive dashboard remains a separate, unplanned future feature (spec Assumptions).

**Performance Goals**: Not latency-critical — `tick` runs are short, bounded checks (is anything
due?) that only do real work when a cadence has elapsed; no SLA specified in the spec.

**Constraints**: No dependency on, or code path to, any broker/execution/order-placement package
(inherited from 001, re-verified for the new package in the architecture-boundary contract). All
credentials referenced by env-var name only, in both `energy_research` config and the new
`config/ops_agent.yaml` — never a secret value in code, config, logs, proposals, or the activity
log (FR-001). The agent's only path to changing pipeline behavior is a human-merged git commit to
tracked YAML files already validated by 001's existing `PipelineConfig` schema — there is no
other write path into pipeline configuration.

**Scale/Scope**: One agent process per operation, ticking on the order of minutes-to-hourly;
proposal volume expected in the tens per month, not a high-throughput system. Budgets (FR-022)
default to double-digit-to-low-hundreds discretionary LLM calls and vendor requests per day —
exact defaults are a configuration concern (`config/ops_agent.yaml`), not fixed here.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan satisfies it |
|---|---|---|
| I. Provider-Agnostic Data Ingestion | **PASS** | The declarative connector (research.md §4) is *one more implementation* of the existing `MarketDataConnector`/`QualitativeContextConnector` protocol — it adds a config-only path to that seam, it does not create a second one. `ingestion/registry.py` gains a minimal, backward-compatible `connector_kind` dispatch; every other layer still depends only on the protocol. |
| II. Statistical Rigor Before Backtesting | **PASS (unaffected)** | `ops_agent` never reads or writes split-scoped data; it only calls `run_cycle`/`replay_cycle` as opaque operations and reads their `CycleResult`. FR-020/SC-008 require 001's screening/multiplicity/split discipline to hold unchanged — `ops_agent` has no import path into `screening`, `datastore.ledger`, or split-scoped `Repository` methods (contracts/ops-agent-boundary.md). |
| III. Constrained LLM Autonomy | **PASS** | The agent's only two LLM uses — discovery interpretation and proposal/onboarding drafting — reuse 001's existing structured-output adapter and emit schema-validated `ProvisioningProposal`/`DataSourceDescriptor` objects only (data-model.md); invalid output is rejected, never repaired or partially applied. The LLM never authors executable code: the declarative connector is a fixed, pre-written interpreter for descriptor *data*, not a code-generation target (research.md §4). No proposal takes effect without a human `git merge` (FR-011/013). |
| IV. Backtest Honesty | **PASS (unaffected)** | `ops_agent` cannot alter backtest, cost, or provenance logic (no import path); it surfaces `CycleResult` as produced by 001 verbatim (FR-009). |
| V. Mobile-First, Fully Responsive UI | **N/A (deferred)** | No UI in this feature; notifications are file/log based (research.md §7), and the interactive dashboard is explicitly out of scope (spec Assumptions). |
| VI. Configuration Over Hardcoding | **PASS** | Cadences, budgets, credential references, and git/notification wiring live in a new `config/ops_agent.yaml`, `pydantic`-validated with the same `extra="forbid"` `StrictModel` discipline as 001 (data-model.md). Data Source Descriptors are themselves configuration, not code (FR-016). Proposed universe/provider changes land in 001's *existing* config files, never in source. |
| VII. Fail-Loud Observability | **PASS** | Every agent action (discovery, ingestion trigger, cycle trigger, proposal, remediation, escalation, budget event, empty poll) is an append-only `AgentActivityLogEntry` (data-model.md); invalid credentials, vendor-interface limitations (FR-018), and budget exhaustion are reported explicitly, never silently skipped (Edge Cases). |
| VIII. Simplicity & Reproducibility | **PASS** | Proposals reuse git instead of a bespoke review system; remediation reuses 001's own `ingest`/`run_cycle` entry points instead of duplicating fetch/clean logic; a second small SQLite database avoids coupling the agent's schema evolution to 001's ledger schema. FR-015/SC-007: a cycle's `config_snapshot` is still exactly 001's mechanism — `ops_agent` changes *which file* is on disk before a cycle starts, never how a cycle records or replays it, so reproducibility is untouched. |

**Result**: No violations. Complexity Tracking table is not needed (empty — no principle
deviations to justify).

*Post-Phase-1 re-check performed after data-model.md and contracts/ were written: `energy_research`
receives two kinds of additive touch, both inside the `ingestion` layer Principle I already
designates as the provider-swapping seam — the `declarative` connector + `connector_kind` registry
dispatch (research.md §4), and an optional `discover()` method added to the three existing sample
provider modules (research.md §5) so US1's discovery step has something concrete to probe. Neither
changes any existing provider's current behavior (both are backward-compatible additions), and
no other `energy_research` layer is touched. All `ops_agent` state (proposals index, activity log,
budgets, schedule, descriptors) lives in the new `data/ops_agent.sqlite`, never in 001's tables.
**Result: still PASS, no changes.***

*Post-implementation re-check (all 45 tasks complete, 138 tests passing — T043): walked all 8
principles against the actual code, not just the design.*

| Principle | Status | Verified against implementation |
|---|---|---|
| I. Provider-Agnostic Data Ingestion | **PASS** | `ingestion/providers/declarative.py` satisfies `MarketDataConnector`/`QualitativeContextConnector` exactly like every other provider (`tests/contract/test_declarative_connector_protocol.py`); `registry.py`'s `connector_kind` dispatch defaults to `python_module` (rule 1's existing behavior, byte-for-byte). **One documented amendment**: `contracts/ops-agent-boundary.md`'s allowlist was extended, during implementation, to include `energy_research.ingestion.registry` (read-only `market_connectors`/`context_connectors` construction only). This was required by `budget-contract.md` rule 1 itself — the budget guard must wrap the actual external `health_check()`/`discover()` call at its call site in `ops_agent.discovery.vendor_probe`, which is impossible without holding the connector instance directly. The registry is the same provider-swapping seam Principle I already designates (no concrete provider module is ever imported by `ops_agent`), so this is a narrowing clarification of the seam, not a new one. `tests/contract/test_ops_agent_boundary.py`'s reach audit enforces the amended allowlist exactly. |
| II. Statistical Rigor Before Backtesting | **PASS (unaffected)** | The reach-audit test statically confirms zero `ops_agent` import path into `screening`/`datastore.ledger`/split-scoped `Repository` methods; `agent.py` only calls `run_cycle`/`ingest_all` as opaque functions and reads `CycleResult`. |
| III. Constrained LLM Autonomy | **PASS** | Both LLM call sites (`discovery.interpret`, `onboarding.draft`) go through `energy_research.common.llm`'s transport and validate the response against `ProvisioningDraft`/`OnboardingDraft` `StrictModel`s; invalid payloads are rejected and logged (`propose`/`limitation_reported`, outcome `failed`), never repaired (`tests/unit/ops_agent/onboarding/test_draft.py`). No proposal takes effect without a human `git merge`: `git_store.approve()`/`reject()` refuse under the scheduled agent's own git identity marker (`tests/integration/test_ops_agent_us1_provisioning.py::test_approve_and_reject_refuse_under_the_agents_own_git_identity`). |
| IV. Backtest Honesty | **PASS (unaffected)** | `agent.tick()` surfaces `CycleResult.report_path`/`promoted_thesis_ids` verbatim into `notify()`; no field is recomputed or filtered. |
| V. Mobile-First, Fully Responsive UI | **N/A (deferred)** | No UI shipped; notifications remain file/log based (`notify.py`). |
| VI. Configuration Over Hardcoding | **PASS** | `OpsAgentConfig` (`extra="forbid"`) requires `resource_budgets`/`remediation` explicitly — no hidden defaults for a required control (budget-contract.md rule 5, verified by `tests/contract/test_budget_enforcement.py::test_zero_limit_blocks_the_first_call`); `remediation.max_retries`/`backoff_seconds` are read from config in `remediation.py`, never a literal constant. |
| VII. Fail-Loud Observability | **PASS** | Every action category in the `AgentActivityLogEntry.action` enum is exercised by at least one test: `credential_error`/`discover`/`propose` (US1), `remediate`/`escalate`/`checked_and_empty` (US2), `limitation_reported` (US4), `budget_blocked` (budget contract test). `tests/contract/test_activity_log_append_only.py` statically confirms no `UPDATE`/`DELETE` path exists against `activity_log`. |
| VIII. Simplicity & Reproducibility | **PASS** | `tests/integration/test_ops_agent_us3_change_control.py::test_replay_is_independent_of_agent_activity_before_or_after` confirms SC-007 holds with `ops_agent` activity happening both before and after the replayed cycle — `ops_agent` changes only which file is on disk before a cycle starts, never how a cycle records or replays it. |

**Result**: Still PASS overall, with the one documented, narrowly-scoped allowlist amendment above
(also reflected in `contracts/ops-agent-boundary.md` itself). No Complexity Tracking entry needed —
the amendment sharpens an existing seam rather than introducing a new dependency direction or
principle deviation.

## Project Structure

### Documentation (this feature)

```text
specs/002-research-ops-agent/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
│   ├── README.md
│   ├── ops-agent-boundary.md
│   ├── proposal-lifecycle.md
│   ├── declarative-connector.md
│   ├── activity-log-contract.md
│   └── budget-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/energy_research/                        # 001, unchanged research logic (this feature only
│                                             # touches the ingestion seam, additively)
├── ingestion/
│   ├── registry.py                          # + minimal connector_kind dispatch (python_module
│   │                                         #   [default, unchanged behavior] | declarative)
│   └── providers/
│       ├── declarative.py                    # NEW: one shared, config-driven connector
│       │                                      #   implementing MarketDataConnector /
│       │                                      #   QualitativeContextConnector from a Data
│       │                                      #   Source Descriptor (FR-016/017)
│       ├── sample_provider.py                 # + optional discover() (research.md §5); existing
│       │                                      #   fetch_series/health_check behavior unchanged
│       ├── secondary_market_provider.py        # + optional discover(), same terms
│       └── qualitative_context_provider.py      # + optional discover(), same terms
└── ...                                       # generation/screening/backtesting/critique/
                                               # reporting/datastore/orchestration: untouched

src/ops_agent/                                # NEW package (this feature)
├── config.py                                 # OpsAgentConfig (pydantic StrictModel): llm,
│                                              #   operating_schedule, resource_budgets, git,
│                                              #   notifications, pipeline_config_path
├── credentials.py                             # CredentialReference resolution (env-var name ->
│                                              #   presence check only; value never logged/stored)
├── store/
│   ├── schema.py                              # ops_agent.sqlite schema (own DB, see data-model.md)
│   └── repository.py                          # activity log (append-only), budgets, schedule
│                                              #   state, feed watermarks, descriptor index
├── discovery/
│   ├── vendor_probe.py                        # calls connector.discover() where supported;
│   │                                          #   assembles raw catalog + evidence
│   └── interpret.py                            # LLM structured-output call: catalog/evidence ->
│                                              #   draft ProvisioningProposal / DataSourceDescriptor
├── proposals/
│   ├── models.py                               # ProvisioningProposal (pydantic); approval/
│   │                                            #   rejection is a status transition on this model,
│   │                                            #   not a separate ApprovalDecision entity
│   │                                            #   (data-model.md ApprovalDecision)
│   └── git_store.py                            # branch/commit/diff via `git` subprocess;
│                                              #   approve/reject helpers (run as the human's own
│                                              #   git identity, never the agent's)
├── onboarding/
│   └── draft.py                                 # vendor-interface -> DataSourceDescriptor draft,
│                                              #   or an explicit OnboardingLimitation (FR-018)
├── scheduling.py                                # what's due now? (cycle / market refresh /
│                                              #   qualitative poll) against operating_schedule
├── budget.py                                    # per-period usage guard around discretionary
│                                              #   LLM calls and vendor discovery/probe requests
├── remediation.py                                # bounded retry of energy_research.orchestration
│                                              #   .ingest before escalating; retry count/backoff
│                                              #   read from OpsAgentConfig.remediation, never a
│                                              #   hardcoded constant (Principle VI, FR-008)
├── notify.py                                     # shortlist + escalation + budget-exhaustion
│                                              #   sink: JSONL file + log line (research.md §7)
├── agent.py                                       # tick(): orchestrates the above, single pass
└── cli.py                                          # `research-ops-agent` entry points: bootstrap,
                                               #   tick, approve, reject, status, log

tests/
├── contract/
│   ├── test_ops_agent_boundary.py             # import-linter independence + reach-audit (FR-019)
│   ├── test_declarative_connector_protocol.py # conforms to MarketDataConnector/QualitativeContext-
│   │                                          #   Connector (contracts/data-connector.md, 001)
│   ├── test_activity_log_append_only.py        # FR-014, no update/delete path
│   └── test_budget_enforcement.py               # FR-022: exhaustion halts discretionary activity
└── integration/
    ├── test_ops_agent_us1_provisioning.py       # credentials -> proposals -> approval -> first
    │                                          #   cycle -> shortlist, zero hand-written config
    ├── test_ops_agent_us2_continuous.py          # unprompted ingest + cycle on cadence; stale-data
    │                                          #   remediation vs. escalation
    ├── test_ops_agent_us3_change_control.py       # pending proposal has no effect; full log
    │                                          #   reconstruction (SC-002/SC-003)
    └── test_ops_agent_us4_onboarding.py           # config-only onboarding to first ingestion;
                                               #   explicit-limitation path (FR-018)

config/
├── ops_agent.yaml                              # NEW: agent's own operating config (research.md §5)
├── default.yaml                                # 001, unchanged shape — target of provisioning
│                                              #   proposals (instrument_universe, splits, etc.)
└── providers.yaml                               # 001, unchanged shape — target of data-source /
                                               #   onboarding proposals; declarative entries add a
                                               #   connector_kind + descriptor, nothing else changes

pyproject.toml                                   # + httpx (direct), jmespath; + research-ops-agent
                                                  #   console script; + independence import-linter
                                                  #   contract (ops_agent -> energy_research only)
uv.lock
```

**Structure Decision**: Two packages in one repository, one-directional dependency. `ops_agent`
is the only new package; it may import from `energy_research` (its CLI-equivalent entry points,
config loader, and read-only repository/report access) but `energy_research` has zero awareness
of `ops_agent`'s existence, mirroring exactly how `orchestration` is 001's sole integration point
for its own five analysis layers. Both deliberate touches inside `energy_research` — the
declarative connector plus the registry's `connector_kind` dispatch, and the sample providers'
optional `discover()` methods — live inside the `ingestion` layer precisely because Principle I
already designates that layer as the provider-swapping seam; no other 001 layer changes.

## Complexity Tracking

*No entries — Constitution Check reported no violations requiring justification.*
