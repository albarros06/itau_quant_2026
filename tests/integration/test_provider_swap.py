"""US2 provider swap (SC-010): changing the configured provider requires zero
changes to cleaning/datastore/analysis code and a full cycle still completes."""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta

import numpy as np

from energy_research.config.settings import MarketProviderEntry, ProvidersConfig
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all
from tests.conftest import UNIVERSE, build_config

ALL_CATEGORIES = ["spot", "forward_curve", "hydrology", "interest_rate", "fx"]


def write_dropzone(base_dir, n_days=900):
    """Deterministic CSV fixtures shaped like a vendor file drop."""
    base_dir.mkdir(parents=True, exist_ok=True)
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    for i, (key, _category) in enumerate(UNIVERSE):
        rng = np.random.default_rng(1000 + i)
        drift = 0.003 if key == "BR_POWER_SE_FWD_M1" else 0.0
        vol = 0.012 if key == "BR_POWER_SE_FWD_M1" else 0.015
        values = 100.0 * np.cumprod(1 + rng.normal(drift, vol, size=n_days))
        with (base_dir / f"{key}.csv").open("w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "value"])
            for day, value in enumerate(values):
                ts = end - timedelta(days=n_days - 1 - day)
                writer.writerow([ts.date().isoformat(), f"{value:.6f}"])


def test_provider_swap_requires_no_downstream_changes(tmp_path):
    dropzone = tmp_path / "dropzone"
    write_dropzone(dropzone)

    base = build_config(tmp_path)
    swapped = build_config(
        tmp_path,
        providers=ProvidersConfig(
            market_data=[
                MarketProviderEntry(
                    provider_id="secondary_market_provider",
                    categories=ALL_CATEGORIES,
                    options={"base_dir": str(dropzone), "provenance": "synthetic"},
                )
            ],
            qualitative_context=base.providers.qualitative_context,  # unchanged
        ),
    )

    # Only configuration changed: same cleaning, datastore, and analysis code paths.
    summary = ingest_all(swapped)
    assert summary["series"] == len(UNIVERSE)

    repo = Repository(swapped.datastore.db_path, swapped.datastore.lake_dir)
    try:
        providers = {row["provider_id"] for row in repo.series_rows()}
        assert providers == {"secondary_market_provider"}
    finally:
        repo.close()

    result = run_cycle(swapped)
    assert result.report_path.exists()
    assert result.statuses, "full cycle must complete against the swapped provider"


def test_unknown_provider_id_fails_loudly(tmp_path):
    import pytest

    config = build_config(
        tmp_path,
        providers=ProvidersConfig(
            market_data=[
                MarketProviderEntry(provider_id="nonexistent_vendor", categories=["spot"])
            ],
        ),
    )
    with pytest.raises(LookupError, match="no connector implementation"):
        ingest_all(config)
