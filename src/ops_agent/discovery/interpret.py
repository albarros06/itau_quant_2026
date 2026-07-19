"""Discovery interpretation: a ``VendorCatalog`` -> a draft ``ProvisioningProposal``
(research.md §5, contracts/ops-agent-boundary.md).

The LLM's only output is a schema-validated ``ProvisioningDraft`` — invalid output
is rejected outright, never repaired or partially applied (Constitution Principle
III). The LLM never calls a vendor directly and never sees a resolved credential
value, only what the catalog already contains (provider id, categories, instrument
hints).
"""

from __future__ import annotations

from energy_research.common.llm import StructuredBackend, StructuredRequest
from ops_agent.budget import BudgetGuard
from ops_agent.discovery.vendor_probe import VendorCatalog
from ops_agent.proposals.models import ProvisioningDraft
from ops_agent.store.repository import Repository

_SYSTEM_PROMPT = (
    "You draft configuration-only provisioning proposals for an energy-markets "
    "research pipeline from a vendor discovery catalog. You never write code and "
    "you never see a resolved credential value — only provider ids, categories, "
    "and instrument hints. Output must satisfy the given JSON schema exactly."
)


def interpret_catalog(
    catalog: VendorCatalog,
    backend: StructuredBackend,
    guard: BudgetGuard,
    repo: Repository,
) -> ProvisioningDraft | None:
    """Returns ``None`` (and logs a failed ``propose`` activity entry) if the
    catalog is empty/unhealthy or the LLM's output fails schema validation."""
    if not catalog.healthy or not catalog.entries:
        repo.record_activity(
            action="propose",
            target=catalog.provider_id,
            reason=f"no usable discovery catalog for {catalog.provider_id} "
            f"(healthy={catalog.healthy}, entries={len(catalog.entries)}); nothing to draft",
            outcome="skipped",
        )
        return None

    guard.guard("llm")
    context = {
        "provider_id": catalog.provider_id,
        "entries": [
            {"category": e.category, "instrument_hints": e.instrument_hints, "notes": e.notes}
            for e in catalog.entries
        ],
    }
    request = StructuredRequest(
        task="provisioning_draft",
        system=_SYSTEM_PROMPT,
        prompt=(
            f"Vendor {catalog.provider_id!r} discovery catalog: {context['entries']!r}. "
            "Draft a ProvisioningProposal covering the data source registration and any "
            "instrument universe entries this vendor's catalog supports."
        ),
        json_schema=ProvisioningDraft.model_json_schema(),
        context=context,
    )
    payloads = backend.complete(request)
    payload = payloads[0] if payloads else {}

    try:
        draft = ProvisioningDraft.model_validate(payload)
    except Exception as exc:  # invalid LLM output is rejected, never repaired (Principle III)
        repo.record_activity(
            action="propose",
            target=catalog.provider_id,
            reason=f"LLM produced an invalid provisioning draft, rejected: {exc}",
            outcome="failed",
        )
        return None

    repo.record_activity(
        action="propose",
        target=catalog.provider_id,
        reason="drafted a provisioning proposal from the discovery catalog",
        outcome="ok",
    )
    return draft
