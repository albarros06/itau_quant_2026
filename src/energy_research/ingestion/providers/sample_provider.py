"""Clearly labeled synthetic sample provider (User Story 1 / quickstart.md §5).

Serves a deterministic synthetic dataset for the full configured universe plus
qualitative context documents. Every observation and document carries
``provenance="synthetic"`` — there is no code path that emits this data as real
(Constitution Principle IV, FR-007).

Series shapes are chosen so a research cycle exercises every outcome: one
instrument carries a real drift (a thesis on it can pass screening), one drifts
slightly the other way, and the rest are driftless noise (their theses fail with
recorded reasons).
"""

from __future__ import annotations

import zlib
from datetime import UTC, datetime, timedelta

import numpy as np

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion.connector import (
    ConnectorHealth,
    RawContextDoc,
    RawObservation,
)

_N_DAYS = 1200
_PROVENANCE = "synthetic"

# Per-instrument (drift, volatility, start_level); anything not listed is driftless.
_SHAPES: dict[str, tuple[float, float, float]] = {
    "BR_POWER_SE_FWD_M1": (0.0030, 0.012, 180.0),
    "BR_POWER_SE_SPOT": (-0.0010, 0.025, 150.0),
    "BR_POWER_SE_FWD_M3": (0.0000, 0.018, 190.0),
    "BR_HYDRO_SE_RESERVOIR": (0.0000, 0.010, 55.0),
    "BR_DI_1Y": (0.0000, 0.004, 11.0),
    "BRL_USD_FX": (0.0000, 0.008, 5.2),
}
_DEFAULT_SHAPE = (0.0, 0.015, 100.0)

# category for each known instrument key (research.md §5 discover()); mirrors
# config/default.yaml's instrument_universe exactly so a discovery-drafted
# proposal reconstructs the same shape. Unlisted keys default to "spot" in
# discover() below, same as _DEFAULT_SHAPE's role for series generation.
_CATEGORY_BY_KEY: dict[str, str] = {
    "BR_POWER_SE_SPOT": "spot",
    "BR_POWER_SE_FWD_M1": "forward_curve",
    "BR_POWER_SE_FWD_M3": "forward_curve",
    "BR_HYDRO_SE_RESERVOIR": "hydrology",
    "BR_DI_1Y": "interest_rate",
    "BRL_USD_FX": "fx",
}

_CONTEXT_DOCS: dict[str, list[str]] = {
    "news": [
        "[SYNTHETIC SAMPLE] Regulator signals no change to SE/CO submarket price caps "
        "this quarter; forward market liquidity reported as improving.",
    ],
    "hydrology_outlook": [
        "[SYNTHETIC SAMPLE] Seasonal outlook: below-median inflows expected for the "
        "SE/CO basin over the next 60 days; reservoir trajectory flat to declining.",
    ],
    "macro_regime": [
        "[SYNTHETIC SAMPLE] Rates regime stable; DI curve pricing no near-term policy "
        "moves; FX volatility subdued.",
    ],
}


class SampleProvider:
    """Implements both connector protocols for the labeled sample dataset."""

    provider_id = "sample_provider"

    def __init__(self, universe_keys: list[str]):
        self._universe_keys = universe_keys

    def _series_values(self, instrument_key: str) -> np.ndarray:
        drift, vol, start = _SHAPES.get(instrument_key, _DEFAULT_SHAPE)
        # Seeded per instrument (not per cycle) with a process-stable digest: the
        # sample dataset is a fixture, identical across ingestions and processes,
        # which is what makes replay meaningful.
        seed = zlib.crc32(instrument_key.encode())
        rng = np.random.default_rng(seed)
        daily = rng.normal(loc=drift, scale=vol, size=_N_DAYS)
        return start * np.cumprod(1.0 + daily)

    def fetch_series(
        self, category: str, instrument_key: str, since: datetime | None = None
    ) -> list[RawObservation]:
        values = self._series_values(instrument_key)
        end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        observations = []
        for i, value in enumerate(values):
            ts = end - timedelta(days=_N_DAYS - 1 - i)
            if since is not None and ts <= since:
                continue
            observations.append(
                RawObservation(
                    category=category,
                    instrument_key=instrument_key,
                    ts=ts,
                    value=float(value),
                    provenance=_PROVENANCE,
                )
            )
        return observations

    def fetch_context(self, category: str, since: datetime | None = None) -> list[RawContextDoc]:
        now = datetime.now(UTC)
        return [
            RawContextDoc(
                category=category,
                source="sample_provider",
                ts=now,
                text=text,
                provenance=_PROVENANCE,
            )
            for text in _CONTEXT_DOCS.get(category, [])
        ]

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(ok=True, detail="synthetic sample data, always available")

    def discover(self) -> dict:
        """Optional vendor-discovery probe (research.md §5, 002 ops_agent).

        Returns a plain, VendorCatalog-shaped dict rather than an ``ops_agent`` type —
        ``energy_research`` never imports ``ops_agent`` (contracts/ops-agent-boundary.md
        rule 1); the agent's ``discovery.vendor_probe`` duck-types this shape instead.
        Reports the vendor's full fixed catalog (``_CATEGORY_BY_KEY``) — what this
        vendor CAN supply — independent of ``self._universe_keys`` (what a caller's
        config currently asks for), so discovery can propose a candidate universe
        larger than whatever is already configured. Market entries are grouped by
        category (not a flat instrument list) so a proposal drafted from this
        catalog can reconstruct real ``InstrumentConfig`` entries.
        """
        by_category: dict[str, list[str]] = {}
        for key in _CATEGORY_BY_KEY:
            by_category.setdefault(_CATEGORY_BY_KEY[key], []).append(key)
        entries = [
            {
                "category": category,
                "instrument_hints": keys,
                "notes": "synthetic sample market series",
            }
            for category, keys in sorted(by_category.items())
        ]
        entries.extend(
            {
                "category": category,
                "instrument_hints": [],
                "notes": f"{len(docs)} sample document(s) available",
            }
            for category, docs in _CONTEXT_DOCS.items()
        )
        return {"provider_id": self.provider_id, "entries": entries}


def build_market_connector(options: dict, config: PipelineConfig) -> SampleProvider:
    return SampleProvider(config.universe_keys)


def build_context_connector(options: dict, config: PipelineConfig) -> SampleProvider:
    return SampleProvider(config.universe_keys)
