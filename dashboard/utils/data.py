"""Read-only data layer over the pipeline's datastore + Parquet lake.

The dashboard adds no data source: every value it shows comes from
``energy_research.datastore.repository.Repository`` (read methods only) and the
pipeline's own ``load_config``. This module deliberately imports no Streamlit, so
its mapping logic is unit-testable against a fixture SQLite database; ``app.py``
wraps construction in ``st.cache_resource``.

Where the design asked for something the data cannot honestly supply — a stored
strategy-equity curve, metrics that were never computed, submarkets that were
never ingested — this layer returns an explicit "unavailable" signal with a
reason, so the UI can say so rather than fabricate (Principles IV and VII).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from energy_research.config.settings import PipelineConfig, load_config
from energy_research.datastore.repository import Repository


@dataclass(frozen=True)
class InstrumentSnapshot:
    key: str
    category: str
    provider_id: str
    provenance: str  # 'real' | 'synthetic'
    latest_value: float | None
    latest_date: str | None
    span: tuple[str, str] | None
    spark: pd.Series  # trailing values indexed by date (may be empty)


@dataclass(frozen=True)
class EquityReconstruction:
    """Reconstructed underlying path across the cycle's real split windows, or an
    explicit reason it could not be built. Never a fabricated curve."""

    available: bool
    reason: str
    frame: pd.DataFrame  # columns: date, cum_return, split_type (empty if unavailable)
    instruments: list[str]
    synthetic: bool


# Buckets used for cycle-history aggregation, mirroring format.status_bucket but
# kept here to avoid a UI import in the data layer.
_BUCKET = {
    "promoted": "promoted",
    "screened_rejected": "rejected",
    "rejected_underperform": "rejected",
    "rejected_after_final": "rejected",
    "invalid_schema": "rejected",
    "refused": "rejected",
}


def _bucket(status: str) -> str:
    return _BUCKET.get(status, "pending")


class DashboardData:
    """Cached, read-only facade. One long-lived instance per session."""

    def __init__(self, dashboard_cfg: dict, project_root: Path):
        self.cfg = dashboard_cfg
        self.root = project_root
        pipeline_cfg_path = project_root / dashboard_cfg["data"]["pipeline_config"]
        self.pipeline: PipelineConfig = load_config(pipeline_cfg_path)
        # Pipeline paths are relative to the project root, not the config file.
        self.db_path = project_root / self.pipeline.datastore.db_path
        self.lake_dir = project_root / self.pipeline.datastore.lake_dir
        self.reports_dir = project_root / self.pipeline.datastore.reports_dir
        self.repo = Repository(self.db_path, self.lake_dir)

    def close(self) -> None:
        self.repo.close()

    # ------------------------------------------------------------------ cycles

    def list_report_cycles(self) -> list[dict]:
        """Cycles that have a report, newest report first, with cycle metadata."""
        conn = self.repo._conn  # read-only use of the shared connection
        rows = conn.execute(
            "SELECT r.cycle_id, r.generated_at, c.started_at, c.completed_at, c.seed,"
            " c.status FROM research_reports r"
            " JOIN research_cycles c ON c.cycle_id = r.cycle_id"
            " GROUP BY r.cycle_id"
            " ORDER BY r.generated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_cycle_id(self) -> str | None:
        cycles = self.list_report_cycles()
        return cycles[0]["cycle_id"] if cycles else None

    def resolve_default_cycle(self) -> str | None:
        want = self.cfg["display"].get("default_cycle", "latest")
        if want and want != "latest":
            return want
        return self.latest_cycle_id()

    # ------------------------------------------------------------------ report

    def report_entries(self, cycle_id: str) -> list[dict]:
        """Non-meta thesis entries for a cycle (skips the trailing __meta__ block)."""
        report = self.repo.get_report(cycle_id)
        return [e for e in report["thesis_entries"] if "__meta__" not in e]

    def report_meta(self, cycle_id: str) -> dict:
        report = self.repo.get_report(cycle_id)
        for e in report["thesis_entries"]:
            if "__meta__" in e:
                return e["__meta__"]
        return {}

    def thesis_entry(self, cycle_id: str, thesis_id: str) -> dict | None:
        for e in self.report_entries(cycle_id):
            if e["thesis_id"] == thesis_id:
                return e
        return None

    def cycle_summary(self, cycle_id: str) -> dict:
        """Aggregate counts by colour bucket + best net/Sharpe among finals."""
        entries = self.report_entries(cycle_id)
        counts = {"promoted": 0, "rejected": 0, "pending": 0}
        best_sharpe: float | None = None
        best_net: float | None = None
        any_synth = False
        for e in entries:
            counts[_bucket(e["final_status"])] += 1
            if e.get("synthetic_inputs"):
                any_synth = True
            for bt in e.get("final_evaluation", []) or []:
                om = bt.get("other_metrics", {}) or {}
                if om.get("any_synthetic_input"):
                    any_synth = True
                sharpe = om.get("sharpe")
                if sharpe is not None and (best_sharpe is None or sharpe > best_sharpe):
                    best_sharpe = sharpe
                net = bt.get("net_return")
                if net is not None and (best_net is None or net > best_net):
                    best_net = net
        return {
            "cycle_id": cycle_id,
            "total": len(entries),
            "counts": counts,
            "best_sharpe": best_sharpe,
            "best_net": best_net,
            "any_synthetic": any_synth,
        }

    # ------------------------------------------------------- market overview

    def _winning_series_row(self, instrument_key: str) -> dict | None:
        """The series that currently 'wins' for a key (last ingested), matching the
        Repository's own last-ingested-wins rule used for split reads."""
        row = None
        for r in self.repo.series_rows([instrument_key]):
            row = r  # series_rows is ordered by ingested_at → last wins
        return row

    def instrument_snapshot(self, instrument_key: str) -> InstrumentSnapshot | None:
        row = self._winning_series_row(instrument_key)
        if row is None:
            return None
        from energy_research.datastore import lake

        frame = lake.read_series(self.lake_dir, row["storage_ref"])
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date")
        spark_n = int(self.cfg["display"]["overview_spark_points"])
        tail = frame.tail(spark_n)
        spark = pd.Series(tail["value"].to_numpy(), index=tail["date"].to_numpy())
        latest = frame.iloc[-1] if len(frame) else None
        span = None
        if len(frame):
            span = (
                frame["date"].iloc[0].date().isoformat(),
                frame["date"].iloc[-1].date().isoformat(),
            )
        return InstrumentSnapshot(
            key=instrument_key,
            category=row["category"],
            provider_id=row["provider_id"],
            provenance=row["provenance"],
            latest_value=None if latest is None else float(latest["value"]),
            latest_date=None if latest is None else latest["date"].date().isoformat(),
            span=span,
            spark=spark,
        )

    def overview_snapshots(self) -> list[InstrumentSnapshot]:
        """Snapshots for the configured overview instruments that actually exist.

        Nothing is fabricated for an absent instrument (honest deviation #2:
        real instruments only, config-driven)."""
        ov = self.cfg.get("overview", {})
        keys: list[str] = []
        for role_key in (
            "spot_key",
            "reservoir_key",
            "forward_front_key",
            "forward_back_key",
            "fx_key",
            "rate_key",
        ):
            k = ov.get(role_key)
            if k and k not in keys:
                keys.append(k)
        out: list[InstrumentSnapshot] = []
        for k in keys:
            snap = self.instrument_snapshot(k)
            if snap is not None:
                out.append(snap)
        return out

    def forward_curve_shape(self) -> dict | None:
        """Contango/backwardation from the configured front vs back forward tenors."""
        ov = self.cfg.get("overview", {})
        front = self.instrument_snapshot(ov.get("forward_front_key", ""))
        back = self.instrument_snapshot(ov.get("forward_back_key", ""))
        if front is None or back is None or front.latest_value is None or back.latest_value is None:
            return None
        diff = back.latest_value - front.latest_value
        shape = "contango" if diff > 0 else ("backwardation" if diff < 0 else "flat")
        return {
            "shape": shape,
            "front": front.latest_value,
            "back": back.latest_value,
            "diff": diff,
            "synthetic": front.provenance == "synthetic" or back.provenance == "synthetic",
        }

    # ------------------------------------------------------- equity rebuild

    def _split_reader(self, split_type: str):
        return {
            "refinement": self.repo.read_refinement_data,
            "final_evaluation": self.repo.read_final_evaluation_data,
            "discovery": self.repo.read_discovery_data,
        }[split_type]

    def reconstruct_equity(self, cycle_id: str, entry: dict) -> EquityReconstruction:
        """Cumulative return of the thesis's traded instrument(s) across the cycle's
        REAL refinement + final-evaluation windows — a reconstructed *underlying
        path*, explicitly not a stored strategy equity (honest deviation #1).

        Returns ``available=False`` with a reason when the current lake does not
        cover the cycle's split windows (e.g. an older cycle whose spot series has
        since been replaced by a shorter real feed) — never a blank or faked line.
        """
        instruments = list(entry.get("hypothesis", {}).get("instruments") or [])
        if not instruments:
            return EquityReconstruction(
                False, "thesis records no traded instrument", _empty_equity(), [], False
            )
        direction = entry.get("hypothesis", {}).get("direction", "long")
        sign = -1.0 if direction == "short" else 1.0
        min_pts = int(self.cfg["display"].get("equity_min_points", 3))

        pieces: list[pd.DataFrame] = []
        synthetic = bool(entry.get("synthetic_inputs"))
        cum = 1.0
        for split_type in ("refinement", "final_evaluation"):
            try:
                scoped = self._split_reader(split_type)(cycle_id, instruments)
            except LookupError:
                continue
            prices = scoped.prices.dropna()
            if prices.empty or len(prices) < 2:
                continue
            if scoped.any_synthetic:
                synthetic = True
            # Equal-weight the traded instruments; directional per hypothesis.
            rets = prices.pct_change().dropna().mean(axis=1) * sign
            piece = pd.DataFrame({"date": rets.index})
            growth = (1.0 + rets).cumprod().to_numpy()
            piece["cum_return"] = cum * growth - 1.0
            piece["split_type"] = split_type
            if len(growth):
                cum = cum * growth[-1]
            pieces.append(piece)

        if not pieces:
            return EquityReconstruction(
                False,
                "underlying price data for this cycle's split windows is not in the "
                "current lake (the series that produced this backtest has since been "
                "replaced); the stored net-of-cost result above is unaffected",
                _empty_equity(),
                instruments,
                synthetic,
            )
        frame = pd.concat(pieces, ignore_index=True)
        if len(frame) < min_pts:
            return EquityReconstruction(
                False,
                f"only {len(frame)} price point(s) available for these split windows — "
                "too few to plot honestly",
                _empty_equity(),
                instruments,
                synthetic,
            )
        return EquityReconstruction(True, "", frame, instruments, synthetic)


def _empty_equity() -> pd.DataFrame:
    return pd.DataFrame({"date": [], "cum_return": [], "split_type": []})
