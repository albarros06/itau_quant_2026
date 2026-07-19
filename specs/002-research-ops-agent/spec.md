# Feature Specification: Autonomous Research Operations Agent

**Feature Branch**: `002-research-ops-agent`

**Created**: 2026-07-18

**Status**: Draft

**Input**: User description: "Autonomous research operations agent (layer above the 001 pipeline). A researcher provides only API keys (LLM provider, market-data vendors, news/climate/qualitative feeds — referenced by env-var name, never stored) plus risk-side configuration, and the system runs the entire research operation continuously with no further manual steps. An LLM-driven operations agent owns everything around the existing deterministic pipeline: discovers vendor offerings, provisions and maintains provider config and the instrument universe, keeps market and qualitative-context feeds ingested and fresh, triggers research cycles on a cadence, and surfaces the shortlist. Thesis ideation stays inside the pipeline; all agent-authored configuration changes are reviewable proposals a human approves; the agent's actions are auditable; no execution/broker/capital path exists anywhere."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - From credentials to a running research operation (Priority: P1)

A quant researcher who has just obtained access credentials for an LLM provider, one or
more market-data vendors, and one or more qualitative feeds (news, climate/hydrology
outlooks, macro commentary) hands those credentials to the system — by reference, never
by value — together with their risk-side parameters (statistical evidence standard,
cost/slippage/financing assumptions, refinement-loop bounds). Without writing any
configuration or integration by hand, the researcher receives a set of provisioning
proposals from the operations agent: which data series the configured vendors can supply,
which instruments should form the research universe, and how each feed will be brought in.
The researcher approves (or edits and approves) the proposals, and the system becomes a
fully operational research pipeline: data flows in, cycles run, and a shortlist report
arrives — with the researcher never having authored a config file or integration.

**Why this priority**: This is the feature's core promise — collapsing setup from
"engineer a data pipeline" to "supply keys and approve proposals". Without it, the
remaining stories have nothing to operate.

**Independent Test**: Provide credentials for at least one market-data vendor and one
qualitative feed against a fresh installation; verify the agent produces provisioning
proposals covering discoverable series and a candidate universe; approve them; verify
ingestion and a first research cycle complete and a shortlist report is produced, with
zero hand-written configuration.

**Acceptance Scenarios**:

1. **Given** valid credentials for a market-data vendor and a qualitative feed, **When**
   the researcher registers them (by reference) and starts the agent, **Then** the agent
   discovers what the vendors offer and produces provisioning proposals (data sources,
   instrument universe, feed schedules) for the researcher's review — without fetching
   beyond what discovery requires.
2. **Given** the researcher approves the provisioning proposals, **When** the agent
   applies them, **Then** ingestion, quality checks, and a first research cycle run to
   completion and a shortlist report is surfaced, with no further manual steps.
3. **Given** a credential that is invalid or lacks entitlements, **When** the agent
   attempts discovery, **Then** the failure is reported visibly to the researcher with
   the specific vendor and reason, and nothing is silently skipped.
4. **Given** the researcher rejects or edits a proposal, **When** the agent continues,
   **Then** only the approved content takes effect and the rejection is recorded.

---

### User Story 2 - Hands-off continuous operation (Priority: P1)

With the operation provisioned, the researcher steps away. The agent keeps the dataset
current on its own: it refreshes market series ahead of each cycle, watches the
qualitative feeds and picks up newly published material (for example, a new seasonal
climate outlook) without being asked, triggers research cycles on the configured cadence,
reads each cycle's report, and surfaces the resulting shortlist. When something blocks a
cycle — a stale feed, an unreachable vendor — the agent first attempts the obvious
remediation (re-ingest, retry) and escalates visibly to the researcher only when it
cannot restore normal operation. Thesis ideation remains entirely inside the pipeline:
the agent influences *what data and context exist*, never *which theses are proposed or
how they are judged*.

