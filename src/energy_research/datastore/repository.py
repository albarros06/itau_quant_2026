"""Repository over SQLite state + the Parquet lake, owning all split scoping.

Split isolation (FR-014/FR-018) is structural here: the only price-data access paths
are :meth:`read_discovery_data`, :meth:`read_refinement_data`, and
:meth:`read_final_evaluation_data`, each of which slices the lake to that split's
recorded ``DataSplitAllocation`` date range. There is no method returning unscoped
or cross-split data, so no caller can widen its own scope.
"""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from energy_research.common.logging import get_logger, kv
from energy_research.common.records import CleanedSeries, ContextDoc, QualityIssue
from energy_research.datastore import lake
from energy_research.datastore.schema import create_schema

log = get_logger("datastore.repository")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class SplitScopedData:
    """Price data already restricted to exactly one split's date range.

    Downstream layers (screening, backtesting) accept only this type — never a raw
    date range — so split scoping cannot be widened by the caller
    (contracts/backtest-contract.md rule 1, screening-contract.md rule 1).
    """

    split_type: str
    date_range: tuple[str, str]
    prices: pd.DataFrame  # index: date, columns: instrument_key
    provenance: dict[str, str]  # instrument_key -> 'real' | 'synthetic'

    @property
    def any_synthetic(self) -> bool:
        return any(p == "synthetic" for p in self.provenance.values())


class StaleDataError(RuntimeError):
    """Raised when required series are stale beyond tolerance (FR-006)."""


