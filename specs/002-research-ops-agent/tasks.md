---

description: "Task list for Autonomous Research Operations Agent"
---

# Tasks: Autonomous Research Operations Agent

**Input**: Design documents from `/specs/002-research-ops-agent/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md,
data-model.md, contracts/, quickstart.md — all present.

**Tests**: Not explicitly requested in the feature specification. The contract tests included
below (agent reach boundary, activity-log append-only, budget enforcement, declarative-connector
protocol conformance) are not generic verification scaffolding — they are the mechanical
enforcement of guarantees plan.md's Constitution Check designated as structural, non-optional
deliverables (FR-019's reach limit, FR-014's audit durability, FR-022's spend ceiling, and
Principle I's provider-agnostic seam extended to config-only onboarding). Integration tests mirror
each user story's Independent Test from spec.md, run against 001's existing synthetic providers —
no live vendor credentials required, matching 001's own test posture (quickstart.md §8).

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Two packages in one repository (see plan.md Project Structure): the existing
`src/energy_research/` (001, touched only at the ingestion seam) and the new `src/ops_agent/`
(002); `tests/`, `config/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: New-package initialization and dependency/tooling wiring

- [ ] T001 Create `src/ops_agent/{store,discovery,proposals,onboarding}/__init__.py`, `src/ops_agent/__init__.py`, and `tests/{contract,integration}/__init__.py` additions per plan.md Project Structure (no new top-level test dirs — reuses 001's `tests/contract`/`tests/integration`)
- [ ] T002 Add `httpx` (promote to direct dependency) and `jmespath` to `pyproject.toml` dependencies; add `research-ops-agent = "ops_agent.cli:main"` under `[project.scripts]`; regenerate `uv.lock`
- [ ] T003 Add an import-linter `independence` contract to `pyproject.toml` `[tool.importlinter]`: `ops_agent` may import `energy_research`; `energy_research` MUST NOT import `ops_agent` (contracts/ops-agent-boundary.md rule 1)
- [ ] T004 [P] Create `config/ops_agent.yaml` skeleton (placeholder cadences/budgets, no secrets) per `quickstart.md` §1

**Checkpoint**: New-package scaffolding and dependency/architecture tooling in place.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting infrastructure every user story depends on: the agent's own config and
credential handling, its separate SQLite store (activity log, budgets, schedule state, feed
watermarks, proposal index), notification sink, budget guard, scheduling, and vendor-discovery
capability on the existing synthetic connectors — plus the contract tests that mechanically
enforce the agent's structural boundary from day one.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T005 [P] `src/energy_research/ingestion/providers/sample_provider.py` — add a `discover() -> VendorCatalog`-shaped method returning the provider's configured market categories/instrument hints (research.md §5; duck-typed, no protocol change required)
- [ ] T006 [P] `src/energy_research/ingestion/providers/secondary_market_provider.py` — add the same `discover()` method
- [ ] T007 [P] `src/energy_research/ingestion/providers/qualitative_context_provider.py` — add the same `discover()` method for context categories
- [ ] T008 `src/ops_agent/config.py` — `OpsAgentConfig` pydantic `StrictModel` (`llm`, `operating_schedule`, `resource_budgets`, `git`, `notifications`, `pipeline_config_path`) + `load_ops_agent_config(path)` per data-model.md `OpsAgentConfig`
- [ ] T009 [P] `src/ops_agent/credentials.py` — `CredentialReference` resolution (env-var name → presence check only) and `CredentialError`, raised visibly and never silently on a missing/empty value (FR-001)
- [ ] T010 `src/ops_agent/store/schema.py` — `data/ops_agent.sqlite` table definitions for all data-model.md store entities: `activity_log`, `proposals`, `resource_budget_usage`, `operating_schedule_state`, `feed_watermarks`, `data_source_descriptors` (depends on T008)
- [ ] T011 [P] `src/ops_agent/store/repository.py` — `record_activity`/`read_activity` (INSERT/SELECT only against `activity_log`), budget usage read/increment, schedule-state read/update, feed-watermark read/update, proposal-index CRUD (depends on T010)
- [ ] T012 [P] `src/ops_agent/notify.py` — `NotificationSink` interface + `FileNotificationSink` (JSONL append + log line) per research.md §8
- [ ] T013 [P] `src/ops_agent/budget.py` — `guard(kind: "llm" | "vendor_request")` enforcing `ResourceBudgetConfig` via `store.repository`; raises `BudgetExhausted` and logs `budget_blocked` on exhaustion (contracts/budget-contract.md) (depends on T008, T011)
- [ ] T014 [P] `src/ops_agent/scheduling.py` — `is_due(kind, config, state)` against `OperatingSchedule` cadences and `OperatingScheduleState.last_fired_at` (depends on T008, T011)
- [ ] T015 [P] `tests/contract/test_ops_agent_boundary.py` — asserts the import-linter `independence` contract (T003) holds and statically enumerates every `energy_research.*` import under `src/ops_agent/` against the contracts/ops-agent-boundary.md allowlist, failing on anything outside it (FR-019)
- [ ] T016 [P] `tests/contract/test_activity_log_append_only.py` — asserts `store/repository.py` (T011) contains no `UPDATE`/`DELETE` against `activity_log`, only `INSERT`/`SELECT` (FR-014, contracts/activity-log-contract.md rule 1)
- [ ] T017 [P] `tests/contract/test_budget_enforcement.py` — asserts `budget.py` (T013) raises `BudgetExhausted` at the configured limit, blocks further discretionary calls for the remainder of the period, and resets only at the next `period_key` (contracts/budget-contract.md) (depends on T013)

**Checkpoint**: Foundation ready — user story implementation can now begin.

---

## Phase 3: User Story 1 - From credentials to a running research operation (Priority: P1) 🎯 MVP

**Goal**: From vendor/LLM credentials by reference plus risk parameters, produce provisioning
proposals (data sources, instrument universe, feed schedules), let the researcher approve them,
and reach a completed first cycle and shortlist with zero hand-written configuration.

**Independent Test**: Provide credentials for at least one market-data vendor and one qualitative
feed against a fresh installation; verify `research-ops-agent bootstrap` produces provisioning
proposals covering discoverable series and a candidate universe; approve them; verify ingestion
and a first `research-ops-agent tick` complete a cycle and a shortlist report is produced, with
zero hand-written configuration.

### Implementation for User Story 1

- [ ] T018 [P] [US1] `src/ops_agent/discovery/vendor_probe.py` — `VendorCatalog`/`CatalogEntry` dataclasses; probes each configured connector's `discover()` (duck-typed via `hasattr`, falling back to an empty catalog) and `health_check()`; records `credential_error`/`discover` activity entries per vendor without one vendor's failure blocking another's (spec Acceptance Scenario 1.3) (depends on T011, T009)
- [ ] T019 [US1] `src/ops_agent/discovery/interpret.py` — LLM structured-output call via `energy_research.common.llm.StructuredRequest` turning a `VendorCatalog` into a schema-validated draft `ProvisioningProposal` (data sources / instrument universe / feed schedules), rejecting invalid LLM output rather than repairing it (Constitution III) (depends on T018, T013)
- [ ] T020 [P] [US1] `src/ops_agent/proposals/models.py` — `ProvisioningProposal`, `ApprovalDecision` pydantic `StrictModel`s per data-model.md
- [ ] T021 [US1] `src/ops_agent/proposals/git_store.py` — branch/commit/diff via `git` subprocess: `open_proposal()`, `approve()`, `reject()` (contracts/proposal-lifecycle.md); `approve()`/`reject()` refuse to run under the scheduled agent's own git identity (depends on T020)
- [ ] T022 [US1] `src/ops_agent/agent.py` — `bootstrap()`: runs discovery (T018) + interpretation (T019) for every configured vendor, opens one proposal branch per proposal via `git_store` (T021), logs every step (`discover`, `propose`) via `store.repository` (depends on T019, T021, T011)
- [ ] T023 [US1] `src/ops_agent/agent.py` — `tick()`: if a cycle is due (`scheduling.py`), refreshes market data via `energy_research.orchestration.ingest.ingest_all` then calls `energy_research.orchestration.cycle.run_cycle`, surfacing the resulting `CycleResult` (shortlist + report path) via `notify()` (FR-009) and logging `cycle_trigger` (depends on T014, T012, T011)
- [ ] T024 [US1] `src/ops_agent/cli.py` — `research-ops-agent bootstrap|tick|approve|reject|status` entry points, `--config` option defaulting to `config/ops_agent.yaml` (depends on T022, T023, T021)
- [ ] T025 [P] [US1] `tests/integration/test_ops_agent_us1_provisioning.py` — credentials → `bootstrap` proposals → `approve` → `tick` → completed cycle → shortlist notification, zero hand-written config, against 001's `sample_provider`/`qualitative_context_provider` (spec.md US1 Acceptance Scenarios 1–4) (depends on T024)

**Checkpoint**: User Story 1 is fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - Hands-off continuous operation (Priority: P1)

**Goal**: Keep data current unprompted — refresh market series ahead of cycles, poll qualitative
feeds and pick up new material, trigger cycles on cadence, and remediate-or-escalate blocked
cycles — with thesis ideation staying entirely inside the unchanged 001 pipeline.

**Independent Test**: With a provisioned operation, publish a new document to a qualitative feed
and advance ticks past the cycle cadence; verify the agent ingested the new document unprompted, a
new cycle ran on schedule reflecting the updated context, and the shortlist was surfaced — zero
researcher interaction. Then make a feed stale and verify the agent remediates or escalates rather
than letting cycles fail silently.

### Implementation for User Story 2

- [ ] T026 [P] [US2] `src/ops_agent/remediation.py` — bounded retry (small fixed count, backoff) of `energy_research.orchestration.ingest.ingest_all` scoped to the affected provider/category before escalating; every attempt logged (FR-008) (depends on T011, T012)
- [ ] T027 [US2] `src/ops_agent/agent.py` — extend `tick()`: poll qualitative feeds on `qualitative_poll_cadence_hours` using `FeedWatermark` (store) to ingest only genuinely new material unprompted, logging `checked_and_empty` when nothing new is found (Edge Case); on stale/missing data at cycle time, invoke `remediation.py` (T026) before triggering `run_cycle`; escalate via `notify()` and skip the cycle (never run on data 001's own `assert_fresh` would refuse) when remediation fails (depends on T023, T026, T014)
- [ ] T028 [US2] `src/ops_agent/scheduling.py` — extend `is_due()` to track `qualitative_poll_cadence_hours` and `market_refresh_cadence_hours` independently of `cycle_cadence_hours`, each with its own `OperatingScheduleState` row (depends on T014)
- [ ] T029 [P] [US2] `tests/integration/test_ops_agent_us2_continuous.py` — publish new material to the sample qualitative feed, run enough ticks to cross poll + cycle cadence, assert unprompted ingestion + on-schedule cycle + shortlist reflecting the new context; then force staleness and assert either successful remediation (cycle proceeds) or a visible escalation naming the series/vendor (spec.md US2 Acceptance Scenarios 1–5) (depends on T027)

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - Reviewable change control and a complete audit trail (Priority: P2)

**Goal**: Every agent-drafted configuration change is a diffable proposal with no effect before
approval, every decision is attributable, and every agent action is durably logged and
retrievable — closing the remaining gaps in the git-based proposal mechanism and activity log
already built in Foundational + US1.

**Independent Test**: Cause the agent to want a universe change; verify a diffable proposal exists
and has no effect before approval; approve it and verify it takes effect and is visible in the
next cycle's recorded `config_snapshot`; then inspect `research-ops-agent log` and reconstruct the
full sequence of agent actions for the period.

### Implementation for User Story 3

- [ ] T030 [P] [US3] `src/ops_agent/cli.py` — add `research-ops-agent log --since --until --action` reading `store/repository.read_activity` (contracts/activity-log-contract.md rule 3) (depends on T011, T024)
- [ ] T031 [US3] `src/ops_agent/proposals/git_store.py` — extend `approve()`/`reject()` to populate `decided_by`/`decided_at`/`applied_commit_sha` from the actual merge-commit's git metadata, and to distinguish `approved` from `edited_and_approved` when the merged tree differs from the proposal branch's original tip (FR-004, FR-012) (depends on T021)
- [ ] T032 [P] [US3] `tests/integration/test_ops_agent_us3_change_control.py` — cause a universe-change proposal; verify `config/default.yaml` on disk and a `tick()`'s `config_snapshot` are unaffected before approval; approve it and verify it takes effect on the next cycle and appears in that cycle's recorded `config_snapshot`; then reconstruct the full action sequence for the period from `research-ops-agent log` alone (spec.md US3 Acceptance Scenarios 1–4) (depends on T031, T030)

**Checkpoint**: User Stories 1, 2, and 3 all independently functional.

---

## Phase 6: User Story 4 - Config-only vendor onboarding (Priority: P3)

**Goal**: Onboard a new market-data or qualitative vendor entirely as configuration — no new
Python module — via a drafted Data Source Descriptor interpreted by one shared declarative
connector.

**Independent Test**: Present a vendor interface not previously integrated; verify the agent
drafts an onboarding proposal that is pure configuration; approve it; verify series from the new
vendor are ingested, quality-checked, and usable in a full cycle with no per-vendor program code
added. Separately, present a vendor interface the descriptor language cannot express and verify an
explicit limitation is reported rather than a guessed integration.

### Implementation for User Story 4

- [ ] T033 [P] [US4] `src/energy_research/config/settings.py` — add `connector_kind: Literal["python_module","declarative"] = "python_module"` to `MarketProviderEntry`/`ContextProviderEntry` (data-model.md "Registry extension"); default preserves every existing entry's current behavior unchanged
- [ ] T034 [US4] `src/energy_research/ingestion/registry.py` — dispatch on `connector_kind`: `declarative` routes to `ingestion/providers/declarative.py` with the `DataSourceDescriptor` from `options`; `python_module` (default) keeps today's exact per-provider-module lookup, unchanged (depends on T033)
- [ ] T035 [P] [US4] `src/energy_research/ingestion/providers/declarative.py` — shared `MarketDataConnector`/`QualitativeContextConnector` implementation: header-bearer auth from a credential reference, `httpx` requests against rendered `path_template`s, `jmespath`-driven `field_mapping`, `none`/`offset`/`cursor` pagination, plus `discover()`/`health_check()` — per contracts/declarative-connector.md (depends on T033)
- [ ] T036 [P] [US4] `tests/contract/test_declarative_connector_protocol.py` — asserts `declarative.py` (T035) satisfies `MarketDataConnector`/`QualitativeContextConnector` (001 contracts/data-connector.md) via `isinstance`/`runtime_checkable`, and that a fixture descriptor + fixture HTTP responses map correctly to `RawObservation`/`RawContextDoc` (depends on T035)
- [ ] T037 [P] [US4] `src/ops_agent/proposals/models.py` — add `DataSourceDescriptor`, `EndpointSpec`, `PaginationSpec`, `OnboardingLimitation` pydantic `StrictModel`s per data-model.md (depends on T020)
- [ ] T038 [US4] `src/ops_agent/onboarding/draft.py` — inspects a vendor interface description/discovery probe and asks the LLM (via `energy_research.common.llm`) for either a schema-validated `DataSourceDescriptor` or an `OnboardingLimitation` per contracts/declarative-connector.md's onboarding-drafting rules; a descriptor is submitted as a `kind="onboarding"` proposal via `git_store` (T021); a limitation is logged (`limitation_reported`) and reported directly — never a partial/guessed integration (FR-018) (depends on T037, T021, T013)
- [ ] T039 [US4] `src/ops_agent/cli.py` — add `research-ops-agent onboard --provider-id --interface-doc` wiring `onboarding/draft.py` (depends on T038)
- [ ] T040 [P] [US4] `tests/integration/test_ops_agent_us4_onboarding.py` — present a not-yet-integrated vendor fixture; verify a pure-configuration onboarding proposal; approve it; verify ingestion/quality-check/full-cycle usage with zero new files under `ingestion/providers/`; separately present an unsupported-interface fixture (e.g. OAuth handshake auth) and verify an explicit `OnboardingLimitation` is reported (spec.md US4 Acceptance Scenarios 1–3) (depends on T039, T034)

**Checkpoint**: All user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T041 [P] `README.md` — add an ops-agent architecture overview section, pointer to `specs/002-research-ops-agent/quickstart.md`
- [ ] T042 [P] Ruff lint pass across `src/ops_agent/` and the touched `src/energy_research/` files; fix violations
- [ ] T043 Re-verify the Constitution Check table in `specs/002-research-ops-agent/plan.md` against the implemented code (walk all 8 principles); record any drift, mirroring 001 plan.md's post-implementation re-check
- [ ] T044 [P] `tests/unit/ops_agent/{discovery,proposals,onboarding,budget,scheduling}/` — unit-test coverage pass for logic not already exercised by contract/integration tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories.
- **User Story 1 (Phase 3)**: Depends only on Foundational. True MVP entry point.
- **User Story 2 (Phase 4)**: Extends `src/ops_agent/agent.py`'s `tick()`, built in Phase 3 (T023).
  **Requires User Story 1 complete first** — despite both being P1 in the spec ("equal-first
  priority"), this is a real implementation dependency (extending the same function), not just a
  shared-foundation one, exactly as 001's tasks.md flagged for its own extension relationships.
- **User Story 3 (Phase 5)**: Extends `src/ops_agent/proposals/git_store.py` (Phase 3, T021) and
  reads state `tick()` (Phase 3/4) produces. **Requires User Story 1 complete**; the full
  reconstruction scenario (T032) benefits from — but does not strictly require — User Story 2.
- **User Story 4 (Phase 6)**: Extends 001's `ingestion/registry.py`/`config/settings.py` (its own
  small, additive touch) and `ops_agent/proposals/`. **Requires User Story 1 complete** (reuses
  `git_store.py` and the proposal path built there); independent of US2/US3.
- **Polish (Phase 7)**: Depends on all desired user stories being complete.

### User Story Dependencies (implementation, not just acceptance)

- **US1 (P1)**: No dependency on other stories. True MVP.
- **US2 (P1)**: Extends US1's `agent.py` — build after US1, despite equal spec priority.
- **US3 (P2)**: Extends US1's `git_store.py` — build after US1.
- **US4 (P3)**: Extends US1's `git_store.py`/proposal path plus its own small 001 touch — build
  after US1; independent of US2 and US3.

### Within Each User Story

- Models/schemas before services.
- Services before `agent.py`/CLI wiring.
- CLI wiring before the story's integration test.

---

## Parallel Example: Phase 2 (Foundational)

After Phase 1 (Setup) is complete, these Phase 2 tasks touch disjoint files and share no
in-phase dependency, so they can run together:

```bash
Task: "ingestion/providers/sample_provider.py — add discover() (T005)"
Task: "ingestion/providers/secondary_market_provider.py — add discover() (T006)"
Task: "ingestion/providers/qualitative_context_provider.py — add discover() (T007)"
Task: "ops_agent/credentials.py — CredentialReference resolution (T009)"
```

Everything else in Phase 2 (T008, T010–T017) has an in-phase dependency (config before store
schema; store schema before repository; repository before budget/scheduling; boundary/audit/
budget contract tests after their subjects exist) and should follow in order.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories).
3. Complete Phase 3: User Story 1.
4. **STOP and VALIDATE**: run `research-ops-agent bootstrap` → approve → `research-ops-agent tick`
   against 001's sample providers; confirm every US1 acceptance scenario, with zero hand-written
   configuration.
5. This is a demonstrable, credentials-to-shortlist operation even before continuous cadence,
   full audit tooling, or config-only onboarding exist.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. Add User Story 1 → validate independently → MVP (a one-shot provisioned operation).
3. Add User Story 2 → validate independently → the operation runs unattended on a cadence.
4. Add User Story 3 → validate independently → change control and the audit trail are complete.
5. Add User Story 4 → validate independently → new vendors onboard without new code.

### Parallel Team Strategy

With multiple developers: complete Setup + Foundational together first (Phase 2's `discover()`
additions, T005–T007, can be split across developers trivially — disjoint files). User Stories 2,
3, and 4 all extend User Story 1's files directly, so — unlike 001's two truly-parallel P1
stories — sequence them after US1 lands; they can then proceed in parallel with each other once
US1 is done, since US2 (`agent.py`/scheduling), US3 (`git_store.py`/CLI `log`), and US4
(`onboarding/`, 001's `ingestion/registry.py`) touch largely disjoint files beyond that shared
base.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task in the same phase.
- [Story] label maps each task to its user story for traceability; Setup/Foundational/Polish tasks
  carry no story label by design.
- Contract tests (T015–T017, T036) exist to make FR-019's reach limit, FR-014's append-only audit
  log, FR-022's budget ceiling, and the declarative connector's protocol conformance
  build-breaking, not just documented — see plan.md's Constitution Check.
- T005–T007's `discover()` additions are the only Foundational-phase touch to existing 001
  provider files; they are additive (a new method) and change no existing behavior.
- T033–T035 are the only touches to 001's `config/settings.py` and `ingestion/registry.py` in the
  entire feature — both additive and backward compatible (data-model.md "Registry extension").
- Commit after each task or logical group.
- Stop at any checkpoint to validate a story independently before continuing.
- Avoid: cross-story dependencies beyond the documented US1→{US2,US3,US4} extension relationships;
  any code path from `ops_agent` into `energy_research.generation`/`screening`/`backtesting`/
  `critique`/`reporting`/`datastore.ledger` (contracts/ops-agent-boundary.md).
