"""Shared, config-driven connector for config-only vendor onboarding
(contracts/declarative-connector.md, FR-016-018).

Implements both ``MarketDataConnector`` and ``QualitativeContextConnector`` purely
by interpreting a Data Source Descriptor carried in a provider entry's ``options``
dict — never a per-vendor Python module (research.md §4). The descriptor's shape
mirrors ``ops_agent.proposals.models.DataSourceDescriptor``, but this module
defines its own local models rather than importing them: ``energy_research`` must
never import ``ops_agent`` (contracts/ops-agent-boundary.md rule 1).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
import jmespath
from pydantic import BaseModel, ConfigDict, Field

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion.connector import ConnectorHealth, RawContextDoc, RawObservation


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CredentialReference(_StrictModel):
    env_var_name: str
    purpose: Literal["llm", "market_data", "qualitative_context"]


class _EndpointSpec(_StrictModel):
    category: str
    path_template: str
    method: Literal["GET", "POST"] = "GET"
    field_mapping: dict[str, str]


class _PaginationSpec(_StrictModel):
    mode: Literal["none", "offset", "cursor"] = "none"
    limit_param: str | None = None
    offset_param: str | None = None
    cursor_param: str | None = None
    next_cursor_path: str | None = None


class DataSourceDescriptor(_StrictModel):
    """Local, standalone parse of the descriptor shape — never imported from
    ``ops_agent`` (see module docstring)."""

    provider_id: str
    credential: _CredentialReference
    base_url: str
    endpoints: list[_EndpointSpec] = Field(min_length=1)
    pagination: _PaginationSpec = _PaginationSpec()


class CredentialError(RuntimeError):
    """A referenced credential is missing or empty — never silently treated as
    "no auth" (FR-001, contracts/declarative-connector.md rule 1)."""


class UnsupportedCategoryError(LookupError):
    pass


def _resolve_credential(ref: _CredentialReference, provider_id: str) -> str:
    value = os.environ.get(ref.env_var_name)
    if not value:
        raise CredentialError(
            f"vendor {provider_id!r}: credential env var {ref.env_var_name!r} is not set or empty"
        )
    return value


def _elements_of(payload: Any) -> list[Any]:
    """The response is either a bare JSON array of elements, or a JSON object
    carrying them under a top-level ``data`` key (used whenever an envelope is
    also needed to carry a cursor)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data", [])
    return []


