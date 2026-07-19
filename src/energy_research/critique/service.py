"""Critique service: LLM call constrained to ThesisCritique, persisted and
attached to the critiqued thesis (FR-020).

Uses the shared structured-LLM transport in ``common.llm`` (the independence
contract forbids importing generation's adapter); output is independently
re-validated against ThesisCritique before persistence, and consumed by the next
generation call for the lineage via orchestration — never by generation reaching
into this layer (critique-schema.md rule 2).
"""

from __future__ import annotations

from energy_research.common.llm import StructuredRequest, build_backend
from energy_research.common.logging import get_logger, kv
from energy_research.config.settings import PipelineConfig
from energy_research.critique.schemas import (
    CritiqueRejection,
    ThesisCritique,
    validate_critique,
)
from energy_research.datastore.repository import Repository

log = get_logger("critique.service")

_SYSTEM = (
    "You are a critical reviewer of quantitative trading theses for Brazilian "
    "energy markets. You produce structured critiques only: specific, concrete "
    "weaknesses grounded in the recorded screening and backtest evidence, plus a "
    "concrete suggested direction for the next refinement. You never produce code "
    "and never reference execution or capital."
)


class CritiqueService:
    def __init__(self, repo: Repository, config: PipelineConfig):
        self._repo = repo
        self._config = config
        self._backend = build_backend(
            config.generation.backend,
            config.generation.model,
            config.generation.api_key_env,
        )

    def critique_thesis(
        self, thesis_id: str, instrument_trend: float = 0.0
    ) -> ThesisCritique | None:
        """Critique a rejected/underperforming thesis; persist and return it.

        Returns None (with a loud log) when the critique itself fails validation —
        the loop then stops refining that lineage rather than consuming a
        malformed critique (no repair, Principle III).
        """
        thesis = self._repo.get_thesis(thesis_id)
        screening = self._repo.screening_result_for(thesis_id)
        backtests = self._repo.backtest_results_for(thesis_id, split_type="refinement")
        context = {
            "hypothesis": thesis["hypothesis"],
            "screening": None
            if screening is None
            else {
                "verdict": screening["verdict"],
                "p_value": screening["p_value"],
                "adjusted_threshold": screening["adjusted_threshold"],
            },
            "backtest": None
            if not backtests
            else {
                "net_return": backtests[-1]["net_return"],
                "gross_return": backtests[-1]["gross_return"],
            },
            "underperform_bar": self._config.backtesting.underperform_net_return_threshold,
            "instrument_trend": instrument_trend,
        }
        prompt = (
            f"Thesis under critique (status {thesis['status']}):\n"
            f"Rationale: {thesis['rationale']}\n"
            f"Hypothesis: {thesis['hypothesis']}\n"
            f"Recorded screening result: {context['screening']}\n"
            f"Recorded refinement backtest: {context['backtest']}\n\n"
            "Produce a ThesisCritique JSON identifying the specific weaknesses and a "
            "concrete direction for the next variant."
        )
        payloads = self._backend.complete(
            StructuredRequest(
                task="critique",
                system=_SYSTEM,
                prompt=prompt,
                json_schema=ThesisCritique.model_json_schema(),
                n=1,
                context=context,
            )
        )
        payload = payloads[0] if payloads else {}
        try:
            critique = validate_critique(payload)
        except CritiqueRejection as exc:
            log.warning(
                "critique rejected, lineage refinement stops %s",
                kv(thesis_id=thesis_id, reason=exc.reason),
            )
            return None
        self._repo.insert_critique(
            thesis_id=thesis_id,
            weaknesses=critique.weaknesses,
            suggested_direction=critique.suggested_direction,
            feeds_iteration_index=thesis["iteration_index"] + 1,
        )
        return critique
