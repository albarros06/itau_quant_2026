"""Proposal models (data-model.md ``ProvisioningProposal``, ``ApprovalDecision``).

``ProvisioningProposal`` is the general-purpose change-control unit (FR-011).
Approval/rejection is a status transition on this model (``decided_by``/
``decided_at``/``applied_commit_sha``/``status``) — not a separate
``ApprovalDecision`` entity (data-model.md).

The models below it (``MarketProviderDraftEntry`` etc.) are the schema-validated
*content* an LLM drafts (``discovery.interpret``) before ``proposals.git_store``
turns it into an actual YAML diff on a proposal branch — the draft is never
persisted itself; only the resulting ``ProvisioningProposal`` index row and the git
commit are durable (research.md §7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from ops_agent.config import StrictModel
from ops_agent.credentials import CredentialReference

ProposalKind = Literal["instrument_universe", "data_source", "onboarding", "feed_schedule"]
ProposalStatus = Literal["proposed", "approved", "edited_and_approved", "rejected"]


class ProvisioningProposal(StrictModel):
    """Store row (data-model.md ``proposals`` table). The authoritative diff is
    always the live ``git diff <base_commit_sha> <branch_name>`` — never
    duplicated here (research.md §7)."""

    id: str
    kind: ProposalKind
    branch_name: str
    base_commit_sha: str
    target_files: list[str]
    rationale: str
    discovery_evidence_ref: str | None = None
    status: ProposalStatus = "proposed"
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    applied_commit_sha: str | None = None


class MarketProviderDraftEntry(StrictModel):
    """Mirrors ``energy_research.config.settings.MarketProviderEntry``."""

    provider_id: str
    categories: list[str] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class ContextProviderDraftEntry(StrictModel):
    """Mirrors ``energy_research.config.settings.ContextProviderEntry``."""

    provider_id: str
    categories: list[str] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)


class InstrumentDraftEntry(StrictModel):
    """Mirrors ``energy_research.config.settings.InstrumentConfig``."""

    key: str
    category: str
    description: str = ""


class ProvisioningDraft(StrictModel):
    """The LLM's schema-validated discovery-interpretation output (research.md §5).

    Invalid LLM output is rejected outright by ``discovery.interpret``, never
    repaired or partially applied (Constitution Principle III).
    """

    provider_id: str
    kind: ProposalKind = "data_source"
    rationale: str = Field(min_length=1)
    market_data_entry: MarketProviderDraftEntry | None = None
    qualitative_entry: ContextProviderDraftEntry | None = None
    instrument_universe_entries: list[InstrumentDraftEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Config-only vendor onboarding (data-model.md DataSourceDescriptor, FR-016-018)
# --------------------------------------------------------------------------


class EndpointSpec(StrictModel):
    category: str
    path_template: str
    method: Literal["GET", "POST"] = "GET"
    # canonical field name -> JMESPath expression evaluated against one response
    # element (contracts/declarative-connector.md).
    field_mapping: dict[str, str] = Field(min_length=1)
    results_path: str | None = Field(
        default=None,
        description=(
            "JMESPath into the raw response locating the elements array, for "
            "envelopes that are neither a bare array nor {'data': [...]} (e.g. "
            "'records' or 'result.records')."
        ),
    )
    ts_format: str | None = Field(
        default=None,
        description=(
            "strptime pattern for non-ISO timestamp strings (e.g. '%d/%m/%Y'). "
            "Omit for ISO-8601 timestamps (parsed via datetime.fromisoformat)."
        ),
    )


class PaginationSpec(StrictModel):
    mode: Literal["none", "offset", "cursor"] = "none"
    limit_param: str | None = None
    offset_param: str | None = None
    cursor_param: str | None = None
    next_cursor_path: str | None = None


class DataSourceDescriptor(StrictModel):
    """The FR-016 config-only vendor-onboarding artifact. Lives as YAML inside a
    ``providers.yaml`` proposal — the store keeps only an index (data-model.md).
    ``energy_research.ingestion.providers.declarative`` parses the identical
    shape independently (never imports this model — ops-agent-boundary.md)."""

    provider_id: str
    connector_kind: Literal["declarative"] = "declarative"
    credential: CredentialReference
    base_url: str
    endpoints: list[EndpointSpec] = Field(min_length=1)
    pagination: PaginationSpec = PaginationSpec()


class OnboardingLimitation(StrictModel):
    """Returned directly to the researcher, never persisted as a proposal — a
    ``limitation_reported`` activity-log entry is the durable record (FR-018)."""

    provider_id: str
    reason: str = Field(min_length=1)
    unsupported_aspect: Literal["auth", "pagination", "field_mapping", "transport"]


class OnboardingDraft(StrictModel):
    """The LLM's schema-validated onboarding output — either a descriptor or an
    explicit limitation, never a partial/guessed descriptor (contracts/
    declarative-connector.md "Onboarding-drafting rules")."""

    descriptor: DataSourceDescriptor | None = None
    limitation: OnboardingLimitation | None = None
