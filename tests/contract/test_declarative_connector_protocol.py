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


def test_results_path_and_ts_format_handle_a_ckan_style_columnar_envelope(monkeypatch):
    """Mirrors CCEE Dados Abertos' real /datastore/dump/ shape: elements live
    under a top-level "records" key (not "data"), each element is a positional
    array (not a keyed object), and the date is DD/MM/AAAA, not ISO-8601."""
    monkeypatch.setenv("FIXTURE_VENDOR_API_KEY", "secret-token")
    descriptor = {
        "provider_id": "ckan_style_vendor",
        "credential": {"env_var_name": "FIXTURE_VENDOR_API_KEY", "purpose": "market_data"},
        "base_url": "https://fixture.example.test",
        "endpoints": [
            {
                "category": "spot",
                "path_template": "/datastore/dump/abc123",
                "method": "GET",
                "field_mapping": {
                    "instrument_key": "[2]",
                    "ts": "[3]",
                    "value": "[4]",
                    "provenance": '`"real"`',
                },
                "results_path": "records",
                "ts_format": "%d/%m/%Y",
            }
        ],
        "pagination": {"mode": "none"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "fields": [
                    {"id": "_id", "type": "int"},
                    {"id": "MES_REFERENCIA", "type": "text"},
                    {"id": "SUBMERCADO", "type": "text"},
                    {"id": "DIA", "type": "text"},
                    {"id": "PLD_MEDIA_DIA", "type": "numeric"},
                ],
                "records": [
                    [1, "202605", "NORDESTE", "14/05/2026", 188.53],
                    [2, "202605", "NORTE", "14/05/2026", 202.2],
                ],
            },
        )

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("spot", "NORDESTE")

    assert len(observations) == 2
    assert observations[0].instrument_key == "NORDESTE"
    assert observations[0].value == 188.53
    assert observations[0].provenance == "real"
    assert observations[0].ts.year == 2026
    assert observations[0].ts.month == 5
    assert observations[0].ts.day == 14


def test_results_path_ignores_non_list_result(monkeypatch):
    monkeypatch.setenv("FIXTURE_VENDOR_API_KEY", "secret-token")
    descriptor = dict(MARKET_DESCRIPTOR)
    descriptor["endpoints"] = [dict(MARKET_DESCRIPTOR["endpoints"][0], results_path="missing.key")]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    assert connector.fetch_series("spot", "FIX_INST") == []


def test_csv_response_with_row_filter_and_no_credential():
    """Mirrors ONS's real S3-hosted open-data shape: a public CSV (no auth — S3
    rejects stray Authorization headers), semicolon-delimited, all four
    subsystems interleaved, ISO dates. No credential block in the descriptor
    means NO Authorization header is sent at all."""
    descriptor = {
        "provider_id": "ons_style_vendor",
        "base_url": "https://opendata.example.test",
        "endpoints": [
            {
                "category": "hydrology",
                "path_template": "/dataset/ear/EAR_2026.csv",
                "method": "GET",
                "response_format": "csv",
                "row_filter": "nom_subsistema == 'SUDESTE'",
                "field_mapping": {
                    "instrument_key": '`"BR_HYDRO_SE_RESERVOIR"`',
                    "ts": "ear_data",
                    "value": "ear_verif_subsistema_percentual",
                    "provenance": '`"real"`',
                },
            }
        ],
        "pagination": {"mode": "none"},
    }
    body = (
        "id_subsistema;nom_subsistema;ear_data;ear_max;ear_verif;"
        "ear_verif_subsistema_percentual\n"
        "NE;NORDESTE;2026-01-01;51691.2;23746.6;45.9395\n"
        "N ;NORTE;2026-01-01;15302.3;8377.9;54.749\n"
        "SE;SUDESTE;2026-01-01;204615.3;130769.9;63.9102\n"
        "SE;SUDESTE;2026-01-02;204615.3;131000.0;64.0225\n"
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, content=body.encode(), headers={"content-type": "text/csv"})

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("hydrology", "BR_HYDRO_SE_RESERVOIR")

    assert seen["authorization"] is None  # public endpoint: no Bearer header
    assert len(observations) == 2  # only the SUDESTE rows survive the filter
    assert observations[0].instrument_key == "BR_HYDRO_SE_RESERVOIR"
    assert observations[0].value == 63.9102
    assert observations[0].provenance == "real"
    assert observations[1].ts.day == 2


