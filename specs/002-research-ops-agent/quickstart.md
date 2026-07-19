# Quickstart: Autonomous Research Operations Agent

This describes how the ops agent is operated once implemented (`/speckit-tasks` +
`/speckit-implement`). It is the reference for each user story's independent test and for
`tests/integration/test_ops_agent_us*.py`. It assumes 001's pipeline is already installed
(`research-pipeline` on PATH) — see [001's quickstart](../001-auto-research-pipeline/quickstart.md).

## 0. Deployment prerequisite: separate git identities

Because approval is a `git merge` performed by a credential the agent does not hold
(contracts/proposal-lifecycle.md), set this up once before running the agent unattended:

- The **scheduled agent process** runs under a git identity/credential (deploy key, scoped token,
  or simply a machine account) that can `push` to `ops-proposal/*` branches only — no write access
  to the operating branch (`main`, or whatever `config/ops_agent.yaml`'s `git.operating_branch`
  names).
- The **researcher**, reviewing and running `research-ops-agent approve|reject` interactively,
  uses their own normal git identity, which does have merge rights on the operating branch.

For local/single-user development this can be as simple as: the agent's cron job runs with
`GIT_AUTHOR_NAME`/`GIT_COMMITTER_NAME` set to `ops-agent` and no branch-protection bypass, while
the researcher merges by hand from their own shell.

## 1. Provide credentials and risk parameters (User Story 1)

Nothing here is a secret value — only environment-variable *names* (FR-001):

```bash
export ANTHROPIC_API_KEY=...
export MARKET_VENDOR_API_KEY=...
export NEWS_FEED_API_KEY=...
```

```yaml
# config/ops_agent.yaml
pipeline_config_path: config/default.yaml

llm:
  api_key_env: ANTHROPIC_API_KEY
  model: claude-opus-4-8

operating_schedule:
  cycle_cadence_hours: 24
  market_refresh_cadence_hours: 6
  qualitative_poll_cadence_hours: 2

resource_budgets:
  period: daily
  max_llm_calls: 200
  max_vendor_requests: 1000

git:
  proposal_branch_prefix: ops-proposal/
  operating_branch: main

notifications:
  sink: file
  path: data/ops_agent/notifications.jsonl
```

Risk-side parameters (statistical evidence standard, cost/slippage/financing assumptions,
refinement-loop bounds) are 001's existing `screening`/`backtesting`/`refinement` sections in
`config/default.yaml` — set them there once at setup; later changes go through the same proposal
path as any agent-drafted change (research.md §6).

Register vendor credentials by reference in `config/providers.yaml`, same shape 001 already uses
(`api_key_env`, never a value).

## 2. Bootstrap: discovery → provisioning proposals

```bash
research-ops-agent bootstrap --config config/ops_agent.yaml
```

For each configured vendor: calls `discover()` (research.md §5), interprets the catalog via the
LLM into schema-validated draft proposals, and opens one or more `ops-proposal/*` branches
covering data sources, instrument universe, and feed schedules (FR-002/003). A vendor with
invalid/missing credentials fails loudly, naming the vendor and reason (Edge Case), and does not
block proposals for the other configured vendors.

## 3. Review and approve (User Story 3)

```bash
git fetch && git diff main ops-proposal/universe-a1b2c3d4
```

Human-readable, diffable YAML — edit the branch directly if the proposal needs changes, then:

```bash
research-ops-agent approve ops-proposal/universe-a1b2c3d4    # or: reject <id>
```

This performs the merge into `main` as the researcher's own git identity and records
`decided_by`/`decided_at`/`applied_commit_sha` from the resulting merge commit
(contracts/proposal-lifecycle.md). Until this runs, cycles keep operating on whatever was
approved before — a pending proposal has zero effect (Edge Case).

## 4. First operational cycle (User Story 1, continued)

Approving the initial provisioning proposals is enough — no further hand-authored config:

```bash
research-ops-agent tick --config config/ops_agent.yaml
```

A single `tick` (idempotent, bounded pass) will, if due: refresh market data, poll qualitative
feeds, and trigger `research-pipeline run-cycle` under the hood — surfacing the shortlist and
report path via `notify()` (FR-005/009). Independent Test for User Story 1: this sequence,
starting from credentials only, reaches a completed cycle and shortlist with zero hand-written
configuration.

## 5. Continuous operation (User Story 2)

In production, an external scheduler invokes `tick` every few minutes:

```cron
*/10 * * * * research-ops-agent tick --config /path/to/config/ops_agent.yaml
```

Each invocation only acts on what's due per `operating_schedule` (data-model.md
`OperatingScheduleState`); most invocations are a fast no-op. Independent Test for User Story 2:
publish new material to a configured qualitative feed, then run enough `tick` invocations to
cross both the poll cadence and the cycle cadence — verify the new material appears in the next
cycle's context (FR-007) without any researcher action, and that a subsequent stale-data scenario
either self-remediates (`remediate` → restored freshness → cycle proceeds) or escalates
(`escalate`, visible via `research-ops-agent log` and the notification sink) rather than running
on unfit data or failing silently.

## 6. Auditing (User Story 3, continued)

```bash
research-ops-agent log --since 2026-07-19T00:00:00 --until 2026-07-20T00:00:00
```

Prints every agent action in the window — discovery calls, ingestions, cycle triggers, proposals,
remediations, escalations, budget events — each with timestamp, action, target, and reason
(FR-014). Combined with `git log --all --grep=<proposal-id>` for proposal history, an auditor
reconstructs the full sequence without touching `ops_agent`'s internals (SC-003).

## 7. Onboarding a new vendor with zero new code (User Story 4)

```bash
export NEW_VENDOR_API_KEY=...
research-ops-agent onboard --provider-id new_vendor --config config/ops_agent.yaml \
  --interface-doc path/to/vendor-api-notes.md
```

Drafts a `DataSourceDescriptor` (contracts/declarative-connector.md) and opens it as an
`ops-proposal/*` branch touching only `config/providers.yaml`. Approve it exactly as in step 3;
on the next `ingest`, `new_vendor`'s series flow through the same cleaning/quality path as every
other provider, with no `.py` file added under `ingestion/providers/`. If the vendor's interface
can't be expressed by the descriptor (contracts/declarative-connector.md "Onboarding-drafting
rules"), `onboard` reports the specific limitation instead of a guessed integration (FR-018).

## 8. Verifying independently, before live vendors

Every step above works against 001's existing synthetic `sample_provider`/`sample_news_provider`
with no live credentials — `tests/integration/test_ops_agent_us*.py` exercise exactly this
sequence, matching how 001's own quickstart §5 verifies User Story 1 before live providers exist.
Any artifact produced from synthetic data still carries `provenance: synthetic` end to end
(Constitution Principle IV) — unchanged from 001, since `ops_agent` never touches provenance
logic.
