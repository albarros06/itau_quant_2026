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
    "falsifiable hypothesis restricted to the provided instrument universe.\n\n"
    "The instrument universe is split into TRADEABLE instruments — they have a "
    "price, a position, and a short side — and SIGNAL-ONLY statistics (e.g. "
    "reservoir levels, inflow as a percent of long-term mean, policy-rate proxies) "
    "which have no price, no position, and no short side. Only tradeable "
    "instruments may appear in hypothesis.instruments as traded legs. A signal-only "
    "statistic may be referenced ONLY inside a condition clause, to gate WHEN a "
    "thesis is active — never as a traded leg. A hypothesis whose instruments list "
    "contains a signal-only statistic will be rejected.\n\n"
    "A hypothesis may carry an optional structured 'condition' (or null for "
    "always-in-market) that gates when the position is held. A condition is 1..3 "
    "clauses combined with AND. Each clause compares one universe instrument's "
    "subject (subject_transform: 'level' | 'sma' | 'change', with subject_lookback "
    "set only for sma/change) via a comparator ('<','<=','>','>=') against a "
    "reference (reference_kind: 'constant' uses reference_value; 'sma' uses "
    "reference_lookback; 'rolling_quantile' uses reference_lookback and "
    "reference_quantile in [0,1]). All lookbacks are in trading days and must not "
    "exceed 90. When reference_kind is 'constant', reference_value MUST be on the "
    "subject instrument's NATIVE level scale as shown per instrument in the market "
    "summary (each line gives that series' level min/p10/median/p90/max) — do NOT "
    "assume a normalized 0..1 or 0..100 scale; a threshold outside the observed "
    "range means the condition never triggers and the thesis is discarded untested. "
    "Express conditions ONLY in this vocabulary — never as free text; "
    "put prose reasoning in the rationale and testable_claim instead."
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
        tradeable_keys: list[str],
        n: int,
        context: dict,
    ) -> list[Any]:
        """Request up to ``n`` raw thesis payloads (unvalidated).

        ``tradeable_keys`` is the subset of ``universe_keys`` that may appear as a
        traded leg in ``hypothesis.instruments``; the remaining (signal-only) keys
        may only gate a thesis via ``condition`` clauses.
        """
        signal_only = [k for k in universe_keys if k not in tradeable_keys]
        prompt = (
            f"Instrument universe (only these keys are valid): {universe_keys}\n"
            f"  - Tradeable (valid as traded legs in hypothesis.instruments): "
            f"{tradeable_keys}\n"
            f"  - Signal-only statistics (valid ONLY inside condition clauses as "
            f"gates, never as a traded leg): {signal_only}\n\n"
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