**Why this priority**: Equal-first priority — continuous unattended operation is the
"autonomous" in the feature's name. Setup (US1) without this still leaves a hand-cranked
pipeline.

**Independent Test**: With a provisioned operation, publish a new document to a
qualitative feed and advance time past the cycle cadence; verify the agent ingested the
new document unprompted, a new cycle ran on schedule, its report reflects the updated
context, and the shortlist was surfaced — with zero researcher interaction. Then make a
feed stale and verify the agent remediates or escalates rather than letting cycles fail
silently.

**Acceptance Scenarios**:

1. **Given** a provisioned operation and a configured cadence, **When** the cadence
   elapses, **Then** the agent refreshes required data and triggers a research cycle
   without any researcher action.
2. **Given** a qualitative feed publishes new material, **When** the agent next checks
   the feed, **Then** the material is ingested and available as context to the next
   cycle's thesis generation, unprompted.
3. **Given** required data is stale beyond tolerance at cycle time, **When** the agent's
   re-ingestion attempt restores freshness, **Then** the cycle proceeds; **When** it
   cannot, **Then** the cycle is not run on degraded data and the researcher is notified
   with the specific series and reason.
4. **Given** any completed cycle, **When** its report is produced, **Then** the agent
   surfaces the shortlist (and the full report location) to the researcher.
5. **Given** the agent has operated for any period, **When** the pipeline's cycle
   results are examined, **Then** every thesis was proposed by the pipeline's own
   generation stage and passed the unchanged screening, multiplicity, backtest, and
   spend-once gates — the agent introduced no thesis and altered no verdict.

---

### User Story 3 - Reviewable change control and a complete audit trail (Priority: P2)

A reviewing researcher (or a colleague who didn't set the system up) wants certainty
about what the agent has done and could do. Every configuration change the agent wants
to make — adding or removing instruments, registering a new data source, changing a feed
schedule — is presented as a human-readable, diffable proposal that takes effect only
after explicit approval; the operation meanwhile continues on the last approved
configuration. Every action the agent takes (discovery calls, ingestions, cycle
triggers, proposals, escalations) is durably logged with when, what, and why, so the
operation can be audited end to end. The agent has no mechanism to approve its own
proposals or to modify anything other than the pipeline's configuration and data inputs.

**Why this priority**: This is what makes autonomy trustworthy rather than merely
convenient, and it preserves the platform's governing principles (inspectable
configuration, constrained LLM autonomy). It is P2 only because it gates *changes*, not
first-time value.

**Independent Test**: Cause the agent to want a universe change (e.g., a vendor starts
offering a new relevant series); verify a diffable proposal is produced and the change
has no effect before approval; approve it and verify it takes effect and is visible in
the next cycle's recorded configuration; then inspect the activity log and reconstruct
the full sequence of agent actions for the period.

**Acceptance Scenarios**:

1. **Given** the agent determines a configuration change is warranted, **When** it acts,
   **Then** it produces a reviewable, diffable proposal and continues operating on the
   last approved configuration until a human decision is made.
2. **Given** a pending proposal, **When** the researcher approves it, **Then** it takes
   effect for subsequent cycles and the approval (who, when) is recorded; **When** the
   researcher rejects it, **Then** nothing changes and the rejection is recorded.
3. **Given** any window of operation, **When** an auditor inspects the activity log,
   **Then** every agent action in that window is present with timestamp, action,
   target, and stated reason — including failed attempts and escalations.
4. **Given** the agent's available mechanisms are enumerated, **When** checked against
   the pipeline, **Then** there exists no mechanism by which the agent can create or
   modify theses, verdicts, backtest results, ledger state, or reports — its reach ends
   at configuration proposals, data ingestion, and cycle triggering.

---

### User Story 4 - Config-only vendor onboarding (Priority: P3)

