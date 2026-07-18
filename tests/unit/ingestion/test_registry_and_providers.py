from __future__ import annotations

import numpy as np
import pytest

from energy_research.config.settings import MarketProviderEntry, ProvidersConfig
from energy_research.ingestion import registry
from energy_research.ingestion.connector import (
    MarketDataConnector,
    QualitativeContextConnector,
)
from tests.conftest import build_config


class TestRegistry:
    def test_resolves_configured_provider(self, tmp_path):
        config = build_config(tmp_path)
        connectors = registry.market_connectors(config)
        assert set(connectors) == {"sample_provider"}
        assert isinstance(connectors["sample_provider"], MarketDataConnector)
        context = registry.context_connectors(config)
        assert isinstance(context["sample_provider"], QualitativeContextConnector)

    def test_unknown_provider_id_is_a_lookup_error(self, tmp_path):
        config = build_config(
            tmp_path,
            providers=ProvidersConfig(
                market_data=[MarketProviderEntry(provider_id="ghost", categories=["fx"])]
            ),
        )
        with pytest.raises(LookupError, match="ghost"):
            registry.market_connectors(config)


class TestSampleProvider:
    def test_series_are_deterministic_across_instances(self, tmp_path):
        config = build_config(tmp_path)
        a = registry.market_connectors(config)["sample_provider"]
        b = registry.market_connectors(config)["sample_provider"]
        series_a = a.fetch_series("forward_curve", "BR_POWER_SE_FWD_M1")
        series_b = b.fetch_series("forward_curve", "BR_POWER_SE_FWD_M1")
        assert [o.value for o in series_a] == [o.value for o in series_b]

    def test_everything_is_labeled_synthetic(self, tmp_path):
        config = build_config(tmp_path)
        provider = registry.market_connectors(config)["sample_provider"]
        assert all(
            o.provenance == "synthetic" for o in provider.fetch_series("spot", "BR_POWER_SE_SPOT")
        )
        context = registry.context_connectors(config)["sample_provider"]
        docs = context.fetch_context("news")
        assert docs and all(d.provenance == "synthetic" for d in docs)
        assert all("SYNTHETIC" in d.text for d in docs)

    def test_signal_instrument_has_positive_drift(self, tmp_path):
        config = build_config(tmp_path)
        provider = registry.market_connectors(config)["sample_provider"]
        values = np.array(
            [o.value for o in provider.fetch_series("forward_curve", "BR_POWER_SE_FWD_M1")]
        )
        returns = np.diff(values) / values[:-1]
        assert returns.mean() > 0.001, "fixture must embed a genuine drift signal"