class Repository:
    def __init__(self, db_path: str | Path, lake_dir: str | Path):
        self.db_path = Path(db_path)
        self.lake_dir = Path(lake_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lake_dir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=30)
        self._conn.row_factory = sqlite3.Row
        create_schema(self._conn)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------ series

    def store_cleaned_series(self, cleaned: CleanedSeries) -> str:
        """Persist a cleaned series: Parquet frame + DataSeries row + quality records."""
        ref = lake.write_series(
            self.lake_dir,
            cleaned.category,
            cleaned.instrument_key,
            cleaned.provider_id,
            cleaned.frame,
        )
        series_id = f"{cleaned.category}:{cleaned.instrument_key}:{cleaned.provider_id}"
        quality_status = "flagged" if cleaned.issues else "clean"
        with self._conn:
            self._conn.execute(
                "INSERT INTO data_series (series_id, category, instrument_key, provider_id,"
                " provenance, freshness_ts, ingested_at, storage_ref, quality_status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(series_id) DO UPDATE SET provenance = excluded.provenance,"
                "  freshness_ts = excluded.freshness_ts, ingested_at = excluded.ingested_at,"
                "  storage_ref = excluded.storage_ref, quality_status = excluded.quality_status",
                (
                    series_id,
                    cleaned.category,
                    cleaned.instrument_key,
                    cleaned.provider_id,
                    cleaned.provenance,
                    cleaned.freshness_ts.isoformat(),
                    _now(),
                    ref,
                    quality_status,
                ),
            )
        for issue in cleaned.issues:
            self.record_quality_issue(series_id, issue)
        return series_id

    def record_quality_issue(self, series_id: str, issue: QualityIssue) -> str:
        record_id = _new_id("dq")
        with self._conn:
            self._conn.execute(
                "INSERT INTO data_quality_records"
                " (record_id, series_id, detected_at, issue_type, intervention, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (record_id, series_id, _now(), issue.issue_type, issue.intervention, issue.detail),
            )
        log.warning(
            "data-quality issue %s",
            kv(
                series_id=series_id,
                issue_type=issue.issue_type,
                intervention=issue.intervention,
                detail=issue.detail,
            ),
        )
        return record_id

    def quality_records(self, series_id: str | None = None) -> list[dict]:
        q = "SELECT * FROM data_quality_records"
        args: tuple = ()
        if series_id:
            q += " WHERE series_id = ?"
            args = (series_id,)
        return [dict(r) for r in self._conn.execute(q + " ORDER BY detected_at", args)]

    def series_rows(self, instrument_keys: list[str] | None = None) -> list[dict]:
        rows = [
            dict(r) for r in self._conn.execute("SELECT * FROM data_series ORDER BY ingested_at")
        ]
        if instrument_keys is not None:
            rows = [r for r in rows if r["instrument_key"] in instrument_keys]
        return rows

    def assert_fresh(
        self, instrument_keys: list[str], tolerance_days: float, as_of: datetime | None = None
    ) -> None:
        """Refuse (raise) if any required series is missing or stale beyond tolerance.

        This is the FR-006 gate: a research cycle must not start on degraded data,
        and the refusal states exactly which series and why.
        """
        as_of = as_of or datetime.now(UTC)
        by_key: dict[str, dict] = {}
        for row in self.series_rows(instrument_keys):
            by_key[row["instrument_key"]] = row  # last ingested wins
        problems: list[str] = []
        for key in instrument_keys:
            row = by_key.get(key)
            if row is None:
                problems.append(f"{key}: no ingested series (run `research-pipeline ingest`)")
                continue
            freshness = datetime.fromisoformat(row["freshness_ts"])
            if freshness.tzinfo is None:
                freshness = freshness.replace(tzinfo=UTC)
            age_days = (as_of - freshness).total_seconds() / 86400
            if age_days > tolerance_days:
                problems.append(
                    f"{key}: freshness_ts {row['freshness_ts']} is {age_days:.1f} days old "
                    f"(tolerance {tolerance_days} days)"
                )
                with self._conn:
                    self._conn.execute(
                        "UPDATE data_series SET quality_status = 'stale' WHERE series_id = ?",
                        (row["series_id"],),
                    )
                self.record_quality_issue(
                    row["series_id"],
                    QualityIssue(
                        issue_type="stale_feed",
                        intervention="rejected",
                        detail=f"cycle refused: series {age_days:.1f} days stale "
                        f"(tolerance {tolerance_days})",
                    ),
                )
        if problems:
            msg = "refusing to start research cycle on stale/missing data: " + "; ".join(problems)
            log.error(msg)
            raise StaleDataError(msg)

    def common_date_bounds(self, instrument_keys: list[str]) -> tuple[str, str]:
        """(start, end) date range covered by ALL required series, for split sizing."""
        by_key: dict[str, dict] = {}
        for row in self.series_rows(instrument_keys):
            by_key[row["instrument_key"]] = row
        missing = [k for k in instrument_keys if k not in by_key]
        if missing:
            raise LookupError(f"no ingested series for instruments {missing}")
        starts, ends = [], []
        for key in instrument_keys:
            frame = lake.read_series(self.lake_dir, by_key[key]["storage_ref"])
            dates = pd.to_datetime(frame["date"])
            starts.append(dates.min())
            ends.append(dates.max())
        return (max(starts).date().isoformat(), min(ends).date().isoformat())

    # ------------------------------------------------------------- context docs

    def store_context_docs(self, docs: list[ContextDoc]) -> int:
        with self._conn:
            for provider_id, category in {(d.provider_id, d.category) for d in docs}:
                self._conn.execute(
                    "DELETE FROM context_docs WHERE provider_id = ? AND category = ?",
                    (provider_id, category),
                )
            for d in docs:
                self._conn.execute(
                    "INSERT INTO context_docs"
                    " (doc_id, provider_id, category, source, doc_ts, text, provenance,"
                    "  ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        _new_id("ctx"),
                        d.provider_id,
                        d.category,
                        d.source,
                        d.doc_ts.isoformat(),
                        d.text,
                        d.provenance,
                        _now(),
                    ),
                )
        return len(docs)

    def context_documents(self, categories: list[str] | None = None) -> list[dict]:
        rows = [
            dict(r) for r in self._conn.execute("SELECT * FROM context_docs ORDER BY doc_ts DESC")
        ]
        if categories is not None:
            rows = [r for r in rows if r["category"] in categories]
        return rows

    # ------------------------------------------------------------------ cycles

    def create_cycle(
        self, config_snapshot: dict, seed: int, max_refinement_depth: int, max_lineages: int
    ) -> str:
        cycle_id = _new_id("cyc")
        with self._conn:
            self._conn.execute(
                "INSERT INTO research_cycles (cycle_id, started_at, config_snapshot, seed,"
                " max_refinement_depth, max_lineages_or_iterations, status)"
                " VALUES (?, ?, ?, ?, ?, ?, 'running')",
                (
                    cycle_id,
                    _now(),
                    json.dumps(config_snapshot),
                    seed,
                    max_refinement_depth,
                    max_lineages,
                ),
            )
        return cycle_id

    def finish_cycle(self, cycle_id: str, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE research_cycles SET status = ?, completed_at = ? WHERE cycle_id = ?",
                (status, _now(), cycle_id),
            )

    def get_cycle(self, cycle_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM research_cycles WHERE cycle_id = ?", (cycle_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no research cycle {cycle_id!r}")
        d = dict(row)
        d["config_snapshot"] = json.loads(d["config_snapshot"])
        return d

    # ------------------------------------------------------------- allocations

    def create_split_allocation(
        self, cycle_id: str, split_type: str, start: str, end: str, instrument_scope: str
    ) -> str:
        allocation_id = _new_id("split")
        with self._conn:
            self._conn.execute(
                "INSERT INTO data_split_allocations"
                " (allocation_id, cycle_id, split_type, date_range_start, date_range_end,"
                "  instrument_scope) VALUES (?, ?, ?, ?, ?, ?)",
                (allocation_id, cycle_id, split_type, start, end, instrument_scope),
            )
        return allocation_id

    def get_allocation(self, cycle_id: str, split_type: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM data_split_allocations WHERE cycle_id = ? AND split_type = ?",
            (cycle_id, split_type),
        ).fetchone()
        if row is None:
            raise LookupError(f"cycle {cycle_id!r} has no {split_type!r} split allocation")
        return dict(row)

    # ------------------------------------------------- split-scoped data reads

    def _read_split(
        self, cycle_id: str, split_type: str, instrument_keys: list[str]
    ) -> SplitScopedData:
        alloc = self.get_allocation(cycle_id, split_type)
        start = pd.Timestamp(alloc["date_range_start"])
        end = pd.Timestamp(alloc["date_range_end"])
        by_key: dict[str, dict] = {}
        for row in self.series_rows(instrument_keys):
            by_key[row["instrument_key"]] = row
        columns: dict[str, pd.Series] = {}
        provenance: dict[str, str] = {}
        for key in instrument_keys:
            row = by_key.get(key)
            if row is None:
                raise LookupError(f"no ingested series for instrument {key!r}")
            frame = lake.read_series(self.lake_dir, row["storage_ref"])
            frame["date"] = pd.to_datetime(frame["date"])
            mask = (frame["date"] >= start) & (frame["date"] <= end)
            sliced = frame.loc[mask].set_index("date")["value"]
            columns[key] = sliced
            provenance[key] = row["provenance"]
        prices = pd.DataFrame(columns).sort_index()
        return SplitScopedData(
            split_type=split_type,
            date_range=(alloc["date_range_start"], alloc["date_range_end"]),
            prices=prices,
            provenance=provenance,
        )

    def read_discovery_data(self, cycle_id: str, instrument_keys: list[str]) -> SplitScopedData:
        """The ONLY data access path available to screening (FR-014)."""
        return self._read_split(cycle_id, "discovery", instrument_keys)

    def read_refinement_data(self, cycle_id: str, instrument_keys: list[str]) -> SplitScopedData:
        return self._read_split(cycle_id, "refinement", instrument_keys)

    def read_final_evaluation_data(
        self, cycle_id: str, instrument_keys: list[str]
    ) -> SplitScopedData:
        """Callers must hold a GRANTED ledger spend before invoking this (FR-019)."""
        return self._read_split(cycle_id, "final_evaluation", instrument_keys)

    # -------------------------------------------------------- lineages / theses

    def create_lineage(self, cycle_id: str, root_thesis_id: str) -> str:
        lineage_id = _new_id("lin")
        with self._conn:
            self._conn.execute(
                "INSERT INTO thesis_lineages (lineage_id, cycle_id, root_thesis_id,"
                " refinement_depth) VALUES (?, ?, ?, 0)",
                (lineage_id, cycle_id, root_thesis_id),
            )
        return lineage_id

    def get_lineage(self, lineage_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM thesis_lineages WHERE lineage_id = ?", (lineage_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no lineage {lineage_id!r}")
        return dict(row)

    def bump_lineage_depth(self, lineage_id: str) -> int:
        with self._conn:
            self._conn.execute(
                "UPDATE thesis_lineages SET refinement_depth = refinement_depth + 1"
                " WHERE lineage_id = ?",
                (lineage_id,),
            )
        return self.get_lineage(lineage_id)["refinement_depth"]

    def insert_thesis(
        self,
        *,
        cycle_id: str,
        lineage_id: str,
        rationale: str,
        hypothesis: dict,
        status: str,
        status_reason: str = "",
        parent_thesis_id: str | None = None,
        iteration_index: int = 0,
        thesis_id: str | None = None,
    ) -> str:
        thesis_id = thesis_id or _new_id("th")
        with self._conn:
            self._conn.execute(
                "INSERT INTO trading_theses (thesis_id, lineage_id, parent_thesis_id,"
                " cycle_id, iteration_index, rationale, hypothesis, status, status_reason,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thesis_id,
                    lineage_id,
                    parent_thesis_id,
                    cycle_id,
                    iteration_index,
                    rationale,
                    json.dumps(hypothesis),
                    status,
                    status_reason,
                    _now(),
                ),
            )
        return thesis_id

    def update_thesis_status(self, thesis_id: str, status: str, reason: str = "") -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE trading_theses SET status = ?, status_reason = ? WHERE thesis_id = ?",
                (status, reason, thesis_id),
            )

    def get_thesis(self, thesis_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM trading_theses WHERE thesis_id = ?", (thesis_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no thesis {thesis_id!r}")
        d = dict(row)
        d["hypothesis"] = json.loads(d["hypothesis"])
        return d

    def theses_for_cycle(self, cycle_id: str, status: str | None = None) -> list[dict]:
        q = "SELECT * FROM trading_theses WHERE cycle_id = ?"
        args: list = [cycle_id]
        if status is not None:
            q += " AND status = ?"
            args.append(status)
        # rowid ordering keeps iteration order deterministic across replays,
        # which created_at (same-microsecond ties) cannot guarantee (FR-028).
        rows = [dict(r) for r in self._conn.execute(q + " ORDER BY rowid", args)]
        for d in rows:
            d["hypothesis"] = json.loads(d["hypothesis"])
        return rows

    def theses_for_lineage(self, lineage_id: str) -> list[dict]:
        rows = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM trading_theses WHERE lineage_id = ? ORDER BY iteration_index, rowid",
                (lineage_id,),
            )
        ]
        for d in rows:
            d["hypothesis"] = json.loads(d["hypothesis"])
        return rows

    # ----------------------------------------------------------------- results

    def insert_screening_result(
        self,
        *,
        thesis_id: str,
        method: str,
        statistic_value: float,
        p_value: float,
        multiplicity_method: str,
        adjusted_threshold: float,
        verdict: str,
        reason: str,
    ) -> str:
        if verdict not in ("pass", "fail"):
            raise ValueError(f"screening verdict must be pass/fail, got {verdict!r}")
        if not reason.strip():
            raise ValueError("screening result requires a specific, non-empty reason (FR-015)")
        result_id = _new_id("scr")
        with self._conn:
            self._conn.execute(
                "INSERT INTO screening_results (result_id, thesis_id, method,"
                " statistic_value, p_value, multiplicity_method, adjusted_threshold,"
                " verdict, reason, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result_id,
                    thesis_id,
                    method,
                    statistic_value,
                    p_value,
                    multiplicity_method,
                    adjusted_threshold,
                    verdict,
                    reason,
                    _now(),
                ),
            )
        return result_id

    def screening_result_for(self, thesis_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM screening_results WHERE thesis_id = ? ORDER BY evaluated_at DESC",
            (thesis_id,),
        ).fetchone()
        return dict(row) if row else None

    def insert_backtest_result(
        self,
        *,
        thesis_id: str,
        split_type: str,
        gross_return: float,
        transaction_costs: float,
        slippage: float,
        financing_carry: float,
        net_return: float,
        other_metrics: dict | None = None,
    ) -> str:
        for name, value in (
            ("transaction_costs", transaction_costs),
            ("slippage", slippage),
            ("financing_carry", financing_carry),
        ):
            if value is None:
                raise ValueError(
                    f"backtest result missing {name}: gross-only results are invalid and "
                    "must not be persisted (Constitution Principle IV, FR-017)"
                )
        for name, value in (
            ("gross_return", gross_return),
            ("transaction_costs", transaction_costs),
            ("slippage", slippage),
            ("financing_carry", financing_carry),
            ("net_return", net_return),
        ):
            if not math.isfinite(value):
                raise ValueError(
                    f"backtest result has non-finite {name}={value!r}: inf/NaN performance "
                    "is not a result and must not be persisted (Principle VII backstop; "
                    "the engine should have refused upstream)"
                )
        result_id = _new_id("bt")
        with self._conn:
            self._conn.execute(
                "INSERT INTO backtest_results (result_id, thesis_id, split_type,"
                " gross_return, transaction_costs, slippage, financing_carry, net_return,"
                " other_metrics, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result_id,
                    thesis_id,
                    split_type,
                    gross_return,
                    transaction_costs,
                    slippage,
                    financing_carry,
                    net_return,
                    json.dumps(other_metrics or {}),
                    _now(),
                ),
            )
        return result_id

    def backtest_results_for(self, thesis_id: str, split_type: str | None = None) -> list[dict]:
        q = "SELECT * FROM backtest_results WHERE thesis_id = ?"
        args: list = [thesis_id]
        if split_type is not None:
            q += " AND split_type = ?"
            args.append(split_type)
        rows = [dict(r) for r in self._conn.execute(q + " ORDER BY evaluated_at", args)]
        for d in rows:
            d["other_metrics"] = json.loads(d["other_metrics"])
        return rows

    def insert_critique(
        self,
        *,
        thesis_id: str,
        weaknesses: list[str],
        suggested_direction: str,
        feeds_iteration_index: int,
    ) -> str:
        critique_id = _new_id("cr")
        with self._conn:
            self._conn.execute(
                "INSERT INTO critiques (critique_id, thesis_id, weaknesses,"
                " suggested_direction, created_at, feeds_iteration_index)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    critique_id,
                    thesis_id,
                    json.dumps(weaknesses),
                    suggested_direction,
                    _now(),
                    feeds_iteration_index,
                ),
            )
        return critique_id

    def critiques_for(self, thesis_id: str) -> list[dict]:
        rows = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM critiques WHERE thesis_id = ? ORDER BY created_at", (thesis_id,)
            )
        ]
        for d in rows:
            d["weaknesses"] = json.loads(d["weaknesses"])
        return rows

    # ----------------------------------------------------------------- reports

    def insert_report(self, cycle_id: str, thesis_entries: list[dict]) -> str:
        report_id = _new_id("rep")
        with self._conn:
            self._conn.execute(
                "INSERT INTO research_reports (report_id, cycle_id, generated_at,"
                " thesis_entries) VALUES (?, ?, ?, ?)",
                (report_id, cycle_id, _now(), json.dumps(thesis_entries)),
            )
        return report_id

    def get_report(self, cycle_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM research_reports WHERE cycle_id = ? ORDER BY generated_at DESC",
            (cycle_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"no report for cycle {cycle_id!r}")
        d = dict(row)
        d["thesis_entries"] = json.loads(d["thesis_entries"])
        return d

    def ledger_refusal_rows(self, cycle_id: str) -> list[dict]:
        """Refused final-evaluation attempts for lineages of this cycle (FR-026/US4)."""
        rows = self._conn.execute(
            "SELECT lr.* FROM ledger_refusals lr"
            " JOIN thesis_lineages tl ON tl.lineage_id = lr.lineage_id"
            " WHERE tl.cycle_id = ? ORDER BY lr.attempted_at",
            (cycle_id,),
        ).fetchall()
        return [dict(r) for r in rows]
