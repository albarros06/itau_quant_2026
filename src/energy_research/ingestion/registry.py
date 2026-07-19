"""Config-keyed provider registry (FR-002).

Resolves ``provider_id`` -> connector instance. Two dispatch modes per provider
entry's ``connector_kind`` (data-model.md "Registry extension", 002 ops_agent):

- ``python_module`` (default): imports ``energy_research.ingestion.providers.
  <provider_id>`` and calls its ``build_market_connector``/``build_context_connector``
  factory — today's exact, unchanged behavior.
- ``declarative``: routes to the one shared ``ingestion.providers.declarative``
  module instead, handing it the ``DataSourceDescriptor`` carried in ``options``
  (FR-016/017) — no per-vendor Python module involved.

No code outside this registry ever imports a concrete provider module (enforced by
the import-linter contract "No layer imports a concrete provider adapter").
"""

from __future__ import annotations

import importlib
from typing import Any

from energy_research.config.settings import ConnectorKind, PipelineConfig
from energy_research.ingestion.connector import MarketDataConnector, QualitativeContextConnector

_PROVIDER_PACKAGE = "energy_research.ingestion.providers"
_DECLARATIVE_MODULE = f"{_PROVIDER_PACKAGE}.declarative"


def _load_provider_module(provider_id: str, connector_kind: ConnectorKind) -> Any:
    if connector_kind == "declarative":
        return importlib.import_module(_DECLARATIVE_MODULE)
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
        module = _load_provider_module(entry.provider_id, entry.connector_kind)
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
        module = _load_provider_module(entry.provider_id, entry.connector_kind)
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
