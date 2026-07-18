"""Evaluation ledger: the spent-once-per-lineage transactional gate (FR-019).

Implements contracts/evaluation-ledger-contract.md. ``spend()`` is a single atomic
UPDATE checked by rows-affected; callers never check-then-act. A refused attempt is
durably recorded in ``ledger_refusals`` and logged loudly — never a silent no-op.

The ledger opens a short-lived connection per operation so it is safe to call from
concurrent contexts; SQLite's write serialization plus the ``spent = 0`` predicate
makes exactly one concurrent spender win.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from energy_research.common.logging import get_logger, kv

log = get_logger("datastore.ledger")


class SpendOutcome(StrEnum):
    GRANTED = "granted"
    REFUSED = "refused"


@dataclass(frozen=True)
class LedgerStatus:
    lineage_id: str
    spent: bool
    spent_by_thesis_id: str | None
    spent_at: str | None


class EvaluationLedger:
    def __init__(self, db_path: str | Path):
        self._db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, lineage_id: str) -> None:
        """Create the lineage's single ledger row (spent = false). Idempotent."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO evaluation_ledger (lineage_id, spent) VALUES (?, 0)",
                (lineage_id,),
            )

    def spend(self, lineage_id: str, thesis_id: str) -> SpendOutcome:
        """Atomically consume the lineage's one-time final-evaluation entitlement."""
        now = datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE evaluation_ledger "
                "SET spent = 1, spent_by_thesis_id = ?, spent_at = ? "
                "WHERE lineage_id = ? AND spent = 0",
                (thesis_id, now, lineage_id),
            )
            if cur.rowcount == 1:
                conn.execute("COMMIT")
                log.info(
                    "final-evaluation entitlement spent %s",
                    kv(lineage_id=lineage_id, thesis_id=thesis_id),
                )
                return SpendOutcome.GRANTED

            row = conn.execute(
                "SELECT spent, spent_by_thesis_id FROM evaluation_ledger WHERE lineage_id = ?",
                (lineage_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                raise LookupError(
                    f"no evaluation ledger row exists for lineage {lineage_id!r}; "
                    "ledger rows must be created alongside the lineage"
                )
            detail = (
                f"refused final-evaluation attempt by thesis {thesis_id} on lineage "
                f"{lineage_id}: entitlement already spent by thesis {row['spent_by_thesis_id']}"
            )
            conn.execute(
                "INSERT INTO ledger_refusals "
                "(refusal_id, lineage_id, attempted_thesis_id, attempted_at, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, lineage_id, thesis_id, now, detail),
            )
            conn.execute("COMMIT")
            log.warning(
                "REFUSED ledger spend %s",
                kv(lineage_id=lineage_id, thesis_id=thesis_id, detail=detail),
            )
            return SpendOutcome.REFUSED
        finally:
            conn.close()

    def status(self, lineage_id: str) -> LedgerStatus:
        """Read-only audit view (User Story 4, SC-005)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT spent, spent_by_thesis_id, spent_at FROM evaluation_ledger "
                "WHERE lineage_id = ?",
                (lineage_id,),
            ).fetchone()
        if row is None:
            raise LookupError(f"no evaluation ledger row exists for lineage {lineage_id!r}")
        return LedgerStatus(
            lineage_id=lineage_id,
            spent=bool(row["spent"]),
            spent_by_thesis_id=row["spent_by_thesis_id"],
            spent_at=row["spent_at"],
        )

    def refusals(self, lineage_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ledger_refusals WHERE lineage_id = ? ORDER BY attempted_at",
                (lineage_id,),
            ).fetchall()
        return [dict(r) for r in rows]
