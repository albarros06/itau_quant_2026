from __future__ import annotations

import pytest

from ops_agent.budget import BudgetGuard
from ops_agent.config import ResourceBudgetConfig
from ops_agent.onboarding.draft import draft_onboarding
from ops_agent.store.repository import Repository


class _StaticBackend:
    def __init__(self, payload):
        self._payload = payload

    def complete(self, request):
        return [self._payload]


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "ops_agent.sqlite")
    yield r
    r.close()


@pytest.fixture
def guard(repo):
    return BudgetGuard(
        ResourceBudgetConfig(period="daily", max_llm_calls=10, max_vendor_requests=10), repo, None
    )


def test_invalid_payload_returns_none_and_logs_a_failed_limitation(repo, guard):
    backend = _StaticBackend({"descriptor": {"provider_id": "x"}})  # missing required fields
    result = draft_onboarding("bad_vendor", "{}", backend, guard, repo)
    assert result is None
    rows = [r for r in repo.read_activity() if r["action"] == "limitation_reported"]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failed"


def test_neither_descriptor_nor_limitation_returns_none(repo, guard):
    backend = _StaticBackend({})
    result = draft_onboarding("empty_vendor", "{}", backend, guard, repo)
    assert result is None
    rows = [r for r in repo.read_activity() if r["action"] == "limitation_reported"]
    assert any("neither a descriptor nor a limitation" in r["reason"] for r in rows)


def test_valid_limitation_payload_is_returned_uninterpreted(repo, guard):
    backend = _StaticBackend(
        {
            "limitation": {
                "provider_id": "v",
                "reason": "no REST API",
                "unsupported_aspect": "transport",
            }
        }
    )
    draft = draft_onboarding("ftp_vendor", "{}", backend, guard, repo)
    assert draft is not None
    assert draft.limitation.unsupported_aspect == "transport"
    assert draft.descriptor is None
