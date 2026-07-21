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

import csv
import io
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
    # JMESPath into the raw response locating the elements array, for envelopes
    # that are neither a bare array nor {"data": [...]} (e.g. "records" or
    # "result.records"). None preserves the original data-key/bare-array lookup.
    results_path: str | None = None
    # strptime pattern for non-ISO timestamp strings (e.g. "%d/%m/%Y"). None
    # preserves the original datetime.fromisoformat parsing.
    ts_format: str | None = None
    # "csv" parses the response body as delimited text: each row becomes a dict
    # keyed by the header row, so the same JMESPath field_mapping applies. "json"
    # (default) preserves the original behavior. Needed for open-data portals that
    # publish plain CSV files with no JSON API (e.g. ONS's S3-hosted datasets).
    response_format: Literal["json", "csv"] = "json"
    csv_delimiter: str = ";"
    csv_encoding: str = "utf-8"
    # JMESPath predicate evaluated per element; only truthy elements are kept.
    # For files that interleave many instruments/regions in one response (e.g.
    # ONS files carry all four subsystems: nom_subsistema == 'SUDESTE').
    row_filter: str | None = None
    # "daily_mean" collapses sub-daily observations to one per calendar day (the
    # mean), e.g. ONS's semi-hourly CMO -> the standard daily-average figure.
    # None preserves observations exactly as the provider publishes them.
    aggregate: Literal["daily_mean"] | None = None
    # [floor, ceiling] applied to every mapped value (either bound may be null).
    # For proxy construction where the target series is a regulatory clamp of the
    # source (PLD = CMO bounded by ANEEL's yearly floor/ceiling) — also prevents
    # zero-price pathologies in percent-return math downstream. The clamp is part
    # of the declared descriptor, never a silent correction (Principle VII).
    value_clamp: tuple[float | None, float | None] | None = None
    # provider-native instrument value -> canonical instrument_key, for responses
    # that interleave SEVERAL instruments in one payload (ONS files carry all four
    # submarkets: {SE: BR_POWER_SE_SPOT, S: BR_POWER_S_SPOT, ...}). When set,
    # fetch_series keeps only the rows whose translated key matches the requested
    # instrument; unmapped values are dropped, never guessed (Principle IV).
    instrument_key_map: dict[str, str] | None = None


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
    # None means the vendor is a public open-data endpoint and NO Authorization
    # header is sent (some hosts, e.g. plain S3, reject a stray Bearer header).
    # This does not weaken contract rule 1: a credential that IS configured but
    # fails to resolve still raises CredentialError — only an explicitly absent
    # credential block means "public".
    credential: _CredentialReference | None = None
    base_url: str
    endpoints: list[_EndpointSpec] = Field(min_length=1)
    pagination: _PaginationSpec = _PaginationSpec()
    # HTTP timeout per request. Some public APIs generate multi-year extracts
    # server-side and legitimately take >30s (observed: BACEN SGS ~30s).
    timeout_seconds: float = Field(default=30.0, gt=0)


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


def _elements_of(payload: Any, results_path: str | None = None) -> list[Any]:
    """The response is either a bare JSON array of elements, a JSON object
    carrying them under a top-level ``data`` key (used whenever an envelope is
    also needed to carry a cursor), or — when the descriptor sets
    ``results_path`` — whatever a JMESPath expression against the response
    locates, for envelopes that use neither convention."""
    if results_path is not None:
        found = jmespath.search(results_path, payload)
        return found if isinstance(found, list) else []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("data", [])
    return []


def _parse_ts(raw: str, ts_format: str | None) -> datetime:
    ts = datetime.strptime(raw, ts_format) if ts_format else datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts


def _daily_mean(observations: list[RawObservation]) -> list[RawObservation]:
    """Collapse sub-daily observations to one per (instrument, calendar day): the
    mean of that day's values, stamped at midnight UTC. Provenance survives:
    'synthetic' wins for the day if any contributing observation was synthetic."""
    groups: dict[tuple[str, str, Any], list[RawObservation]] = {}
    for obs in observations:
        groups.setdefault((obs.category, obs.instrument_key, obs.ts.date()), []).append(obs)
    result = [
        RawObservation(
            category=category,
            instrument_key=instrument_key,
            ts=datetime(day.year, day.month, day.day, tzinfo=UTC),
            value=sum(o.value for o in members) / len(members),
            provenance="synthetic"
            if any(o.provenance == "synthetic" for o in members)
            else "real",
        )
        for (category, instrument_key, day), members in groups.items()
    ]
    result.sort(key=lambda o: (o.instrument_key, o.ts))
    return result


