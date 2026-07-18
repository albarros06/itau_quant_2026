"""Shared test fixtures: a fully offline pipeline configuration on tmp paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from energy_research.config.settings import (
    BacktestingConfig,
    ContextProviderEntry,
    DataQualityConfig,
    DatastoreConfig,
    GenerationConfig,
    InstrumentConfig,
    MarketProviderEntry,
    PipelineConfig,
    ProvidersConfig,
    RefinementConfig,
    ReproducibilityConfig,
    ScreeningConfig,
    SplitsConfig,
)

UNIVERSE = [
    ("BR_POWER_SE_SPOT", "spot"),
    ("BR_POWER_SE_FWD_M1", "forward_curve"),
    ("BR_POWER_SE_FWD_M3", "forward_curve"),
    ("BR_HYDRO_SE_RESERVOIR", "hydrology"),
    ("BR_DI_1Y", "interest_rate"),
    ("BRL_USD_FX", "fx"),
]


def build_config(base_dir: Path, **overrides) -> PipelineConfig:
    defaults: dict = {
        "providers": ProvidersConfig(
            market_data=[
                MarketProviderEntry(
                    provider_id="sample_provider",
                    categories=["spot", "forward_curve", "hydrology", "interest_rate", "fx"],
                )
            ],
            qualitative_context=[
                ContextProviderEntry(
                    provider_id="sample_provider",
                    categories=["news", "hydrology_outlook", "macro_regime"],
                )
            ],
        ),
        "datastore": DatastoreConfig(
            db_path=base_dir / "research.sqlite",
            lake_dir=base_dir / "lake",
            reports_dir=base_dir / "reports",
        ),
        "instrument_universe": [
            InstrumentConfig(key=key, category=category) for key, category in UNIVERSE
        ],
        "data_quality": DataQualityConfig(freshness_tolerance_days=7),
        "splits": SplitsConfig(discovery_fraction=0.5, refinement_fraction=0.3),
        "screening": ScreeningConfig(n_bootstrap=200, alpha=0.10),
        "backtesting": BacktestingConfig(
            transaction_cost_bps=5.0, slippage_bps=3.0, financing_annual_rate=0.11
        ),
        "refinement": RefinementConfig(max_refinement_depth_per_lineage=1, max_lineages_per_run=4),
        "generation": GenerationConfig(backend="deterministic_stub", max_theses_per_cycle=4),
        "reproducibility": ReproducibilityConfig(seed=20260718),
    }
    defaults.update(overrides)
    return PipelineConfig(**defaults)


@pytest.fixture
def pipeline_config(tmp_path) -> PipelineConfig:
    return build_config(tmp_path)
