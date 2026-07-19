"""US4 end-to-end: config-only vendor onboarding (spec.md User Story 4,
Acceptance Scenarios 1-3).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from energy_research.config.settings import load_config
from energy_research.datastore.repository import Repository
from ops_agent.agent import OpsAgent
from ops_agent.proposals.models import OnboardingLimitation


def _make_fixture_vendor_server() -> tuple[HTTPServer, str]:
    now = datetime.now(UTC)
    observations = [
        {
            "id": "BR_POWER_SE_SPOT",
            "timestamp": (now - timedelta(days=n)).isoformat(),
            "price": {"last": 100.0 + n},
            "provenance": "real",
        }
        for n in range(10)
    ]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if self.path.startswith("/v1/series/__health_check__"):
                self.wfile.write(b"[]")
            else:
                self.wfile.write(json.dumps(observations).encode())

        def log_message(self, format, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    return server, base_url


@pytest.fixture
def fixture_vendor_server():
    server, base_url = _make_fixture_vendor_server()
    yield base_url
    server.shutdown()


def test_config_only_onboarding_to_ingestion_and_full_cycle(
    ops_agent_repo, fixture_vendor_server, monkeypatch
):
    repo_dir, config = ops_agent_repo
    monkeypatch.setenv("NEW_VENDOR_API_KEY", "secret-token")

    from pathlib import Path as _Path

    import energy_research.ingestion.providers as providers_pkg

    files_before = {p.name for p in _Path(providers_pkg.__file__).parent.glob("*.py")}

    interface_doc = json.dumps(
        {
            "credential": {"env_var_name": "NEW_VENDOR_API_KEY", "purpose": "market_data"},
            "base_url": fixture_vendor_server,
            "endpoints": [
                {
                    "category": "spot",
                    "path_template": "/v1/series/{instrument_key}",
                    "method": "GET",
                    "field_mapping": {
                        "instrument_key": "id",
                        "category": "id",
                        "ts": "timestamp",
                        "value": "price.last",
                        "provenance": "provenance",
                    },
                }
            ],
            "pagination": {"mode": "none"},
        }
    )

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        result = agent.onboard("new_vendor", interface_doc)
        assert not isinstance(result, OnboardingLimitation)
        assert result.kind == "onboarding"
        assert result.target_files == ["config/providers.yaml"]

        approved = agent.git_store.approve(result.id)
        assert approved.status in ("approved", "edited_and_approved")

    files_after = {p.name for p in _Path(providers_pkg.__file__).parent.glob("*.py")}
    assert files_after == files_before, (
        "onboarding must add zero new files under ingestion/providers/"
    )

    providers_raw = yaml.safe_load((repo_dir / "config" / "providers.yaml").read_text())
    new_entry = next(e for e in providers_raw["market_data"] if e["provider_id"] == "new_vendor")
    assert new_entry["connector_kind"] == "declarative"
    assert new_entry["options"]["base_url"] == fixture_vendor_server

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        tick_result = agent.tick()
    assert tick_result["cycle_ran"] is True
    assert tick_result["report_path"].exists()

    pipeline_config = load_config(repo_dir / "config" / "default.yaml")
    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        new_vendor_series = [r for r in repo.series_rows() if r["provider_id"] == "new_vendor"]
        assert new_vendor_series, "new_vendor's series must be ingested and quality-checked"
        assert new_vendor_series[0]["quality_status"] in ("clean", "flagged")
    finally:
        repo.close()


def test_unsupported_interface_reports_an_explicit_limitation(ops_agent_repo):
    repo_dir, config = ops_agent_repo
    interface_doc = json.dumps(
        {
            "unsupported_aspect": "auth",
            "reason": "vendor requires a full OAuth2 authorization-code handshake, "
            "not a single bearer/API-key header",
        }
    )

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        result = agent.onboard("oauth_only_vendor", interface_doc)
        activity = agent.repo.read_activity()
        # No proposal was opened for an unsupported interface.
        pending_proposals = agent.repo.list_proposals()

    assert isinstance(result, OnboardingLimitation)
    assert result.unsupported_aspect == "auth"
    assert "OAuth2" in result.reason

    limitation_rows = [r for r in activity if r["action"] == "limitation_reported"]
    assert any(r["target"] == "oauth_only_vendor" and r["outcome"] == "ok" for r in limitation_rows)
    assert pending_proposals == []
