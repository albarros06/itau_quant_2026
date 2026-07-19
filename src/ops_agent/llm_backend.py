"""LLM backend selection for ops_agent's own structured tasks.

Reuses ``energy_research.common.llm``'s transport (``StructuredRequest`` ->
validated JSON payload, ``AnthropicStructuredBackend``/``GeminiStructuredBackend``)
for the ``anthropic``/``gemini`` backends — the same transport generation/critique
use (contracts/ops-agent-boundary.md). ``ops_agent`` never imports generation/
critique themselves to get it.

The ``deterministic_stub`` backend is ops_agent's own — 001's stub only knows the
``thesis_generation``/``critique`` tasks, not ops_agent's ``provisioning_draft``/
``onboarding_draft`` tasks — offline and reproducible for tests and sample runs
(research.md §11), never a network call.
"""

from __future__ import annotations

import json
from typing import Any

from energy_research.common.llm import (
    AnthropicStructuredBackend,
    GeminiStructuredBackend,
    StructuredBackend,
)
from ops_agent.config import LlmConfig


def _provisioning_draft_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    provider_id: str = ctx["provider_id"]
    entries: list[dict[str, Any]] = ctx.get("entries", [])
    market_categories = {"spot", "forward_curve", "hydrology", "interest_rate", "fx"}
    qualitative_categories = {"news", "hydrology_outlook", "macro_regime"}

    market_hints: dict[str, list[str]] = {}
    qualitative_found: list[str] = []
    instrument_entries: list[dict[str, str]] = []
    for entry in entries:
        category = entry.get("category")
        hints = entry.get("instrument_hints") or []
        if category in market_categories:
            market_hints[category] = hints
            for key in hints:
                instrument_entries.append(
                    {
                        "key": key,
                        "category": category,
                        "description": f"discovered via {provider_id}",
                    }
                )
        elif category in qualitative_categories:
            qualitative_found.append(category)

    payload: dict[str, Any] = {
        "provider_id": provider_id,
        "kind": "data_source",
        "rationale": (
            f"Discovery probe of vendor {provider_id!r} found "
            f"{len(market_hints)} market category(ies) and {len(qualitative_found)} "
            "qualitative category(ies); drafting a provisioning proposal to register "
            "the vendor and its offered instruments."
        ),
        "instrument_universe_entries": instrument_entries,
    }
    if market_hints:
        payload["market_data_entry"] = {
            "provider_id": provider_id,
            "categories": sorted(market_hints),
            "options": {},
        }
    if qualitative_found:
        payload["qualitative_entry"] = {
            "provider_id": provider_id,
            "categories": sorted(qualitative_found),
            "options": {},
        }
    return payload


def _onboarding_draft_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    """Deterministic stand-in for onboarding.draft's LLM call (T038).

    The stub can't actually read a vendor's API docs, so it expects
    ``interface_doc`` to itself be a JSON string: either a full
    ``DataSourceDescriptor`` payload (drafts a descriptor) or an
    ``{"unsupported_aspect": ..., "reason": ...}`` object (drafts a limitation).
    Anything else is reported as an explicit limitation, never a guessed
    descriptor (contracts/declarative-connector.md "Onboarding-drafting rules").
    """
    provider_id = ctx["provider_id"]
    try:
        parsed = json.loads(ctx["interface_doc"])
    except (json.JSONDecodeError, TypeError):
        return {
            "limitation": {
                "provider_id": provider_id,
                "reason": "interface description was not machine-readable by this offline stub",
                "unsupported_aspect": "transport",
            }
        }

    if isinstance(parsed, dict) and "unsupported_aspect" in parsed:
        return {
            "limitation": {
                "provider_id": provider_id,
                "reason": parsed.get("reason", "unsupported vendor interface"),
                "unsupported_aspect": parsed["unsupported_aspect"],
            }
        }

    if isinstance(parsed, dict) and "endpoints" in parsed:
        descriptor = dict(parsed)
        descriptor.setdefault("provider_id", provider_id)
        descriptor.setdefault("connector_kind", "declarative")
        return {"descriptor": descriptor}

    return {
        "limitation": {
            "provider_id": provider_id,
            "reason": "interface description did not resemble a supported REST descriptor",
            "unsupported_aspect": "field_mapping",
        }
    }


class DeterministicOpsBackend:
    """Offline, deterministic payload generator for ops_agent's structured tasks."""

    def complete(self, request) -> list[Any]:
        if request.task == "provisioning_draft":
            return [_provisioning_draft_payload(request.context)]
        if request.task == "onboarding_draft":
            return [_onboarding_draft_payload(request.context)]
        raise ValueError(f"unknown structured task {request.task!r}")


def build_llm_backend(config: LlmConfig) -> StructuredBackend:
    if config.backend == "deterministic_stub":
        return DeterministicOpsBackend()
    if config.backend == "anthropic":
        return AnthropicStructuredBackend(model=config.model, api_key_env=config.api_key_env)
    if config.backend == "gemini":
        return GeminiStructuredBackend(model=config.model, api_key_env=config.api_key_env)
    raise ValueError(f"unknown LLM backend {config.backend!r}")
