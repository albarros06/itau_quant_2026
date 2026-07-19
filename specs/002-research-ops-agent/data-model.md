# Phase 1 Data Model: Autonomous Research Operations Agent

All models are `pydantic` `StrictModel`s (`extra="forbid"`), matching 001's config/schema
discipline. Entities marked **(config)** live in `config/ops_agent.yaml` and are loaded once per
`tick`; entities marked **(store)** are rows in `data/ops_agent.sqlite` (research.md §3); entities
marked **(git)** are represented by git branches/commits, with only an index row in the store.
Entities marked **(001, extended)** are additive fields on 001's existing config schema (its
provider registry), not new tables.

## OpsAgentConfig **(config)**

The root of `config/ops_agent.yaml`.

| Field | Type | Notes |
|---|---|---|
| `pipeline_config_path` | path | Points at 001's `config/default.yaml` (FR-015 target). |
| `llm` | `LlmConfig` | `api_key_env: str`, `model: str`. Credential by reference only (FR-001). |
| `operating_schedule` | `OperatingSchedule` | See below. |
| `resource_budgets` | `ResourceBudgetConfig` | See below. |
| `git` | `GitConfig` | `proposal_branch_prefix: str = "ops-proposal/"`, `operating_branch: str = "main"`, `remote: str \| None`. |
| `notifications` | `NotificationConfig` | `sink: Literal["file"] = "file"`, `path: Path = data/ops_agent/notifications.jsonl`. |

## CredentialReference **(config, embedded)**

Not a standalone table — embedded wherever a vendor/LLM credential is referenced (provider
entries, `OpsAgentConfig.llm`).

| Field | Type | Notes |
|---|---|---|
| `env_var_name` | str | Name only. Resolving a missing/empty env var at startup is a visible `CredentialError`, never a silent skip (FR-001, Edge Case: invalid credentials). |
| `purpose` | `Literal["llm", "market_data", "qualitative_context"]` | For log/proposal display only. |

The value itself is never a model field anywhere in `ops_agent` — it is read from `os.environ`
at the point of use and passed straight to the connector/LLM transport, never assigned to a
variable that could be logged, serialized into a proposal, or written to `ops_agent.sqlite`.

## OperatingSchedule **(config)**

| Field | Type | Notes |
|---|---|---|
| `cycle_cadence_hours` | float, `> 0` | How often `tick` should trigger `run_cycle`. |
| `market_refresh_cadence_hours` | float, `> 0` | How often `tick` should refresh market series ahead of a cycle (FR-006). |
| `qualitative_poll_cadence_hours` | float, `> 0` | How often `tick` should poll qualitative feeds (FR-007). |

Runtime "when did each of these last actually fire" state is `OperatingScheduleState` **(store)**:
one row per cadence kind — `(kind, last_fired_at, last_outcome)`. `scheduling.py` computes "is X
due" as `now - last_fired_at >= cadence`; a tick where nothing is due does no work and logs a
`checked_and_empty` activity entry (Edge Case: "no new qualitative material").

## ResourceBudgetConfig **(config)** / ResourceBudgetUsage **(store)**

| Field | Type | Notes |
|---|---|---|
| `period` | `Literal["hourly","daily"]` | Reset cadence for the counters below. |
| `max_llm_calls` | int, `>= 0` | Discretionary LLM calls only (research.md §9). |
| `max_vendor_requests` | int, `>= 0` | Discretionary discovery/probe requests only. |

`ResourceBudgetUsage` (store): `(period_key, llm_calls_used, vendor_requests_used,
exhausted_at: datetime | None)`. `period_key` is the period's start timestamp truncated to
`period` granularity, so usage naturally resets when a new period begins. Exhaustion sets
`exhausted_at` once and is idempotent; every increment attempt after exhaustion is itself logged
(action=`budget_blocked`) rather than silently no-op'd.

## FeedWatermark **(store)**

Tracks "what's already been ingested" per qualitative feed, so `tick` only picks up genuinely new
material (FR-007, US2 Independent Test).

| Field | Type | Notes |
|---|---|---|
| `provider_id` | str | Matches `providers.yaml` entry. |
| `category` | str | `news` \| `hydrology_outlook` \| `macro_regime` \| ... |
| `last_seen_marker` | str | Provider-native cursor or max-timestamp-seen; opaque to `ops_agent`. |
| `updated_at` | datetime | Last successful poll. |

## DataSourceDescriptor **(git-proposed, store-indexed)**

The FR-016 config-only vendor-onboarding artifact. Lives as YAML inside a `providers.yaml`
proposal (research.md §4/§7); the store keeps only an index for status tracking.

| Field | Type | Notes |
|---|---|---|
| `provider_id` | str | New or existing vendor id. |
| `connector_kind` | `Literal["python_module","declarative"]` | `declarative` routes to the shared connector (research.md §4). |
| `credential` | `CredentialReference` | |
| `base_url` | str | |
| `endpoints` | `list[EndpointSpec]` | One per `(category, ...)` pair the vendor supports. |
| `pagination` | `PaginationSpec` | `mode: Literal["none","offset","cursor"]` + named parameters. |

