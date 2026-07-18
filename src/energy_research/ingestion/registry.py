"""Config-keyed provider registry (FR-002).

Resolves ``provider_id`` -> connector instance by importing
``energy_research.ingestion.providers.<provider_id>`` and calling its
``build_market_connector`` / ``build_context_connector`` factory. No code outside
this registry ever imports a concrete provider module (enforced by the
import-linter contract "No layer imports a concrete provider adapter").
"""

from __future__ import annotations

import importlib
from typing import Any

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion.connector import MarketDataConnector, QualitativeContextConnector

_PROVIDER_PACKAGE = "energy_research.ingestion.providers"


def _load_provider_module(provider_id: str) -> Any:
    try:
        return importlib.import_module(f"{_PROVIDER_PACKAGE}.{provider_id}")
    except ImportError as exc:
        raise LookupError(
            f"no connector implementation for provider_id={provider_id!r}: expected module "
            f"{_PROVIDER_PACKAGE}.{provider_id} (check providers.yaml)"
        ) from exc


def market_connectors(config: PipelineConfig) -> dict[str, MarketDataConnector]:
    """provider_id -> MarketDataConnector for every configured market-data provider."""
    result: dict[str, MarketDataConnector] = {}
    for entry in config.providers.market_data:
        module = _load_provider_module(entry.provider_id)
        if not hasattr(module, "build_market_connector"):
            raise LookupError(
                f"provider module {entry.provider_id!r} defines no build_market_connector()"
            )
        connector = module.build_market_connector(entry.options, config)
        if not isinstance(connector, MarketDataConnector):
            raise TypeError(f"provider {entry.provider_id!r} did not return a MarketDataConnector")
        result[entry.provider_id] = connector
    return result


def context_connectors(config: PipelineConfig) -> dict[str, QualitativeContextConnector]:
    """provider_id -> QualitativeContextConnector for every configured context provider."""
    result: dict[str, QualitativeContextConnector] = {}
    for entry in config.providers.qualitative_context:
        module = _load_provider_module(entry.provider_id)
        if not hasattr(module, "build_context_connector"):
            raise LookupError(
                f"provider module {entry.provider_id!r} defines no build_context_connector()"
            )
        connector = module.build_context_connector(entry.options, config)
        if not isinstance(connector, QualitativeContextConnector):
            raise TypeError(
                f"provider {entry.provider_id!r} did not return a QualitativeContextConnector"
            )
        result[entry.provider_id] = connector
    return result
