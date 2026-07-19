"""SQLite schema for ``data/ops_agent.sqlite`` (data-model.md, research.md §3).

A second, purpose-built database — separate from 001's ``data/research.sqlite`` —
holding only the agent's own state. 001's schema is never touched.
"""

from __future__ import annotations

import sqlite3

DDL = """
-- Append-only audit trail (FR-014, contracts/activity-log-contract.md). No
-- UPDATE/DELETE statement against this table exists anywhere in ops_agent.
CREATE TABLE IF NOT EXISTS activity_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                   TEXT NOT NULL,
    action               TEXT NOT NULL CHECK (action IN
        ('discover', 'ingest', 'cycle_trigger', 'propose', 'remediate', 'escalate',
         'budget_blocked', 'checked_and_empty', 'notify_shortlist',
         'limitation_reported', 'credential_error')),
    target               TEXT NOT NULL,
    reason               TEXT NOT NULL,
    outcome              TEXT NOT NULL CHECK (outcome IN ('ok', 'failed', 'skipped')),
    related_proposal_id  TEXT
);

-- Index for status/listing only — the diff a reviewer sees is always the live git
-- diff, never duplicated here (proposal-lifecycle.md rule 1).
CREATE TABLE IF NOT EXISTS proposals (
    id                      TEXT PRIMARY KEY,
    kind                    TEXT NOT NULL CHECK (kind IN
        ('instrument_universe', 'data_source', 'onboarding', 'feed_schedule')),
    branch_name             TEXT NOT NULL,
    base_commit_sha         TEXT NOT NULL,
    target_files            TEXT NOT NULL,
    rationale               TEXT NOT NULL,
    discovery_evidence_ref  TEXT,
    status                  TEXT NOT NULL CHECK (status IN
        ('proposed', 'approved', 'edited_and_approved', 'rejected')),
    created_at              TEXT NOT NULL,
    decided_by              TEXT,
    decided_at              TEXT,
    applied_commit_sha      TEXT
);

-- period_key = the period's start timestamp truncated to `period` granularity, so
-- usage naturally resets when a new period begins (budget-contract.md rule 4).
CREATE TABLE IF NOT EXISTS resource_budget_usage (
    period_key            TEXT PRIMARY KEY,
    llm_calls_used        INTEGER NOT NULL DEFAULT 0,
    vendor_requests_used  INTEGER NOT NULL DEFAULT 0,
    exhausted_at          TEXT
);

-- One row per cadence kind: "is X due" = now - last_fired_at >= cadence.
CREATE TABLE IF NOT EXISTS operating_schedule_state (
    kind            TEXT PRIMARY KEY CHECK (kind IN
        ('cycle', 'market_refresh', 'qualitative_poll')),
    last_fired_at   TEXT,
    last_outcome    TEXT
);

-- What's already been ingested per qualitative feed, so a poll only picks up
-- genuinely new material (FR-007).
CREATE TABLE IF NOT EXISTS feed_watermarks (
    provider_id       TEXT NOT NULL,
    category          TEXT NOT NULL,
    last_seen_marker  TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (provider_id, category)
);

-- Index-only: the descriptor's YAML content lives in the onboarding proposal's git
-- branch (data-model.md DataSourceDescriptor).
CREATE TABLE IF NOT EXISTS data_source_descriptors (
    provider_id     TEXT PRIMARY KEY,
    proposal_id     TEXT NOT NULL REFERENCES proposals(id),
    connector_kind  TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    conn.commit()