The researcher gains access to a new market-data vendor. Instead of waiting for a
developer to write a vendor integration, the vendor's interface (how to authenticate by
credential reference, how to request each series, how responses map to the pipeline's
canonical series shape) is captured entirely as configuration. The agent drafts that
configuration by inspecting the vendor's interface, submits it as a proposal, and — once
approved — the new vendor's data flows through the existing ingestion, cleaning, and
quality machinery with no new program code.

**Why this priority**: It multiplies the agent's usefulness and removes the last
recurring engineering task from the loop, but the operation is viable without it (the
initially provisioned vendors keep working).

**Independent Test**: Present a vendor interface not previously integrated; verify the
agent drafts an onboarding proposal that is pure configuration; approve it; verify series
from the new vendor are ingested, quality-checked, and usable in a full cycle with no
per-vendor program code added.

**Acceptance Scenarios**:

1. **Given** credentials for a not-yet-integrated vendor, **When** the agent inspects
   its interface, **Then** it produces an onboarding proposal expressed entirely as
   configuration (authentication by credential reference, series addressing, field
   mapping).
2. **Given** the proposal is approved, **When** ingestion next runs, **Then** the new
   vendor's series arrive through the same cleaning and quality-check path as existing
   vendors, carrying correct provenance and freshness.
3. **Given** a vendor interface the configuration language cannot express, **When** the
   agent attempts onboarding, **Then** it reports the specific limitation rather than
   producing a partial or guessed integration.

---

### Edge Cases

- **Invalid or expired credentials**: discovery/ingestion fails loudly, naming the vendor
  and reason; the agent never retries indefinitely nor silently drops the source.
- **Vendor changes its interface mid-operation**: ingestion failures surface as
  escalations with the affected series; the agent may propose an updated onboarding
  configuration, which follows the normal approval path.
- **Pending proposal at cycle time**: cycles keep running on the last approved
  configuration; a proposal never blocks the operation nor takes effect early.
- **Researcher unavailable for approvals**: the operation continues indefinitely on the
  approved configuration; proposals queue and never auto-approve, regardless of age.
- **No new qualitative material found**: a normal outcome, logged as a checked-and-empty
  poll, not an error or a reason to skip the cycle.
- **LLM provider outage**: operations that need the LLM (discovery interpretation,
  proposal drafting, in-pipeline thesis generation) fail visibly and are retried on the
  next scheduled occasion; already-approved configuration and scheduled ingestion of
  already-onboarded sources continue unaffected.
- **Resource-consumption runaway**: agent activity (LLM calls, vendor requests) is
  bounded by configurable per-period budgets; reaching a budget halts further
  discretionary agent activity for the period and notifies the researcher, rather than
  spending without limit.
- **Attempt to exceed reach**: any attempted agent action outside its permitted surface
  (configuration proposals, data ingestion, cycle triggering, reading reports) must be
  structurally impossible, not merely prohibited by instruction.

## Requirements *(mandatory)*

### Functional Requirements

#### Setup & provisioning

- **FR-001**: The system MUST accept vendor and LLM credentials by reference (e.g., the
  name of an environment variable) and MUST NOT store, display, or log credential
  values anywhere.
- **FR-002**: The agent MUST be able to discover, for each configured vendor, what data
  series and qualitative material that vendor can supply to the operation.
- **FR-003**: From discovery results, the agent MUST produce provisioning proposals
  covering: data sources to onboard, the instrument universe, and feed refresh
  schedules — each expressed as reviewable configuration.
- **FR-004**: No provisioning content may take effect without explicit researcher
  approval; the researcher MUST be able to edit a proposal before approving it.
- **FR-005**: After approval, the system MUST reach fully operational state (data
  ingested, first cycle completed, shortlist surfaced) with no further manual steps.

#### Continuous operation

- **FR-006**: The agent MUST refresh required market data ahead of each scheduled cycle
  and MUST trigger research cycles on a configurable cadence without human action.
