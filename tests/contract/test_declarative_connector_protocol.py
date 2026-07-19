"""Contract test: declarative connector protocol conformance
(contracts/declarative-connector.md, 001's contracts/data-connector.md).
"""

from __future__ import annotations

import httpx
import pytest

from energy_research.ingestion.connector import MarketDataConnector, QualitativeContextConnector
from energy_research.ingestion.providers.declarative import (
    CredentialError,
    DataSourceDescriptor,
    DeclarativeConnector,
)

MARKET_DESCRIPTOR = {
    "provider_id": "fixture_vendor",
    "credential": {"env_var_name": "FIXTURE_VENDOR_API_KEY", "purpose": "market_data"},
    "base_url": "https://fixture.example.test",
    "endpoints": [
        {
            "category": "spot",
            "path_template": "/v1/series/{instrument_key}",
            "method": "GET",
            "field_mapping": {
                "instrument_key": "id",
                "category": "category",
                "ts": "timestamp",
                "value": "price.last",
                "provenance": "provenance",
            },
        }
    ],
    "pagination": {"mode": "none"},
}

CONTEXT_DESCRIPTOR = {
    "provider_id": "fixture_news_vendor",
    "credential": {"env_var_name": "FIXTURE_NEWS_API_KEY", "purpose": "qualitative_context"},
    "base_url": "https://fixture-news.example.test",
    "endpoints": [
        {
            "category": "news",
            "path_template": "/v1/news",
            "method": "GET",
            "field_mapping": {
                "source": "outlet",
                "ts": "published_at",
                "text": "headline",
                "provenance": "provenance",
            },
        }
    ],
    "pagination": {"mode": "none"},
}


def test_satisfies_both_connector_protocols(monkeypatch):
    monkeypatch.setenv("FIXTURE_VENDOR_API_KEY", "secret-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(MARKET_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    assert isinstance(connector, MarketDataConnector)
    assert isinstance(connector, QualitativeContextConnector)
    assert connector.provider_id == "fixture_vendor"


def test_fixture_market_response_maps_to_raw_observations(monkeypatch):
    monkeypatch.setenv("FIXTURE_VENDOR_API_KEY", "secret-token")
    seen_auth = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth["authorization"] = request.headers.get("authorization")
        assert request.url.path == "/v1/series/FIX_INST"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "FIX_INST",
                    "category": "spot",
                    "timestamp": "2026-07-01T00:00:00+00:00",
                    "price": {"last": 12.5},
                    "provenance": "real",
                },
                {
                    "id": "FIX_INST",
                    "category": "spot",
                    "timestamp": "2026-07-02T00:00:00+00:00",
                    "price": {"last": 13.0},
                    "provenance": "real",
                },
            ],
        )

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(MARKET_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("spot", "FIX_INST")

    assert seen_auth["authorization"] == "Bearer secret-token"
    assert len(observations) == 2
    assert observations[0].instrument_key == "FIX_INST"
    assert observations[0].value == 12.5
    assert observations[0].provenance == "real"
    assert observations[1].value == 13.0


def test_fixture_context_response_maps_to_raw_context_docs(monkeypatch):
    monkeypatch.setenv("FIXTURE_NEWS_API_KEY", "secret-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "outlet": "Fixture Wire",
                    "published_at": "2026-07-01T00:00:00+00:00",
                    "headline": "fixture headline",
                    "provenance": "real",
                }
            ],
        )

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(CONTEXT_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    docs = connector.fetch_context("news")
    assert len(docs) == 1
    assert docs[0].source == "Fixture Wire"
    assert docs[0].text == "fixture headline"
    assert docs[0].provenance == "real"


def test_offset_pagination_loops_until_an_empty_page(monkeypatch):
    monkeypatch.setenv("FIXTURE_VENDOR_API_KEY", "secret-token")
    descriptor = dict(MARKET_DESCRIPTOR)
    descriptor["pagination"] = {
        "mode": "offset",
        "limit_param": "limit",
        "offset_param": "offset",
    }
    pages = [
        [
            {
                "id": "FIX_INST",
                "timestamp": "2026-07-01T00:00:00+00:00",
                "price": {"last": 1.0},
                "provenance": "real",
            }
        ],
        [
            {
                "id": "FIX_INST",
                "timestamp": "2026-07-02T00:00:00+00:00",
                "price": {"last": 2.0},
                "provenance": "real",
            }
        ],
        [],
    ]
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[calls["n"]]
        calls["n"] += 1
        return httpx.Response(200, json=page)

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("spot", "FIX_INST")
    assert len(observations) == 2
    assert calls["n"] == 3  # two pages of data + one empty page to stop


def test_missing_credential_raises_visibly_never_treated_as_no_auth(monkeypatch):
    monkeypatch.delenv("FIXTURE_VENDOR_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not issue a request without a resolved credential")

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(MARKET_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CredentialError):
        connector.fetch_series("spot", "FIX_INST")


def test_health_check_reports_missing_credential_without_raising(monkeypatch):
    monkeypatch.delenv("FIXTURE_VENDOR_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not issue a request without a resolved credential")

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(MARKET_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    health = connector.health_check()
    assert health.ok is False
    assert "FIXTURE_VENDOR_API_KEY" in health.detail
