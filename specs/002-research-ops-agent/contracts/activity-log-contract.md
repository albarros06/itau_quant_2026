# Contract: Agent Activity Log

Implements FR-014 and SC-003.

## Required fields (data-model.md `AgentActivityLogEntry`)

Every row MUST carry: `ts`, `action`, `target`, `reason`, `outcome`. No code path may insert a row
missing any of these — the store's `record_activity(...)` function takes them as required
(non-optional) positional/keyword arguments, so a caller cannot omit `reason` and still compile.

## Contract rules

1. **Append-only.** `ops_agent/store/repository.py` exposes `record_activity(...)` (INSERT only)
   and `read_activity(since, until)` (SELECT only) for this table. No `UPDATE`/`DELETE` statement
   against `activity_log` exists anywhere in `ops_agent`. A contract test greps the codebase for
   any SQL touching `activity_log` and asserts it is exclusively `INSERT`/`SELECT`.
2. **Every category of agent action is covered**, per the `action` enum: `discover`, `ingest`,
   `cycle_trigger`, `propose`, `remediate`, `escalate`, `budget_blocked`, `checked_and_empty`,
   `notify_shortlist`, `limitation_reported`, `credential_error`. In particular:
   - **Failed attempts are logged**, not just successes (`outcome="failed"`) — e.g. a remediation
     retry that didn't restore freshness, or a credential that failed discovery.
   - **A normal empty poll is logged as `checked_and_empty`**, not silently skipped and not an
     error (Edge Case: "No new qualitative material found").
   - **Escalations are logged with the specific series/vendor and reason**, not a generic
     "something failed" message (Edge Case: "Invalid or expired credentials").
3. **Retrievable by a reviewer without internals access.** `research-ops-agent log --since <ts>
   [--until <ts>] [--action <kind>]` prints every matching row in chronological order; this is the
   only sanctioned read path and requires no direct SQLite access, no code, and no knowledge of
   `ops_agent`'s internal structure (SC-003: "an auditor can reconstruct the full sequence without
   access to the agent's internals").
4. **Correlates with proposals without duplicating them.** `related_proposal_id` links a
   `propose`/`escalate` row to a `proposals.id` (data-model.md); the log never re-stores the
   proposal's diff or rationale — those live once, in git (proposal-lifecycle.md).
5. **No credential values.** `target`/`reason` fields MUST NEVER contain a resolved credential
   value — only vendor/provider ids and env-var *names* — enforced by the same discipline as
   FR-001; a contract test asserts no activity-log write path receives a raw credential value as
   an argument (the credential-resolution function's return value is typed to never reach
   `record_activity`).