`EndpointSpec`: `category: str`, `path_template: str`, `method: Literal["GET","POST"] = "GET"`,
`field_mapping: dict[str, str]` — canonical field name → JMESPath expression evaluated against
one response element (e.g. `{"instrument_key": "id", "ts": "timestamp", "value": "price.last"}`).

`OnboardingLimitation` (not persisted as a proposal — returned directly to the researcher via a
`limitation_reported` activity-log entry, FR-018): `provider_id: str`, `reason: str`,
`unsupported_aspect: Literal["auth","pagination","field_mapping","transport"]`.

## ProvisioningProposal **(git-proposed, store-indexed)**

The general-purpose change-control unit for universe/data-source/feed-schedule changes (FR-011),
and the container `DataSourceDescriptor` onboarding proposals are submitted through.

Store row (`proposals` table):

| Field | Type | Notes |
|---|---|---|
| `id` | str (uuid) | |
| `kind` | `Literal["instrument_universe","data_source","onboarding","feed_schedule"]` | |
| `branch_name` | str | `ops-proposal/<slug>-<id[:8]>` (research.md §7). |
| `base_commit_sha` | str | Operating-branch commit this was branched from. |
| `target_files` | `list[str]` | e.g. `["config/default.yaml"]`. |
| `rationale` | str | Human-readable; also the git commit message body. |
| `discovery_evidence_ref` | str \| None | Pointer to the discovery run that produced this (log correlation, not a foreign key into vendor data). |
| `status` | `Literal["proposed","approved","edited_and_approved","rejected"]` | |
| `created_at` | datetime | |
| `decided_by` | str \| None | Git committer identity of the merge commit (§7) — populated on decision, never set by the agent. |
| `decided_at` | datetime \| None | |
| `applied_commit_sha` | str \| None | The merge commit sha, once approved. |

The authoritative diff is always `git diff <base_commit_sha> <branch_name>` — never duplicated as
text in the store, so it cannot drift from what a reviewer actually sees (research.md §7).

## ApprovalDecision

Not a separate table — it *is* the transition of a `ProvisioningProposal` from `proposed` to
`approved`/`edited_and_approved`/`rejected`, recorded by updating the four `decided_*`/`status`/
`applied_commit_sha` fields above at the moment `research-ops-agent approve|reject` observes the
git state change. "Who" and "when" are read from the merge commit's git metadata, never entered
by hand — this is what makes FR-012's "who decided" attributable without a separate identity
system (research.md §7).

## AgentActivityLogEntry **(store, append-only)**

One row per agent action (FR-014). No `UPDATE`/`DELETE` statement exists against this table
anywhere in `ops_agent` (contracts/activity-log-contract.md) — enforced by a contract test, not
just by discipline.

| Field | Type | Notes |
|---|---|---|
| `id` | int (autoincrement) | |
| `ts` | datetime | |
| `action` | `Literal["discover","ingest","cycle_trigger","propose","remediate","escalate","budget_blocked","checked_and_empty","notify_shortlist","limitation_reported","credential_error"]` | |
| `target` | str | Provider id, series key, proposal id, or cycle id, as applicable. |
| `reason` | str | Always populated — "why", not just "what" (FR-014). |
| `outcome` | `Literal["ok","failed","skipped"]` | |
| `related_proposal_id` | str \| None | Foreign key into `proposals.id` when the action concerns one. |

SC-003's audit reconstruction is: `SELECT * FROM activity_log WHERE ts BETWEEN ? AND ? ORDER BY
ts`, exposed via `research-ops-agent log --since --until`.

## ShortlistNotification (logical, not a table)

Realized as an `AgentActivityLogEntry` with `action="notify_shortlist"`, `target=<cycle_id>`, and
a `notify()` call (research.md §8) carrying `{cycle_id, promoted_thesis_ids, report_path}` —
sourced directly from 001's `CycleResult` (`orchestration/cycle.py`), never re-derived. No
separate table: the activity log already gives it a durable, queryable record, and a second
representation would only risk drifting from what `run_cycle` actually returned (Principle
VIII).

## Registry extension: `connector_kind` **(001, extended)**

`energy_research.config.settings.MarketProviderEntry` / `ContextProviderEntry` gain one optional
field, backward compatible with every existing entry:

| Field | Type | Notes |
|---|---|---|
| `connector_kind` | `Literal["python_module","declarative"] = "python_module"` | Default preserves 001's exact current behavior (module named after `provider_id`). `declarative` routes to `ingestion/providers/declarative.py` with the `DataSourceDescriptor` carried in `options`. |

This is the only field added to 001's schema by this feature (research.md §4); every other
`PipelineConfig` section is untouched.
