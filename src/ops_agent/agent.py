"""``OpsAgent``: ``bootstrap()`` and ``tick()`` (research.md §1, spec User Stories 1-2).

A single bounded pass per invocation — no resident daemon (research.md §1). All
state changes flow through ``store.repository`` (activity log, schedule state,
budgets) and ``proposals.git_store`` (config changes); the pipeline itself is only
ever touched through ``energy_research.orchestration.ingest.ingest_all``/
``orchestration.cycle.run_cycle`` — opaque calls, no thesis/verdict override
(contracts/ops-agent-boundary.md rule 4).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import yaml

from energy_research.common.llm import StructuredBackend
from energy_research.config.settings import PipelineConfig, load_config
from energy_research.datastore.repository import StaleDataError
from energy_research.ingestion import registry
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all
from ops_agent import remediation
from ops_agent.budget import BudgetGuard
from ops_agent.config import OpsAgentConfig
from ops_agent.discovery.interpret import interpret_catalog
from ops_agent.discovery.vendor_probe import probe_all
from ops_agent.llm_backend import build_llm_backend
from ops_agent.notify import build_sink
from ops_agent.onboarding.draft import draft_onboarding
from ops_agent.proposals.git_store import GitStore
from ops_agent.proposals.models import (
    DataSourceDescriptor,
    MarketProviderDraftEntry,
    OnboardingLimitation,
    ProvisioningDraft,
    ProvisioningProposal,
)
from ops_agent.scheduling import is_due
from ops_agent.store.repository import Repository

_DEFAULT_DB_PATH = Path("data/ops_agent.sqlite")


def _relpath(path: Path, repo_dir: Path) -> str:
    return os.path.relpath(path.resolve(), repo_dir.resolve())


def _upsert_provider_entry(
    entries: list[dict], draft_entry: MarketProviderDraftEntry
) -> list[dict]:
    entries = [dict(e) for e in entries]
    for e in entries:
        if e.get("provider_id") == draft_entry.provider_id:
            e["categories"] = sorted(set(e.get("categories", [])) | set(draft_entry.categories))
            return entries
    entries.append(
        {
            "provider_id": draft_entry.provider_id,
            "categories": list(draft_entry.categories),
            "options": dict(draft_entry.options),
        }
    )
    return entries


class OpsAgent:
    def __init__(
        self,
        config: OpsAgentConfig,
        repo_dir: str | Path = ".",
        db_path: str | Path | None = None,
    ):
        self.config = config
        self.repo_dir = Path(repo_dir)
        self.pipeline_config: PipelineConfig = load_config(
            self.repo_dir / config.pipeline_config_path
        )
        self.repo = Repository(db_path or (self.repo_dir / _DEFAULT_DB_PATH))
        self.notify_sink = build_sink(config.notifications.sink, config.notifications.path)
        self.budget_guard = BudgetGuard(config.resource_budgets, self.repo, self.notify_sink)
        self.git_store = GitStore(self.repo_dir, config.git, self.repo)
        self._llm_backend: StructuredBackend | None = None

    @property
    def llm_backend(self) -> StructuredBackend:
        """Built lazily: only ``bootstrap()``/``onboard()`` need it, and commands
        that don't (``tick``/``approve``/``reject``/``status``/``log``) must not
        require LLM credentials just to run."""
        if self._llm_backend is None:
            self._llm_backend = build_llm_backend(self.config.llm)
        return self._llm_backend

    def close(self) -> None:
        self.repo.close()

    def __enter__(self) -> OpsAgent:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------- bootstrap

    def bootstrap(self) -> list[ProvisioningProposal]:
        """Discovery + interpretation for every configured vendor; opens one
        proposal branch per non-empty draft (spec User Story 1)."""
        catalogs = probe_all(self.pipeline_config, self.budget_guard, self.repo)
        proposals: list[ProvisioningProposal] = []
        for catalog in catalogs:
            draft = interpret_catalog(catalog, self.llm_backend, self.budget_guard, self.repo)
            if draft is None:
                continue
            file_changes = self._render_file_changes(draft)
            if not file_changes:
                continue
            proposal = self.git_store.open_proposal(
                kind=draft.kind,
                slug=draft.provider_id,
                rationale=draft.rationale,
                file_changes=file_changes,
                discovery_evidence_ref=f"discover:{draft.provider_id}",
            )
            proposals.append(proposal)
        return proposals

    def _render_file_changes(self, draft: ProvisioningDraft) -> dict[str, str]:
        default_path = (self.repo_dir / self.config.pipeline_config_path).resolve()
        default_raw = yaml.safe_load(default_path.read_text())
        providers_rel = default_raw.get("providers_file")
        providers_path = (
            (default_path.parent / providers_rel).resolve()
            if providers_rel and "providers" not in default_raw
            else None
        )
        providers_raw = (
            yaml.safe_load(providers_path.read_text()) if providers_path is not None else None
        )

        changed: dict[str, str] = {}

        if draft.instrument_universe_entries:
            existing_keys = {e["key"] for e in default_raw.get("instrument_universe", [])}
            new_entries = [
                {"key": e.key, "category": e.category, "description": e.description}
                for e in draft.instrument_universe_entries
                if e.key not in existing_keys
            ]
            if new_entries:
                updated = dict(default_raw)
                updated["instrument_universe"] = [
                    *default_raw.get("instrument_universe", []),
                    *new_entries,
                ]
                changed[_relpath(default_path, self.repo_dir)] = yaml.safe_dump(
                    updated, sort_keys=False
                )

        if providers_raw is not None and (draft.market_data_entry or draft.qualitative_entry):
            updated_providers = dict(providers_raw)
            if draft.market_data_entry:
                updated_providers["market_data"] = _upsert_provider_entry(
                    providers_raw.get("market_data", []), draft.market_data_entry
                )
            if draft.qualitative_entry:
                updated_providers["qualitative_context"] = _upsert_provider_entry(
                    providers_raw.get("qualitative_context", []), draft.qualitative_entry
                )
            changed[_relpath(providers_path, self.repo_dir)] = yaml.safe_dump(
                updated_providers, sort_keys=False
            )

        return changed

    # ------------------------------------------------------------------ tick

    def tick(self) -> dict:
        """One bounded, idempotent pass (research.md §1): refresh market data and
        poll qualitative feeds on their own cadences (FR-006/007), then — if a
        cycle is due — trigger one, remediating stale/missing data before
        escalating rather than failing silently or running on unfit data
        (FR-008). A no-op (logged ``checked_and_empty``) when nothing is due."""
        self._refresh_market_data_if_due()
        self._poll_qualitative_feeds_if_due()

        cycle_state = self.repo.get_schedule_state("cycle")
        if not is_due("cycle", self.config.operating_schedule, cycle_state):
            self.repo.record_activity(
                action="checked_and_empty",
                target="cycle",
                reason="cycle not yet due",
                outcome="skipped",
            )
            return {"cycle_ran": False}

        try:
            result = run_cycle(self.pipeline_config)
        except StaleDataError as exc:
            result = remediation.remediate_and_run_cycle(
                self.pipeline_config, self.config.remediation, self.repo
            )
            if result is None:
                self._escalate(str(exc))
                return {"cycle_ran": False, "escalated": True}

        self.repo.record_activity(
            action="cycle_trigger",
            target=result.cycle_id,
            reason=f"{len(result.promoted_thesis_ids)} thesis(es) promoted",
            outcome="ok",
        )

        self.notify_sink.send(
            {
                "event": "shortlist",
                "cycle_id": result.cycle_id,
                "promoted_thesis_ids": result.promoted_thesis_ids,
                "report_path": str(result.report_path),
            }
        )
        self.repo.record_activity(
            action="notify_shortlist",
            target=result.cycle_id,
            reason=f"report at {result.report_path}",
            outcome="ok",
        )

        self.repo.update_schedule_state("cycle", last_outcome="ok")
        return {
            "cycle_ran": True,
            "cycle_id": result.cycle_id,
            "promoted_thesis_ids": result.promoted_thesis_ids,
            "report_path": result.report_path,
        }

    def _refresh_market_data_if_due(self) -> None:
        state = self.repo.get_schedule_state("market_refresh")
        if not is_due("market_refresh", self.config.operating_schedule, state):
            return
        try:
            summary = ingest_all(self.pipeline_config)
            self.repo.record_activity(
                action="ingest",
                target="market_data",
                reason=f"refreshed {summary['series']} series",
                outcome="ok",
            )
        except Exception as exc:
            self.repo.record_activity(
                action="ingest", target="market_data", reason=str(exc), outcome="failed"
            )
        self.repo.update_schedule_state("market_refresh", last_outcome="ok")

    def _poll_qualitative_feeds_if_due(self) -> None:
        """Polls each configured qualitative feed for material newer than its
        recorded ``FeedWatermark`` (read-only connector calls only — no direct
        Repository write). Only when something new is found does it trigger the
        opaque, full ``ingest_all`` to actually persist it; otherwise logs
        ``checked_and_empty`` (Edge Case: no new qualitative material)."""
        state = self.repo.get_schedule_state("qualitative_poll")
        if not is_due("qualitative_poll", self.config.operating_schedule, state):
            return

        found_new = False
        connectors = registry.context_connectors(self.pipeline_config)
        for entry in self.pipeline_config.providers.qualitative_context:
            connector = connectors.get(entry.provider_id)
            if connector is None:
                continue
            for category in entry.categories:
                marker = self.repo.get_watermark(entry.provider_id, category)
                since = datetime.fromisoformat(marker) if marker else None
                try:
                    docs = connector.fetch_context(category, since=since)
                except Exception as exc:
                    self.repo.record_activity(
                        action="credential_error",
                        target=f"{entry.provider_id}:{category}",
                        reason=str(exc),
                        outcome="failed",
                    )
                    continue
                if docs:
                    found_new = True
                    latest_ts = max(d.ts for d in docs)
                    self.repo.update_watermark(entry.provider_id, category, latest_ts.isoformat())

        if found_new:
            summary = ingest_all(self.pipeline_config)
            self.repo.record_activity(
                action="ingest",
                target="qualitative_feeds",
                reason=(
                    f"picked up new qualitative material "
                    f"({summary['context_docs']} doc(s) persisted)"
                ),
                outcome="ok",
            )
        else:
            self.repo.record_activity(
                action="checked_and_empty",
                target="qualitative_feeds",
                reason="no new qualitative material found",
                outcome="skipped",
            )
        self.repo.update_schedule_state("qualitative_poll", last_outcome="ok")

    def _escalate(self, reason: str) -> None:
        self.repo.record_activity(
            action="escalate", target="cycle_freshness", reason=reason, outcome="failed"
        )
        self.notify_sink.send({"event": "escalation", "reason": reason})

    # ------------------------------------------------------------- onboarding

    def onboard(
        self, provider_id: str, interface_doc: str
    ) -> ProvisioningProposal | OnboardingLimitation:
        """Config-only vendor onboarding (spec User Story 4, FR-016-018): a
        descriptor becomes a ``kind="onboarding"`` proposal touching only
        ``providers.yaml``; a limitation is reported directly, never a
        guessed/partial integration."""
        draft = draft_onboarding(
            provider_id, interface_doc, self.llm_backend, self.budget_guard, self.repo
        )
        if draft is None or draft.limitation is not None:
            limitation = draft.limitation if draft is not None else OnboardingLimitation(
                provider_id=provider_id,
                reason="onboarding drafting failed (invalid LLM output)",
                unsupported_aspect="field_mapping",
            )
            self.repo.record_activity(
                action="limitation_reported",
                target=provider_id,
                reason=limitation.reason,
                outcome="ok",
            )
            return limitation

        descriptor = draft.descriptor
        file_changes = self._render_onboarding_file_change(descriptor)
        proposal = self.git_store.open_proposal(
            kind="onboarding",
            slug=provider_id,
            rationale=(
                f"Config-only onboarding of vendor {provider_id!r} via the declarative connector"
            ),
            file_changes=file_changes,
            discovery_evidence_ref=f"onboard:{provider_id}",
        )
        self.repo.record_data_source_descriptor(provider_id, proposal.id, descriptor.connector_kind)
        self.repo.record_activity(
            action="propose",
            target=provider_id,
            reason="drafted a config-only onboarding proposal",
            outcome="ok",
            related_proposal_id=proposal.id,
        )
        return proposal

    def _render_onboarding_file_change(self, descriptor: DataSourceDescriptor) -> dict[str, str]:
        default_path = (self.repo_dir / self.config.pipeline_config_path).resolve()
        default_raw = yaml.safe_load(default_path.read_text())
        providers_rel = default_raw["providers_file"]
        providers_path = (default_path.parent / providers_rel).resolve()
        providers_raw = yaml.safe_load(providers_path.read_text())

        options = descriptor.model_dump(mode="json", exclude={"connector_kind"})
        entry = {
            "provider_id": descriptor.provider_id,
            "categories": [ep.category for ep in descriptor.endpoints],
            "options": options,
            "connector_kind": "declarative",
        }
        list_key = (
            "market_data"
            if descriptor.credential.purpose == "market_data"
            else "qualitative_context"
        )
        updated = dict(providers_raw)
        entries = [
            e for e in updated.get(list_key, []) if e.get("provider_id") != descriptor.provider_id
        ]
        entries.append(entry)
        updated[list_key] = entries
        return {_relpath(providers_path, self.repo_dir): yaml.safe_dump(updated, sort_keys=False)}
