from __future__ import annotations

from ops_agent.budget import BudgetGuard
from ops_agent.discovery.vendor_probe import (
    CatalogEntry,
    VendorCatalog,
    _parse_entries,
    probe_vendor,
)
from ops_agent.store.repository import Repository


def test_parse_entries_ignores_malformed_shapes():
    assert _parse_entries(None) == []
    assert _parse_entries("not-a-dict") == []
    assert _parse_entries({}) == []
    assert _parse_entries({"entries": "not-a-list"}) == []
    assert _parse_entries({"entries": ["not-a-dict"]}) == []


def test_parse_entries_coerces_missing_fields_to_defaults():
    parsed = _parse_entries({"entries": [{"category": "spot"}]})
    assert parsed == [CatalogEntry(category="spot", instrument_hints=[], notes="")]


class _AlwaysUnhealthyConnector:
    provider_id = "flaky_vendor"

    def health_check(self):
        raise RuntimeError("connection refused")


def test_probe_vendor_records_credential_error_and_returns_unhealthy_catalog(tmp_path):
    repo = Repository(tmp_path / "ops_agent.sqlite")
    try:
        from ops_agent.config import ResourceBudgetConfig

        guard = BudgetGuard(
            ResourceBudgetConfig(period="daily", max_llm_calls=10, max_vendor_requests=10),
            repo,
            None,
        )
        catalog = probe_vendor("flaky_vendor", _AlwaysUnhealthyConnector(), guard, repo)
        assert catalog == VendorCatalog(
            provider_id="flaky_vendor", entries=[], healthy=False, detail="connection refused"
        )
        errors = [r for r in repo.read_activity() if r["action"] == "credential_error"]
        assert len(errors) == 1
        assert errors[0]["outcome"] == "failed"
    finally:
        repo.close()
