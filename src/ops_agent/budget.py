"""Discretionary resource-budget enforcement (contracts/budget-contract.md, FR-022).

Bounds only the agent's own discretionary activity — LLM calls made by
``discovery.interpret``/``onboarding.draft`` and vendor HTTP requests made by
``discovery.vendor_probe`` — never 001's own per-cycle LLM usage or routine
ingestion (research.md §9, out of scope for this guard).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ops_agent.config import ResourceBudgetConfig
from ops_agent.notify import NotificationSink
from ops_agent.store.repository import Repository


class BudgetExhausted(RuntimeError):
    """Raised by :meth:`BudgetGuard.guard` once the period's limit is reached."""


def _period_key(period: str, now: datetime) -> str:
    if period == "hourly":
        return now.strftime("%Y-%m-%dT%H:00:00")
    return now.strftime("%Y-%m-%d")


class BudgetGuard:
    """The only sanctioned entry point for incrementing discretionary usage
    (contracts/budget-contract.md rule 1)."""

    def __init__(
        self, config: ResourceBudgetConfig, repo: Repository, notify_sink: NotificationSink | None
    ):
        self._config = config
        self._repo = repo
        self._notify = notify_sink

    def guard(self, kind: Literal["llm", "vendor_request"]) -> None:
        """Raises :class:`BudgetExhausted` if the period's limit is already
        reached; otherwise increments usage and returns."""
        period_key = _period_key(self._config.period, datetime.now(UTC))
        usage = self._repo.get_budget_usage(period_key)
        if kind == "llm":
            limit, used = self._config.max_llm_calls, usage["llm_calls_used"]
        else:
            limit, used = self._config.max_vendor_requests, usage["vendor_requests_used"]

        if used >= limit:
            first_exhaustion = self._repo.mark_budget_exhausted(period_key)
            reason = f"{kind} budget exhausted for period {period_key} (limit={limit})"
            self._repo.record_activity(
                action="budget_blocked", target=kind, reason=reason, outcome="skipped"
            )
            # First exhaustion in a period fires one clear notification; further
            # blocked attempts are logged but do not re-notify (budget-contract.md
            # rule 3).
            if first_exhaustion and self._notify is not None:
                self._notify.send(
                    {
                        "event": "budget_exhausted",
                        "kind": kind,
                        "period_key": period_key,
                        "limit": limit,
                    }
                )
            raise BudgetExhausted(reason)

        self._repo.increment_budget_usage(period_key, kind)
