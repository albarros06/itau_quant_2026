"""Bounded remediation before escalation (research.md §10, FR-008).

Retries the exact same 001 operations that would normally run —
``orchestration.ingest.ingest_all`` then ``orchestration.cycle.run_cycle`` — up to
``RemediationConfig.max_retries`` times with ``backoff_seconds`` between attempts
(both configured, never hardcoded — Constitution Principle VI). Every attempt is
logged. This reuses 001's own fetch/clean/quality/freshness-gate path verbatim
instead of duplicating any part of it (research.md §2, §10): 001's own
``Repository.assert_fresh`` (invoked inside ``run_cycle``) is the final word on
whether freshness was actually restored, not anything this module decides itself.
"""

from __future__ import annotations

import time

from energy_research.config.settings import PipelineConfig
from energy_research.datastore.repository import StaleDataError
from energy_research.orchestration.cycle import CycleResult, run_cycle
from energy_research.orchestration.ingest import ingest_all
from ops_agent.config import RemediationConfig
from ops_agent.store.repository import Repository


def remediate_and_run_cycle(
    pipeline_config: PipelineConfig, remediation: RemediationConfig, repo: Repository
) -> CycleResult | None:
    """Returns the ``CycleResult`` the moment ``run_cycle`` succeeds; ``None`` once
    ``max_retries`` attempts have all still hit ``StaleDataError`` (or ingestion
    itself keeps failing) — the caller escalates in that case (FR-008)."""
    last_error: str = ""
    for attempt in range(1, remediation.max_retries + 1):
        try:
            ingest_all(pipeline_config)
        except Exception as exc:
            last_error = str(exc)
            repo.record_activity(
                action="remediate",
                target="cycle_freshness",
                reason=f"ingest attempt {attempt}/{remediation.max_retries} failed: {exc}",
                outcome="failed",
            )
            if attempt < remediation.max_retries:
                time.sleep(remediation.backoff_seconds)
            continue

        try:
            result = run_cycle(pipeline_config)
        except StaleDataError as exc:
            last_error = str(exc)
            repo.record_activity(
                action="remediate",
                target="cycle_freshness",
                reason=f"attempt {attempt}/{remediation.max_retries}: still stale after "
                f"re-ingest: {exc}",
                outcome="failed",
            )
            if attempt < remediation.max_retries:
                time.sleep(remediation.backoff_seconds)
            continue

        repo.record_activity(
            action="remediate",
            target="cycle_freshness",
            reason=f"freshness restored on attempt {attempt}/{remediation.max_retries}",
            outcome="ok",
        )
        return result

    repo.record_activity(
        action="remediate",
        target="cycle_freshness",
        reason=f"exhausted {remediation.max_retries} attempt(s), still unresolved: {last_error}",
        outcome="failed",
    )
    return None
