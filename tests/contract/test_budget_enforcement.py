"""Contract test: resource budget enforcement (contracts/budget-contract.md, FR-022).

Covers both discretionary kinds (``llm``, ``vendor_request``) so a regression in
either call site (e.g. an unguarded discovery probe) is caught here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ops_agent.budget import BudgetExhausted, BudgetGuard, _period_key
from ops_agent.config import ResourceBudgetConfig
from ops_agent.store.repository import Repository


class _CapturingSink:
    def __init__(self):
        self.events: list[dict] = []

    def send(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "ops_agent.sqlite")
    yield r
    r.close()


@pytest.mark.parametrize("kind", ["llm", "vendor_request"])
def test_guard_raises_at_configured_limit_and_blocks_further_calls(repo, kind):
    config = ResourceBudgetConfig(period="daily", max_llm_calls=2, max_vendor_requests=2)
    notify = _CapturingSink()
    guard = BudgetGuard(config, repo, notify)

    guard.guard(kind)
    guard.guard(kind)
    with pytest.raises(BudgetExhausted):
        guard.guard(kind)
    # Further discretionary calls in the same period remain blocked.
    with pytest.raises(BudgetExhausted):
        guard.guard(kind)

    blocked = [a for a in repo.read_activity() if a["action"] == "budget_blocked"]
    assert len(blocked) == 2, "each blocked attempt is logged, not silently no-op'd"

    # First exhaustion notifies once; the second blocked attempt does not re-notify.
    assert len(notify.events) == 1
    assert notify.events[0]["kind"] == kind


def test_zero_limit_blocks_the_first_call(repo):
    config = ResourceBudgetConfig(period="daily", max_llm_calls=0, max_vendor_requests=2)
    guard = BudgetGuard(config, repo, _CapturingSink())
    with pytest.raises(BudgetExhausted):
        guard.guard("llm")


def test_llm_and_vendor_request_budgets_are_independent(repo):
    config = ResourceBudgetConfig(period="daily", max_llm_calls=1, max_vendor_requests=1)
    guard = BudgetGuard(config, repo, _CapturingSink())
    guard.guard("llm")
    with pytest.raises(BudgetExhausted):
        guard.guard("llm")
    # vendor_request budget is untouched by llm exhaustion.
    guard.guard("vendor_request")
    with pytest.raises(BudgetExhausted):
        guard.guard("vendor_request")


def test_counters_reset_only_at_a_period_boundary_never_manually(repo):
    config = ResourceBudgetConfig(period="daily", max_llm_calls=1, max_vendor_requests=1)
    guard = BudgetGuard(config, repo, _CapturingSink())
    today = datetime.now(UTC)

    guard.guard("llm")
    with pytest.raises(BudgetExhausted):
        guard.guard("llm")

    tomorrow_key = _period_key("daily", today + timedelta(days=1))
    usage = repo.get_budget_usage(tomorrow_key)
    assert usage["llm_calls_used"] == 0
    assert usage["exhausted_at"] is None, "a new period starts unexhausted with no manual reset"