class DeclarativeConnector:
    """Satisfies both ``MarketDataConnector`` and ``QualitativeContextConnector``
    (contracts/data-connector.md) purely from ``self._descriptor``."""

    def __init__(
        self, descriptor: DataSourceDescriptor, transport: httpx.BaseTransport | None = None
    ):
        self._descriptor = descriptor
        self.provider_id = descriptor.provider_id
        self._client = httpx.Client(
            base_url=descriptor.base_url,
            timeout=descriptor.timeout_seconds,
            transport=transport,
        )
        # Per-instance memo of unpaginated GET payloads, keyed by rendered path.
        # A multi-instrument endpoint (instrument_key_map) is fetched once per
        # ingest run, not once per instrument — the connector lives only for the
        # run, so there is no staleness window.
        self._payload_cache: dict[str, Any] = {}

    def _endpoints_for(self, category: str) -> list[_EndpointSpec]:
        """ALL endpoints configured for a category, in descriptor order. A vendor
        that shards one series across several resources (e.g. ONS's one-CSV-per-
        year S3 files) declares one endpoint per shard; fetch concatenates them."""
        endpoints = [ep for ep in self._descriptor.endpoints if ep.category == category]
        if not endpoints:
            raise UnsupportedCategoryError(
                f"{self.provider_id}: no endpoint configured for category {category!r}"
            )
        return endpoints

    def _headers(self) -> dict[str, str]:
        if self._descriptor.credential is None:
            return {}  # public open-data endpoint: no auth header at all
        token = _resolve_credential(self._descriptor.credential, self.provider_id)
        return {"Authorization": f"Bearer {token}"}

    def _request(self, endpoint: _EndpointSpec, path_params: dict, query: dict) -> Any:
        path = endpoint.path_template.format(**path_params)
        # params=None when there are no pagination params: httpx REPLACES a URL's
        # embedded query string with `params` whenever it is not None, which would
        # silently strip query strings baked into path_template (e.g. BACEN's
        # ?formato=json&dataInicial=...).
        response = self._client.request(
            endpoint.method, path, headers=self._headers(), params=query or None
        )
        response.raise_for_status()
        if endpoint.response_format == "csv":
            text = response.content.decode(endpoint.csv_encoding)
            reader = csv.DictReader(io.StringIO(text), delimiter=endpoint.csv_delimiter)
            # Strip stray cell whitespace (ONS pads short subsystem codes: "N ").
            return [
                {(k or "").strip(): (v or "").strip() for k, v in row.items()}
                for row in reader
            ]
        return response.json()

    def _filtered(self, endpoint: _EndpointSpec, elements: list[Any]) -> list[Any]:
        if endpoint.row_filter is None:
            return elements
        return [e for e in elements if jmespath.search(endpoint.row_filter, e)]

    def _fetch_all_elements(self, endpoint: _EndpointSpec, path_params: dict) -> list[Any]:
        pagination = self._descriptor.pagination
        elements: list[Any] = []

        if pagination.mode == "none":
            cache_key = endpoint.path_template.format(**path_params)
            if cache_key not in self._payload_cache:
                self._payload_cache[cache_key] = self._request(endpoint, path_params, {})
            payload = self._payload_cache[cache_key]
            return self._filtered(endpoint, _elements_of(payload, endpoint.results_path))

        if pagination.mode == "offset":
            offset = 0
            while True:
                query = {}
                if pagination.limit_param:
                    query[pagination.limit_param] = 100
                if pagination.offset_param:
                    query[pagination.offset_param] = offset
                payload = self._request(endpoint, path_params, query)
                page = _elements_of(payload, endpoint.results_path)
                if not page:
                    break
                elements.extend(self._filtered(endpoint, page))
                offset += len(page)
            return elements

        if pagination.mode == "cursor":
            cursor: Any = None
            while True:
                query = {}
                if cursor is not None and pagination.cursor_param:
                    query[pagination.cursor_param] = cursor
                payload = self._request(endpoint, path_params, query)
                page = _elements_of(payload, endpoint.results_path)
                elements.extend(self._filtered(endpoint, page))
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
        observations: list[RawObservation] = []
        for endpoint in self._endpoints_for(category):
            elements = self._fetch_all_elements(endpoint, {"instrument_key": instrument_key})
            mapping = endpoint.field_mapping
            batch: list[RawObservation] = []
            for element in elements:
                mapped_key = jmespath.search(mapping["instrument_key"], element)
                if endpoint.instrument_key_map is not None:
                    # Multi-instrument response: translate the provider-native
                    # value and keep only the requested instrument's rows.
                    mapped_key = endpoint.instrument_key_map.get(mapped_key)
                    if mapped_key != instrument_key:
                        continue
                ts_raw = jmespath.search(mapping["ts"], element)
                ts = _parse_ts(ts_raw, endpoint.ts_format)
                if since is not None and ts <= since:
                    continue
                value = float(jmespath.search(mapping["value"], element))
                if endpoint.value_clamp is not None:
                    lo, hi = endpoint.value_clamp
                    if lo is not None:
                        value = max(value, lo)
                    if hi is not None:
                        value = min(value, hi)
                batch.append(
                    RawObservation(
                        category=category,
                        instrument_key=mapped_key or instrument_key,
                        ts=ts,
                        value=value,
                        provenance=jmespath.search(mapping["provenance"], element) or "real",
                    )
                )
            if endpoint.aggregate == "daily_mean":
                batch = _daily_mean(batch)
            observations.extend(batch)
        observations.sort(key=lambda o: (o.instrument_key, o.ts))
        return observations

    def fetch_context(self, category: str, since: datetime | None = None) -> list[RawContextDoc]:
        docs: list[RawContextDoc] = []
        for endpoint in self._endpoints_for(category):
            elements = self._fetch_all_elements(endpoint, {})
            mapping = endpoint.field_mapping
            for element in elements:
                ts_raw = jmespath.search(mapping["ts"], element)
                ts = _parse_ts(ts_raw, endpoint.ts_format)
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
            if self._descriptor.credential is not None:
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
