"""Thin LLM adapter for thesis generation, constrained to TradingThesisDraft.

Wraps the shared structured-LLM transport (common.llm) with the thesis JSON schema
from contracts/thesis-schema.md. Returns RAW payloads only — the service layer
independently re-validates every payload via ``schemas.validate_draft`` before
anything is persisted (two-stage validation, Constitution Principle III).
"""

from __future__ import annotations

from typing import Any

from energy_research.common.llm import StructuredBackend, StructuredRequest
from energy_research.generation.schemas import TradingThesisDraft

_SYSTEM = (
    "You are a quantitative research assistant for Brazilian energy markets and "
    "derivatives. You propose candidate trading theses as structured data only. "
    "You never produce code, never place orders, and never reference execution or "
    "capital allocation. Every thesis must include a plain-language rationale "
    "grounded in the provided market and qualitative context, and a specific, "
    "falsifiable hypothesis restricted to the provided instrument universe."
)


class ThesisLLMClient:
    def __init__(self, backend: StructuredBackend):
        self._backend = backend

    def propose(
        self,
        *,
        market_summary: str,
        qualitative_summary: str,
        universe_keys: list[str],
        n: int,
        context: dict,
    ) -> list[Any]:
        """Request up to ``n`` raw thesis payloads (unvalidated)."""
        prompt = (
            f"Instrument universe (only these keys are valid): {universe_keys}\n\n"
            f"Discovery-window market summary:\n{market_summary}\n\n"
            f"Qualitative context:\n{qualitative_summary}\n\n"
            f"Propose {n} distinct trading theses as JSON conforming to the "
            "TradingThesisDraft schema."
        )
        request = StructuredRequest(
            task="thesis_generation",
            system=_SYSTEM,
            prompt=prompt,
            json_schema=TradingThesisDraft.model_json_schema(),
            n=n,
            context=context,
        )
        return self._backend.complete(request)
