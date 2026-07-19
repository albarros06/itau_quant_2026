"""Repository over ``data/ops_agent.sqlite`` (data-model.md, research.md §3).

``record_activity``/``read_activity`` are the ONLY functions touching
``activity_log`` and are INSERT/SELECT only — no ``UPDATE``/``DELETE`` statement
against that table exists anywhere in this module (contracts/activity-log-contract.md
rule 1, enforced by ``tests/contract/test_activity_log_append_only.py``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ops_agent.store.schema import create_schema


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Repository:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        create_schema(self._conn)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- activity log

    def record_activity(
        self,
        *,
        action: str,
        target: str,
        reason: str,
        outcome: str,
        related_proposal_id: str | None = None,
        ts: str | None = None,
    ) -> int:
        """INSERT-only. ``action``/``target``/``reason``/``outcome`` are required —
        a caller cannot omit ``reason`` and still compile (activity-log-contract.md).
        """
        ts = ts or _now()
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO activity_log (ts, action, target, reason, outcome,"
                " related_proposal_id) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, action, target, reason, outcome, related_proposal_id),
            )
        return cursor.lastrowid

    def read_activity(
        self, since: str | None = None, until: str | None = None, action: str | None = None
    ) -> list[dict]:
        """SELECT-only, chronological (SC-003)."""
        q = "SELECT * FROM activity_log WHERE 1=1"
        args: list = []
        if since is not None:
            q += " AND ts >= ?"
            args.append(since)
        if until is not None:
            q += " AND ts <= ?"
            args.append(until)
        if action is not None:
            q += " AND action = ?"
            args.append(action)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY ts", args)]

    # ---------------------------------------------------------------- budgets

    def get_budget_usage(self, period_key: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM resource_budget_usage WHERE period_key = ?", (period_key,)
        ).fetchone()
        if row is None:
            return {
                "period_key": period_key,
                "llm_calls_used": 0,
                "vendor_requests_used": 0,
                "exhausted_at": None,
            }
        return dict(row)

    def increment_budget_usage(self, period_key: str, kind: str) -> dict:
        column = "llm_calls_used" if kind == "llm" else "vendor_requests_used"
        with self._conn:
            self._conn.execute(
                f"INSERT INTO resource_budget_usage (period_key, {column})"
                f" VALUES (?, 1)"
                f" ON CONFLICT(period_key) DO UPDATE SET {column} = {column} + 1",
                (period_key,),
            )
        return self.get_budget_usage(period_key)

    def mark_budget_exhausted(self, period_key: str) -> bool:
        """Sets ``exhausted_at`` once; idempotent. Returns True the first time."""
        current = self.get_budget_usage(period_key)
        if current["exhausted_at"] is not None:
            return False
        with self._conn:
            self._conn.execute(
                "INSERT INTO resource_budget_usage (period_key, exhausted_at) VALUES (?, ?)"
                " ON CONFLICT(period_key) DO UPDATE SET exhausted_at = excluded.exhausted_at",
                (period_key, _now()),
            )
        return True

    # -------------------------------------------------------------- schedule

    def get_schedule_state(self, kind: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM operating_schedule_state WHERE kind = ?", (kind,)
        ).fetchone()
        return dict(row) if row else None

    def update_schedule_state(
        self, kind: str, last_outcome: str, last_fired_at: str | None = None
    ) -> None:
        last_fired_at = last_fired_at or _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO operating_schedule_state (kind, last_fired_at, last_outcome)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(kind) DO UPDATE SET last_fired_at = excluded.last_fired_at,"
                " last_outcome = excluded.last_outcome",
                (kind, last_fired_at, last_outcome),
            )

    # ---------------------------------------------------------- feed watermarks

    def get_watermark(self, provider_id: str, category: str) -> str | None:
        row = self._conn.execute(
            "SELECT last_seen_marker FROM feed_watermarks WHERE provider_id = ? AND category = ?",
            (provider_id, category),
        ).fetchone()
        return row["last_seen_marker"] if row else None

    def update_watermark(self, provider_id: str, category: str, marker: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO feed_watermarks (provider_id, category, last_seen_marker, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(provider_id, category) DO UPDATE SET"
                " last_seen_marker = excluded.last_seen_marker, updated_at = excluded.updated_at",
                (provider_id, category, marker, _now()),
            )

    # ------------------------------------------------------------- proposals

    def create_proposal(
        self,
        *,
        id: str,
        kind: str,
        branch_name: str,
        base_commit_sha: str,
        target_files: list[str],
        rationale: str,
        discovery_evidence_ref: str | None = None,
    ) -> str:
        with self._conn:
            self._conn.execute(
                "INSERT INTO proposals (id, kind, branch_name, base_commit_sha, target_files,"
                " rationale, discovery_evidence_ref, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?)",
                (
                    id,
                    kind,
                    branch_name,
                    base_commit_sha,
                    json.dumps(target_files),
                    rationale,
                    discovery_evidence_ref,
                    _now(),
                ),
            )
        return id

    def get_proposal(self, proposal_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["target_files"] = json.loads(d["target_files"])
        return d

    def get_proposal_by_branch(self, branch_name: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM proposals WHERE branch_name = ?", (branch_name,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["target_files"] = json.loads(d["target_files"])
        return d

    def list_proposals(self, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM proposals"
        args: list = []
        if status is not None:
            q += " WHERE status = ?"
            args.append(status)
        rows = [dict(r) for r in self._conn.execute(q + " ORDER BY created_at", args)]
        for d in rows:
            d["target_files"] = json.loads(d["target_files"])
        return rows

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        status: str,
        decided_by: str,
        decided_at: str,
        applied_commit_sha: str | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE proposals SET status = ?, decided_by = ?, decided_at = ?,"
                " applied_commit_sha = ? WHERE id = ?",
                (status, decided_by, decided_at, applied_commit_sha, proposal_id),
            )

    # --------------------------------------------------- data source descriptors

    def record_data_source_descriptor(
        self, provider_id: str, proposal_id: str, connector_kind: str
    ) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO data_source_descriptors (provider_id, proposal_id, connector_kind,"
                " created_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(provider_id) DO UPDATE SET proposal_id = excluded.proposal_id,"
                " connector_kind = excluded.connector_kind, created_at = excluded.created_at",
                (provider_id, proposal_id, connector_kind, _now()),
            )