- **FR-007**: The agent MUST poll qualitative feeds on a configurable schedule and
  ingest newly published material unprompted, making it available as context to
  subsequent thesis generation.
- **FR-008**: When a cycle is blocked (stale or missing data, unreachable vendor), the
  agent MUST attempt bounded automatic remediation and MUST escalate visibly to the
  researcher when remediation fails; it MUST NOT run a cycle on data the pipeline deems
  unfit.
- **FR-009**: After each completed cycle, the agent MUST surface the shortlist and the
  full report's location to the researcher.
- **FR-010**: The agent MUST NOT propose, author, select, edit, or re-rank theses, and
  MUST NOT alter screening, backtesting, evaluation-ledger, or reporting behavior; its
  influence on research results is limited to which approved data and context exist.

#### Change control & audit

- **FR-011**: Every agent-initiated configuration change (universe, data sources, feeds,
  schedules) MUST be expressed as a human-readable, diffable proposal and MUST have no
  effect until a human approves it.
- **FR-012**: The system MUST record every proposal with its content, rationale, and
  outcome (approved / edited-and-approved / rejected), including who decided and when.
- **FR-013**: The agent MUST NOT be able to approve, edit, or apply its own proposals.
- **FR-014**: Every agent action — discovery, ingestion, cycle trigger, proposal,
  remediation, escalation, budget event — MUST be durably logged with timestamp, action,
  target, and stated reason, and the log MUST be retrievable by a reviewer.
