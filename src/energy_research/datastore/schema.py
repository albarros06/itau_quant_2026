"""SQLite schema for all structured/relational state (data-model.md).

The evaluation ledger's spend-once guarantee and the backtest cost-honesty rule are
expressed as database constraints (UNIQUE primary key + NOT NULL cost columns), so
violating them is a database error, not a code-review finding.
"""

from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS data_series (
    series_id      TEXT PRIMARY KEY,
    category       TEXT NOT NULL,
    instrument_key TEXT NOT NULL,
    provider_id    TEXT NOT NULL,
    provenance     TEXT NOT NULL CHECK (provenance IN ('real', 'synthetic')),
    freshness_ts   TEXT NOT NULL,
    ingested_at    TEXT NOT NULL,
    storage_ref    TEXT NOT NULL,
    quality_status TEXT NOT NULL CHECK (quality_status IN ('clean', 'flagged', 'stale'))
);

CREATE TABLE IF NOT EXISTS data_quality_records (
    record_id   TEXT PRIMARY KEY,
    series_id   TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    issue_type  TEXT NOT NULL CHECK (issue_type IN
        ('gap', 'outlier', 'stale_feed', 'schema_mismatch', 'misconfiguration')),
    intervention TEXT NOT NULL CHECK (intervention IN
        ('none_raised', 'gap_fill', 'correction', 'fallback', 'rejected')),
    detail      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_cycles (
    cycle_id        TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    config_snapshot TEXT NOT NULL,
    seed            INTEGER NOT NULL,
    max_refinement_depth      INTEGER NOT NULL,
    max_lineages_or_iterations INTEGER NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS thesis_lineages (
    lineage_id       TEXT PRIMARY KEY,
    cycle_id         TEXT NOT NULL REFERENCES research_cycles(cycle_id),
    root_thesis_id   TEXT NOT NULL,
    refinement_depth INTEGER NOT NULL DEFAULT 0
);

-- One row per lineage (never per thesis): the transactional spend-once gate (FR-019).
CREATE TABLE IF NOT EXISTS evaluation_ledger (
    lineage_id          TEXT PRIMARY KEY REFERENCES thesis_lineages(lineage_id),
    spent               INTEGER NOT NULL DEFAULT 0 CHECK (spent IN (0, 1)),
    spent_by_thesis_id  TEXT,
    spent_at            TEXT
);

-- Durable record of every refused reuse attempt (Edge Case: reuse of spent period).
CREATE TABLE IF NOT EXISTS ledger_refusals (
    refusal_id           TEXT PRIMARY KEY,
    lineage_id           TEXT NOT NULL,
    attempted_thesis_id  TEXT NOT NULL,
    attempted_at         TEXT NOT NULL,
    detail               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_theses (
    thesis_id        TEXT PRIMARY KEY,
    lineage_id       TEXT NOT NULL REFERENCES thesis_lineages(lineage_id),
    parent_thesis_id TEXT REFERENCES trading_theses(thesis_id),
    cycle_id         TEXT NOT NULL REFERENCES research_cycles(cycle_id),
    iteration_index  INTEGER NOT NULL DEFAULT 0,
    rationale        TEXT NOT NULL,
    hypothesis       TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN
        ('proposed', 'invalid_schema', 'screened_rejected', 'screened_passed',
         'backtested', 'rejected_underperform', 'final_evaluation_pending',
         'promoted', 'rejected_after_final', 'refused')),
    status_reason    TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_split_allocations (
    allocation_id    TEXT PRIMARY KEY,
    cycle_id         TEXT NOT NULL REFERENCES research_cycles(cycle_id),
    split_type       TEXT NOT NULL CHECK (split_type IN
        ('discovery', 'refinement', 'final_evaluation')),
    date_range_start TEXT NOT NULL,
    date_range_end   TEXT NOT NULL,
    instrument_scope TEXT NOT NULL,
    UNIQUE (cycle_id, split_type)
);

CREATE TABLE IF NOT EXISTS screening_results (
    result_id           TEXT PRIMARY KEY,
    thesis_id           TEXT NOT NULL REFERENCES trading_theses(thesis_id),
    method              TEXT NOT NULL,
    statistic_value     REAL NOT NULL,
    p_value             REAL NOT NULL,
    multiplicity_method TEXT NOT NULL,
    adjusted_threshold  REAL NOT NULL,
    verdict             TEXT NOT NULL CHECK (verdict IN ('pass', 'fail')),
    reason              TEXT NOT NULL,
    other_metrics       TEXT NOT NULL DEFAULT '{}',
    evaluated_at        TEXT NOT NULL
);

-- Cost columns are NOT NULL: a gross-only result cannot be persisted (Principle IV).
CREATE TABLE IF NOT EXISTS backtest_results (
    result_id         TEXT PRIMARY KEY,
    thesis_id         TEXT NOT NULL REFERENCES trading_theses(thesis_id),
    split_type        TEXT NOT NULL CHECK (split_type IN ('refinement', 'final_evaluation')),
    gross_return      REAL NOT NULL,
    transaction_costs REAL NOT NULL,
    slippage          REAL NOT NULL,
    financing_carry   REAL NOT NULL,
    net_return        REAL NOT NULL,
    other_metrics     TEXT NOT NULL DEFAULT '{}',
    evaluated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS critiques (
    critique_id           TEXT PRIMARY KEY,
    thesis_id             TEXT NOT NULL REFERENCES trading_theses(thesis_id),
    weaknesses            TEXT NOT NULL,
    suggested_direction   TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    feeds_iteration_index INTEGER NOT NULL
);

-- Normalized qualitative-context documents (news / hydrology outlook / macro regime),
-- persisted at ingestion so generation reads them from the datastore only.
CREATE TABLE IF NOT EXISTS context_docs (
    doc_id      TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    category    TEXT NOT NULL,
    source      TEXT NOT NULL,
    doc_ts      TEXT NOT NULL,
    text        TEXT NOT NULL,
    provenance  TEXT NOT NULL CHECK (provenance IN ('real', 'synthetic')),
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_reports (
    report_id      TEXT PRIMARY KEY,
    cycle_id       TEXT NOT NULL REFERENCES research_cycles(cycle_id),
    generated_at   TEXT NOT NULL,
    thesis_entries TEXT NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    _migrate_screening_results_other_metrics(conn)
    conn.commit()


def _migrate_screening_results_other_metrics(conn: sqlite3.Connection) -> None:
    """Idempotently add screening_results.other_metrics to pre-003 databases.

    Fresh databases already get the column from the CREATE TABLE above; this guarded
    ALTER converges a database created before this feature to the same shape. It is
    this codebase's first schema migration — deliberately one guarded statement, not
    a migrations framework (research.md §5). A second such need would be the trigger
    to reconsider that, not this one.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(screening_results)")}
    if "other_metrics" not in columns:
        conn.execute(
            "ALTER TABLE screening_results ADD COLUMN other_metrics TEXT NOT NULL DEFAULT '{}'"
        )