class DeclarativeConnector:
    """Satisfies both ``MarketDataConnector`` and ``QualitativeContextConnector``
    (contracts/data-connector.md) purely from ``self._descriptor``."""

    def __init__(
        self, descriptor: DataSourceDescriptor, transport: httpx.BaseTransport | None = None
    ):
        self._descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self._client = httpx.Client(base_url=descriptor.base_url, timeout=30.0, transport=transport)

    def _endpoint_for(self, category: str) -> _EndpointSpec:
        for ep in self._descriptor.endpoints:
            if ep.category == category:
                return ep
        raise UnsupportedCategoryError(
            f"{self.provider_id}: no endpoint configured for category {category!r}"
        )

    def _headers(self) -> dict[str, str]:
        token = _resolve_credential(self._descriptor.credential, self.provider_id)
        return {"Authorization": f"Bearer {token}"}

    def _request(self, endpoint: _EndpointSpec, path_params: dict, query: dict) -> Any:
        path = endpoint.path_template.format(**path_params)
        response = self._client.request(
            endpoint.method, path, headers=self._headers(), params=query
        )
        response.raise_for_status()
        return response.json()

    def _fetch_all_elements(self, endpoint: _EndpointSpec, path_params: dict) -> list[Any]:
        pagination = self._descriptor.pagination
        elements: list[Any] = []

        if pagination.mode == "none":
            payload = self._request(endpoint, path_params, {})
            return _elements_of(payload)

        if pagination.mode == "offset":
            offset = 0
            while True:
                query = {}
                if pagination.limit_param:
                    query[pagination.limit_param] = 100
                if pagination.offset_param:
                    query[pagination.offset_param] = offset
                payload = self._request(endpoint, path_params, query)
                page = _elements_of(payload)
                if not page:
                    break
                elements.extend(page)
                offset += len(page)
            return elements

        if pagination.mode == "cursor":
            cursor: Any = None
            while True:
                query = {}
                if cursor is not None and pagination.cursor_param:
                    query[pagination.cursor_param] = cursor
                payload = self._request(endpoint, path_params, query)
                elements.extend(_elements_of(payload))
                next_cursor = (
                    jmespath.search(pagination.next_cursor_path, payload)
                    if pagination.next_cursor_path
                    else None
                )
                if not next_cursor:
                    break
                cursor = next_cursor
            return elements

        raise ValueError(f"unsupported pagination mode {pagination.mode!r}")

    def fetch_series(
        self, category: str, instrument_key: str, since: datetime | None = None
    ) -> list[RawObservation]:
        endpoint = self._endpoint_for(category)
        elements = self._fetch_all_elements(endpoint, {"instrument_key": instrument_key})
        mapping = endpoint.field_mapping
        observations: list[RawObservation] = []
        for element in elements:
            ts_raw = jmespath.search(mapping["ts"], element)
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if since is not None and ts <= since:
                continue
            observations.append(
                RawObservation(
                    category=category,
                    instrument_key=jmespath.search(mapping["instrument_key"], element)
                    or instrument_key,
                    ts=ts,
                    value=float(jmespath.search(mapping["value"], element)),
                    provenance=jmespath.search(mapping["provenance"], element) or "real",
                )
            )
        return observations

    def fetch_context(self, category: str, since: datetime | None = None) -> list[RawContextDoc]:
        endpoint = self._endpoint_for(category)
        elements = self._fetch_all_elements(endpoint, {})
        mapping = endpoint.field_mapping
        docs: list[RawContextDoc] = []
        for element in elements:
            ts_raw = jmespath.search(mapping["ts"], element)
            ts = datetime.fromisoformat(ts_raw)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if since is not None and ts <= since:
                continue
            docs.append(
                RawContextDoc(
                    category=category,
                    source=jmespath.search(mapping["source"], element) or self.provider_id,
                    ts=ts,
                    text=jmespath.search(mapping["text"], element),
                    provenance=jmespath.search(mapping["provenance"], element) or "real",
                )
            )
        return docs

    def health_check(self) -> ConnectorHealth:
        try:
            _resolve_credential(self._descriptor.credential, self.provider_id)
        except CredentialError as exc:
            return ConnectorHealth(ok=False, detail=str(exc))
        endpoint = self._descriptor.endpoints[0]
        try:
            path = endpoint.path_template.format(instrument_key="__health_check__")
            response = self._client.request(endpoint.method, path, headers=self._headers())
            response.raise_for_status()
        except Exception as exc:
            return ConnectorHealth(ok=False, detail=f"{self.provider_id}: {exc}")
        return ConnectorHealth(
            ok=True, detail=f"{self.provider_id}: reachable at {endpoint.path_template}"
        )

    def discover(self) -> dict:
        """Probes each configured endpoint (research.md §5) and reports whatever
        category/instrument metadata the response exposes."""
        entries = []
        for endpoint in self._descriptor.endpoints:
            try:
                elements = self._fetch_all_elements(endpoint, {"instrument_key": ""})
            except Exception as exc:
                entries.append(
                    {"category": endpoint.category, "instrument_hints": [], "notes": str(exc)}
                )
                continue
            hints = []
            if "instrument_key" in endpoint.field_mapping:
                hints = sorted(
                    {
                        v
                        for e in elements
                        if (v := jmespath.search(endpoint.field_mapping["instrument_key"], e))
                    }
                )
            entries.append(
                {
                    "category": endpoint.category,
                    "instrument_hints": hints,
                    "notes": f"{len(elements)} element(s) observed via declarative probe",
                }
            )
        return {"provider_id": self.provider_id, "entries": entries}


def _build_descriptor(options: dict) -> DataSourceDescriptor:
    return DataSourceDescriptor.model_validate(options)


def build_market_connector(options: dict, config: PipelineConfig) -> DeclarativeConnector:
    return DeclarativeConnector(_build_descriptor(options))


def build_context_connector(options: dict, config: PipelineConfig) -> DeclarativeConnector:
    return DeclarativeConnector(_build_descriptor(options))
