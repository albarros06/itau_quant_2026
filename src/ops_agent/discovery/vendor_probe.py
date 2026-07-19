"""Vendor discovery probing (research.md §5, contracts/ops-agent-boundary.md).

Probes each configured connector's ``discover()`` (duck-typed via ``hasattr`` —
falling back to an empty catalog when a connector doesn't implement it) and
``health_check()``. Every probe call is metered through
``budget.guard(kind="vendor_request")`` at the actual call site
(contracts/budget-contract.md rule 1). One vendor's failure — a bad credential, an
unreachable host — never blocks discovery for the others (spec Acceptance
Scenario 1.3): each vendor's outcome is recorded independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion import registry
from ops_agent.budget import BudgetExhausted, BudgetGuard
from ops_agent.store.repository import Repository


@dataclass(frozen=True)
class CatalogEntry:
    category: str
    instrument_hints: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass(frozen=True)
class VendorCatalog:
    provider_id: str
    entries: list[CatalogEntry] = field(default_factory=list)
    healthy: bool = True
    detail: str = ""


def _parse_entries(raw: object) -> list[CatalogEntry]:
    if not isinstance(raw, dict):
        return []
    entries = raw.get("entries", [])
    if not isinstance(entries, list):
        return []
    parsed = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        parsed.append(
            CatalogEntry(
                category=str(e.get("category", "")),
                instrument_hints=[str(h) for h in e.get("instrument_hints", [])],
                notes=str(e.get("notes", "")),
            )
        )
    return parsed


def probe_vendor(
    provider_id: str, connector: object, guard: BudgetGuard, repo: Repository
) -> VendorCatalog:
    """Probe one connector. Never raises for a vendor-side failure — records a
    ``credential_error``/``discover`` activity entry and returns a catalog with
    ``healthy=False`` (or empty entries) instead. Re-raises ``BudgetExhausted``:
    that halts discretionary probing for the whole period, not just this vendor."""
    guard.guard("vendor_request")
    try:
        health = connector.health_check()
    except BudgetExhausted:
        raise
    except Exception as exc:  # vendor-side failure must not block other vendors
        repo.record_activity(
            action="credential_error", target=provider_id, reason=str(exc), outcome="failed"
        )
        return VendorCatalog(provider_id=provider_id, entries=[], healthy=False, detail=str(exc))

    if not health.ok:
        repo.record_activity(
            action="credential_error", target=provider_id, reason=health.detail, outcome="failed"
        )
        return VendorCatalog(
            provider_id=provider_id, entries=[], healthy=False, detail=health.detail
        )

    if not hasattr(connector, "discover"):
        repo.record_activity(
            action="discover",
            target=provider_id,
            reason="connector does not implement discover(); empty catalog",
            outcome="skipped",
        )
        return VendorCatalog(
            provider_id=provider_id, entries=[], healthy=True, detail="no discover() support"
        )

    guard.guard("vendor_request")
    try:
        raw = connector.discover()
    except BudgetExhausted:
        raise
    except Exception as exc:
        repo.record_activity(
            action="discover", target=provider_id, reason=str(exc), outcome="failed"
        )
        return VendorCatalog(provider_id=provider_id, entries=[], healthy=True, detail=str(exc))

    entries = _parse_entries(raw)
    repo.record_activity(
        action="discover",
        target=provider_id,
        reason=f"discovered {len(entries)} catalog entrie(s)",
        outcome="ok",
    )
    return VendorCatalog(provider_id=provider_id, entries=entries, healthy=True, detail="")


def probe_all(
    config: PipelineConfig, guard: BudgetGuard, repo: Repository
) -> list[VendorCatalog]:
    """Probe every configured market-data and qualitative-context connector.

    A vendor configured for both roles is probed once. Budget exhaustion stops
    further probing for the remainder of the tick (the guard already logged
    ``budget_blocked``) but does not raise past this function — callers see a
    partial catalog list, not a hard failure.
    """
    connectors: dict[str, object] = {}
    connectors.update(registry.market_connectors(config))
    connectors.update(registry.context_connectors(config))

    catalogs: list[VendorCatalog] = []
    for provider_id, connector in connectors.items():
        try:
            catalogs.append(probe_vendor(provider_id, connector, guard, repo))
        except BudgetExhausted:
            break
    return catalogs
