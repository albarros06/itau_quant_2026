"""US2 fail-loud data quality (SC-006): a gap, an outlier, and a stale feed each
raise a visible warning/error and produce a DataQualityRecord — never silent
interpolation."""

from __future__ import annotations

import csv
import logging
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from energy_research.config.settings import MarketProviderEntry, ProvidersConfig
from energy_research.datastore import lake
from energy_research.datastore.repository import Repository, StaleDataError
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all
from tests.conftest import UNIVERSE, build_config

ALL_CATEGORIES = ["spot", "forward_curve", "hydrology", "interest_rate", "fx"]


def _write_series(path, values, dates):
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "value"])
        for ts, value in zip(dates, values, strict=True):
            writer.writerow([ts.date().isoformat(), f"{value:.6f}"])


@pytest.fixture
def defective_dropzone(tmp_path):
    """CSV fixtures with one gap, one outlier, and one stale feed injected."""
    dropzone = tmp_path / "dropzone"
    dropzone.mkdir(parents=True)
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    n = 400
    rng = np.random.default_rng(7)
    for key, _category in UNIVERSE:
        values = list(100.0 * np.cumprod(1 + rng.normal(0, 0.01, size=n)))
        dates = [end - timedelta(days=n - 1 - i) for i in range(n)]
        if key == "BR_POWER_SE_SPOT":  # gap: drop 12 consecutive days
            del values[200:212]
            del dates[200:212]
        if key == "BRL_USD_FX":  # outlier: one wild spike
            values[300] *= 40.0
        if key == "BR_DI_1Y":  # stale feed: last observation 30 days old
            values = values[:-30]
            dates = dates[:-30]
        _write_series(dropzone / f"{key}.csv", values, dates)
    return dropzone


@pytest.fixture
def defective_config(tmp_path, defective_dropzone):
    return build_config(
        tmp_path,
        providers=ProvidersConfig(
            market_data=[
                MarketProviderEntry(
                    provider_id="secondary_market_provider",
                    categories=ALL_CATEGORIES,
                    options={"base_dir": str(defective_dropzone), "provenance": "synthetic"},
                )
            ],
        ),
    )


def test_defects_raise_visible_warnings_and_records(defective_config, caplog):
    with caplog.at_level(logging.WARNING, logger="energy_research"):
        ingest_all(defective_config)

    repo = Repository(defective_config.datastore.db_path, defective_config.datastore.lake_dir)
    try:
        records = repo.quality_records()
        by_type = {r["issue_type"] for r in records}
        assert "gap" in by_type
        assert "outlier" in by_type
        assert "stale_feed" in by_type
        # Every record explains what was found and that nothing was repaired.
        for record in records:
            assert record["detail"].strip()
            assert record["intervention"] in (
                "none_raised",
                "gap_fill",
                "correction",
                "fallback",
                "rejected",
            )

        # Visible warnings, not just database rows (Principle VII).
        warning_text = " ".join(r.getMessage() for r in caplog.records)
        for token in ("gap", "outlier", "stale"):
            assert token in warning_text, f"no visible warning mentioning {token!r}"

        # No silent interpolation: the gapped series keeps its gap.
        spot = next(r for r in repo.series_rows() if r["instrument_key"] == "BR_POWER_SE_SPOT")
        frame = lake.read_series(defective_config.datastore.lake_dir, spot["storage_ref"])
        assert len(frame) == 400 - 12, "gap must not be filled in"
        assert frame["value"].notna().all(), "no imputed placeholder values"
    finally:
        repo.close()


def test_cycle_refuses_to_start_on_stale_data(defective_config):
    ingest_all(defective_config)
    with pytest.raises(StaleDataError, match="BR_DI_1Y"):
        run_cycle(defective_config)