def test_daily_mean_aggregation_collapses_subdaily_rows():
    """ONS's CMO is semi-hourly (48 rows/day); aggregate=daily_mean yields one
    observation per calendar day carrying that day's mean."""
    descriptor = {
        "provider_id": "ons_cmo_style_vendor",
        "base_url": "https://opendata.example.test",
        "endpoints": [
            {
                "category": "spot",
                "path_template": "/dataset/cmo/CMO_2026.csv",
                "response_format": "csv",
                "row_filter": "nom_subsistema == 'SUDESTE'",
                "aggregate": "daily_mean",
                "field_mapping": {
                    "instrument_key": '`"BR_POWER_SE_SPOT"`',
                    "ts": "din_instante",
                    "value": "val_cmo",
                    "provenance": '`"real"`',
                },
            }
        ],
        "pagination": {"mode": "none"},
    }
    body = (
        "id_subsistema;nom_subsistema;din_instante;val_cmo\n"
        "SE;SUDESTE;2026-01-01 00:00:00;100.0\n"
        "SE;SUDESTE;2026-01-01 00:30:00;200.0\n"
        "S;SUL;2026-01-01 00:00:00;999.0\n"
        "SE;SUDESTE;2026-01-02 00:00:00;150.0\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("spot", "BR_POWER_SE_SPOT")

    assert len(observations) == 2
    assert observations[0].ts.isoformat() == "2026-01-01T00:00:00+00:00"
    assert observations[0].value == 150.0  # mean(100, 200); SUL row filtered out
    assert observations[1].value == 150.0
    assert observations[1].ts.day == 2


def test_multiple_endpoints_per_category_concatenate_in_order():
    """A vendor that shards one series across several resources (ONS's one-CSV-
    per-year S3 files) declares one endpoint per shard under the SAME category;
    fetch_series concatenates all shards, sorted by timestamp."""
    descriptor = {
        "provider_id": "sharded_vendor",
        "base_url": "https://opendata.example.test",
        "endpoints": [
            {
                "category": "hydrology",
                "path_template": f"/dataset/ear/EAR_{year}.csv",
                "response_format": "csv",
                "field_mapping": {
                    "instrument_key": '`"BR_HYDRO_SE_RESERVOIR"`',
                    "ts": "ear_data",
                    "value": "pct",
                    "provenance": '`"real"`',
                },
            }
            for year in (2025, 2026)
        ],
        "pagination": {"mode": "none"},
    }
    bodies = {
        "/dataset/ear/EAR_2025.csv": "ear_data;pct\n2025-12-30;50.0\n2025-12-31;51.0\n",
        "/dataset/ear/EAR_2026.csv": "ear_data;pct\n2026-01-01;52.0\n",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bodies[request.url.path].encode())

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("hydrology", "BR_HYDRO_SE_RESERVOIR")

    assert [o.value for o in observations] == [50.0, 51.0, 52.0]
    assert observations[0].ts.year == 2025 and observations[-1].ts.year == 2026


def test_configured_credential_still_raises_when_env_missing(monkeypatch):
    """Optional-credential support must not weaken contract rule 1: a credential
    that IS configured but cannot resolve raises — only an explicitly absent
    credential block means public/no-auth."""
    monkeypatch.delenv("FIXTURE_VENDOR_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not issue a request without a resolved credential")

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(MARKET_DESCRIPTOR),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(CredentialError):
        connector.fetch_series("spot", "FIX_INST")
    health = connector.health_check()
    assert health.ok is False


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


def test_value_clamp_bounds_mapped_values():
    """value_clamp=[floor, ceiling] applies the declared regulatory band to every
    mapped value — the PLD-proxy construction (PLD = CMO clamped to ANEEL's
    yearly floor/ceiling), which also prevents zero-price return blowups."""
    descriptor = {
        "provider_id": "clamped_vendor",
        "base_url": "https://opendata.example.test",
        "endpoints": [
            {
                "category": "spot",
                "path_template": "/cmo.csv",
                "response_format": "csv",
                "value_clamp": [39.68, 559.75],
                "field_mapping": {
                    "instrument_key": '`"BR_POWER_SE_SPOT"`',
                    "ts": "d",
                    "value": "v",
                    "provenance": '`"real"`',
                },
            }
        ],
        "pagination": {"mode": "none"},
    }
    body = "d;v\n2020-01-01;0.0\n2020-01-02;150.0\n2020-01-03;2000.0\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    observations = connector.fetch_series("spot", "BR_POWER_SE_SPOT")
    assert [o.value for o in observations] == [39.68, 150.0, 559.75]


def test_instrument_key_map_filters_and_caches_multi_instrument_responses():
    """One ONS file carries all four submarkets: instrument_key_map translates
    provider-native codes to canonical keys and fetch_series keeps only the
    requested instrument's rows. The payload is fetched ONCE per path per
    connector instance, not once per instrument."""
    descriptor = {
        "provider_id": "multi_instrument_vendor",
        "base_url": "https://opendata.example.test",
        "endpoints": [
            {
                "category": "spot",
                "path_template": "/cmo.csv",
                "response_format": "csv",
                "instrument_key_map": {
                    "SE": "BR_POWER_SE_SPOT",
                    "NE": "BR_POWER_NE_SPOT",
                },
                "field_mapping": {
                    "instrument_key": "id_subsistema",
                    "ts": "d",
                    "value": "v",
                    "provenance": '`"real"`',
                },
            }
        ],
        "pagination": {"mode": "none"},
    }
    body = (
        "id_subsistema;d;v\n"
        "SE;2026-01-01;100.0\n"
        "NE;2026-01-01;200.0\n"
        "S ;2026-01-01;300.0\n"  # unmapped (padded) code: dropped, never guessed
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=body.encode())

    connector = DeclarativeConnector(
        DataSourceDescriptor.model_validate(descriptor),
        transport=httpx.MockTransport(handler),
    )
    se = connector.fetch_series("spot", "BR_POWER_SE_SPOT")
    ne = connector.fetch_series("spot", "BR_POWER_NE_SPOT")

    assert [o.value for o in se] == [100.0]
    assert se[0].instrument_key == "BR_POWER_SE_SPOT"
    assert [o.value for o in ne] == [200.0]
    assert calls["n"] == 1  # second instrument served from the payload cache