- **FR-015**: The configuration in effect for any given research cycle MUST be exactly
  the last approved configuration at that cycle's start, and MUST remain reconstructable
  afterward (preserving the pipeline's recorded-snapshot reproducibility).

#### Vendor onboarding

- **FR-016**: The system MUST support onboarding a new market-data or qualitative vendor
  through configuration alone — authentication by credential reference, series
  addressing, response-to-canonical-shape mapping — with no per-vendor program code.
- **FR-017**: The agent MUST be able to draft such onboarding configuration by
  inspecting a vendor's interface, submitting it through the normal proposal path.
- **FR-018**: Where a vendor's interface cannot be expressed in the onboarding
  configuration language, the agent MUST report the specific limitation rather than
  produce a partial or speculative integration.

#### Boundaries, safety & resource control

- **FR-019**: The agent's permitted surface MUST be structurally limited to:
  configuration proposals, data ingestion, cycle triggering, and reading pipeline
  outputs. No mechanism may exist for the agent to write theses, verdicts, results,
  ledger state, or reports.
- **FR-020**: All pipeline guarantees from feature 001 (discovery-only screening with
  mandatory multiplicity control, cost-honest backtests, spend-once-per-lineage final
  evaluation, synthetic-data labeling, fail-loud data quality, reproducible cycles)
  MUST hold unchanged under agent operation.
- **FR-021**: The system MUST NOT create any path to order placement, capital
  commitment, or broker/execution connectivity (identical to 001's exclusion).
- **FR-022**: Agent resource consumption (LLM usage, vendor requests) MUST be bounded by
  configurable per-period budgets; exhausting a budget MUST halt further discretionary
  agent activity for the period and notify the researcher.

### Key Entities

- **Operations Agent**: the autonomous actor that discovers, provisions, maintains, and
  operates; identified in every log entry and proposal it produces.
- **Credential Reference**: a pointer (by name) to a secret held outside the system;
  carries which vendor/service it is for, never the secret value.
- **Data Source Descriptor**: the configuration-only description of one vendor
  integration — authentication reference, series addressing, mapping to the canonical
  series shape, refresh schedule.
- **Provisioning / Configuration Change Proposal**: a human-readable, diffable proposed
  change to universe, sources, feeds, or schedules; carries rationale; lifecycle:
  proposed → approved / edited-and-approved / rejected.
- **Approval Decision**: the recorded human ruling on a proposal (who, when, outcome,
  final applied content).
- **Agent Activity Log Entry**: one durable record of an agent action — timestamp,
  action, target, reason, outcome.
- **Operating Schedule**: the configured cadences — cycle trigger, market refresh,
  qualitative polling.
- **Resource Budget**: configurable per-period ceilings on agent LLM usage and vendor
  requests, with consumption tracking and exhaustion events.
- **Shortlist Notification**: the surfaced summary of a completed cycle — promoted
  theses and the full report's location.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Starting from credentials only, a researcher reaches a completed first
  research cycle and shortlist having authored zero configuration by hand — their only
  inputs are credential references, risk parameters, and proposal approvals.
- **SC-002**: 100% of agent-initiated configuration changes pass through an explicit
  human approval before taking effect; zero configuration changes take effect
  unapproved, over any audit window.
- **SC-003**: 100% of agent actions in any audited window are present in the activity
  log with timestamp, target, and reason; an auditor can reconstruct the full sequence
  without access to the agent's internals.
- **SC-004**: New qualitative material published by a configured feed is available as
  context to the next scheduled research cycle in at least 95% of occurrences, with no
  researcher involvement.
- **SC-005**: A new data vendor is onboarded to first successful ingestion via an
  approved configuration-only proposal, with zero new per-vendor program code.
- **SC-006**: Over a representative month of operation, the researcher's total required
  interaction is limited to reviewing proposals and reading shortlists — no data
  wrangling, no configuration authoring, no manual cycle triggering.
- **SC-007**: Replaying any cycle from its recorded configuration and seed reproduces
  identical results regardless of any agent activity before or after — demonstrating
  the agent has no channel into research outcomes.
- **SC-008**: All of feature 001's success criteria continue to pass unchanged while the
  operation is agent-run.
- **SC-009**: 100% of blocked cycles (stale data, unreachable vendor) end in either
  successful automatic remediation or a visible escalation; none are silently skipped
  and none run on unfit data.
- **SC-010**: Agent resource budgets are never exceeded; every budget exhaustion event
  produces a researcher notification.

## Assumptions

- **The 001 pipeline is the unchanged substrate.** This feature operates the existing
  pipeline through its public entry points and configuration; it does not modify the
  pipeline's research logic, and thesis ideation remains the pipeline generation stage's
  job.
- **The agent runs as scheduled, resumable activity rather than requiring a permanently
  resident service** — consistent with the platform's simplicity principle; "continuous"
  means the researcher experiences uninterrupted operation, not that a process must
  never exit.
- **While a proposal awaits decision, the last approved configuration governs.**
  Proposals queue indefinitely and never auto-approve.
- **Approval and notification channels are deliberately unspecified** at this level; any
  medium that presents a diffable proposal and records an attributable decision
  satisfies the spec. The initial reviewer set is assumed to be the researcher(s)
  operating the platform, without a separate role/permission system.
- **Vendor discovery is limited to what configured credentials legitimately expose.**
  The agent does not search for or suggest vendors the researcher has not provided
  credentials for.
- **Reasonable defaults for cadences and budgets exist in configuration** and are risk
  parameters the researcher sets once at setup (and may later change like any other
  approved configuration).
- **The interactive dashboard remains a separate future feature**; this feature's
  surfacing obligations are met by notifications plus the pipeline's report artifacts.

## Out of Scope

- Placing, routing, or simulating orders; committing or allocating capital; any broker
  or execution-venue connectivity (unchanged from 001).
- Agent-authored theses, agent-curated shortlists, or any agent influence on screening,
  backtesting, evaluation, or reporting logic.
- Automatic (human-free) approval of configuration changes, including "auto-approve
  after a timeout" behavior.
- Modifying the 001 pipeline's statistical methodology, split discipline, or ledger
  semantics.
- Sourcing or recommending data vendors beyond those the researcher has supplied
  credentials for.
- The interactive review dashboard (separate feature).
