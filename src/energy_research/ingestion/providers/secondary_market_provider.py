"""Second concrete MarketDataConnector: file-drop market data (SC-010).

A generic, vendor-neutral connector that serves series from CSV files dropped in a
configured directory (``options.base_dir``), one file per instrument named
``<instrument_key>.csv`` with columns ``date,value``. The concrete vendor feeding
that directory is a configuration/operations decision, not fixed here
(tasks.md note; Principle VI).

Provenance is declared in provider options (default ``real``) — never inferred.
Credentials, if the upstream drop requires them, are referenced by env-var name in
``options.api_key_env`` and validated in ``health_check`` only.
"""

from __future__ import annotations

import csv
import os
from datetime import UTC, datetime
from pathlib import Path

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion.connector import (
    ConnectorHealth,
    RawObservation,
)


class SecondaryMarketProvider:
    provider_id = "secondary_market_provider"

    def __init__(self, base_dir: Path, provenance: str, api_key_env: str | None):
        self._base_dir = Path(base_dir)
        self._provenance = provenance
        self._api_key_env = api_key_env

    def fetch_series(
        self, category: str, instrument_key: str, since: datetime | None = None
    ) -> list[RawObservation]:
        path = self._base_dir / f"{instrument_key}.csv"
        if not path.exists():
            return []
        observations: list[RawObservation] = []
        with path.open(newline="") as fh:
            for row in csv.DictReader(fh):
                ts = datetime.fromisoformat(row["date"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if since is not None and ts <= since:
                    continue
                observations.append(
                    RawObservation(
                        category=category,
                        instrument_key=instrument_key,
                        ts=ts,
                        value=float(row["value"]),
                        provenance=self._provenance,
                    )
                )
        return observations

    def health_check(self) -> ConnectorHealth:
        if not self._base_dir.is_dir():
            return ConnectorHealth(
                ok=False, detail=f"drop directory {self._base_dir} does not exist"
            )
        if self._api_key_env and not os.environ.get(self._api_key_env):
            return ConnectorHealth(
                ok=False, detail=f"credential env var {self._api_key_env} is not set"
            )
        return ConnectorHealth(ok=True, detail=f"serving files from {self._base_dir}")

    def discover(self) -> dict:
        """Optional vendor-discovery probe (research.md §5, 002 ops_agent).

        A plain, VendorCatalog-shaped dict — see sample_provider.discover() for why
        this is never an ``ops_agent`` type.
        """
        if not self._base_dir.is_dir():
            return {"provider_id": self.provider_id, "entries": []}
        instrument_hints = sorted(p.stem for p in self._base_dir.glob("*.csv"))
        if not instrument_hints:
            return {"provider_id": self.provider_id, "entries": []}
        return {
            "provider_id": self.provider_id,
            "entries": [
                {
                    "category": "file_drop",
                    "instrument_hints": instrument_hints,
                    "notes": f"CSV files found in {self._base_dir}",
                }
            ],
        }


def build_market_connector(options: dict, config: PipelineConfig) -> SecondaryMarketProvider:
    provenance = options.get("provenance", "real")
    if provenance not in ("real", "synthetic"):
        raise ValueError(
            f"secondary_market_provider: provenance must be 'real' or 'synthetic', "
            f"got {provenance!r} (Principle IV)"
        )
    return SecondaryMarketProvider(
        base_dir=Path(options.get("base_dir", "data/dropzone/market")),
        provenance=provenance,
        api_key_env=options.get("api_key_env"),
    )
