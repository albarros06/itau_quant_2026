"""Config-only vendor onboarding: interface description -> a schema-validated
``DataSourceDescriptor`` or an explicit ``OnboardingLimitation`` (research.md §4,
FR-016-018, contracts/declarative-connector.md "Onboarding-drafting rules").

The LLM's only output is one of the two — never a partial/guessed descriptor
(Constitution Principle III).
"""

from __future__ import annotations

from energy_research.common.llm import StructuredBackend, StructuredRequest
from ops_agent.budget import BudgetGuard
from ops_agent.proposals.models import OnboardingDraft
from ops_agent.store.repository import Repository

_SYSTEM_PROMPT = (
    "You draft config-only vendor onboarding descriptors for an energy-markets "
    "research pipeline's declarative connector. You never write code. If the "
    "vendor's interface needs anything the descriptor cannot express — an auth "
    "scheme beyond a single bearer/API-key header, pagination beyond simple "
    "offset/cursor, a response shape JMESPath cannot flatten, or a non-HTTP "
    "transport — you MUST return a limitation, never a guessed descriptor. "
    "Output must satisfy the given JSON schema exactly, with exactly one of "
    "'descriptor'/'limitation' populated."
)


def draft_onboarding(
    provider_id: str,
    interface_doc: str,
    backend: StructuredBackend,
    guard: BudgetGuard,
    repo: Repository,
) -> OnboardingDraft | None:
    """Returns ``None`` (having already logged a failed ``limitation_reported``
    entry) if the LLM's output fails schema validation or is empty."""
    guard.guard("llm")
    request = StructuredRequest(
        task="onboarding_draft",
        system=_SYSTEM_PROMPT,
        prompt=(
            f"Vendor {provider_id!r} interface notes:\n{interface_doc}\n\n"
            "Draft either a DataSourceDescriptor or an OnboardingLimitation."
        ),
        json_schema=OnboardingDraft.model_json_schema(),
        context={"provider_id": provider_id, "interface_doc": interface_doc},
    )
    payloads = backend.complete(request)
    payload = payloads[0] if payloads else {}

    try:
        draft = OnboardingDraft.model_validate(payload)
    except Exception as exc:  # invalid LLM output is rejected, never repaired (Principle III)
        repo.record_activity(
            action="limitation_reported",
            target=provider_id,
            reason=f"LLM produced invalid onboarding output, rejected: {exc}",
            outcome="failed",
        )
        return None

    if draft.descriptor is None and draft.limitation is None:
        repo.record_activity(
            action="limitation_reported",
            target=provider_id,
            reason="LLM returned neither a descriptor nor a limitation",
            outcome="failed",
        )
        return None

    return draft
