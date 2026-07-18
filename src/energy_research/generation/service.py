"""Generation service: context assembly → LLM call → validated TradingThesis rows.

Reads market/qualitative context from the datastore only (discovery split — idea
discovery never sees refinement or final-evaluation data), calls the thesis LLM
adapter, independently re-validates every payload, and persists results:

- valid drafts    → TradingThesis(status="proposed") in a new (or given) lineage
- invalid drafts  → TradingThesis(status="invalid_schema") with the specific
                    rejection reason, excluded from all further processing (FR-011)
"""

from __future__ import annotations

from dataclasses import dataclass

from energy_research.common.llm import build_backend
from energy_research.common.logging import get_logger, kv
from energy_research.config.settings import PipelineConfig
from energy_research.datastore.ledger import EvaluationLedger
from energy_research.datastore.repository import Repository, _new_id
from energy_research.generation.llm_client import ThesisLLMClient
from energy_research.generation.schemas import DraftRejection, validate_draft

log = get_logger("generation.service")


@dataclass
class GenerationOutcome:
    proposed_thesis_ids: list[str]
    invalid_thesis_ids: list[str]


class GenerationService:
    def __init__(self, repo: Repository, ledger: EvaluationLedger, config: PipelineConfig):
        self._repo = repo
        self._ledger = ledger
        self._config = config
        backend = build_backend(
            config.generation.backend,
            config.generation.anthropic_model,
            config.generation.anthropic_api_key_env,
        )
        self._client = ThesisLLMClient(backend)

    # ------------------------------------------------------------------ context

    def _discovery_context(self, cycle_id: str) -> tuple[str, str, dict]:
        keys = self._config.universe_keys
        data = self._repo.read_discovery_data(cycle_id, keys)
        rets = data.prices.pct_change().dropna(how="all")
        instruments = []
        lines = []
        for key in keys:
            series = rets[key].dropna()
            trend = float(series.mean()) if len(series) else 0.0
            vol = float(series.std(ddof=0)) if len(series) else 0.0
            instruments.append({"key": key, "trend": trend, "vol": vol})
            label = " [SYNTHETIC]" if data.provenance.get(key) == "synthetic" else ""
            lines.append(
                f"- {key}{label}: mean daily return {trend:+.5f}, "
                f"volatility {vol:.5f}, {len(series)} observations"
            )
        docs = self._repo.context_documents()
        doc_lines = [f"- [{d['category']}] ({d['provenance']}) {d['text']}" for d in docs]
        context = {
            "instruments": instruments,
            "qualitative": [{"category": d["category"], "text": d["text"]} for d in docs],
        }
        return "\n".join(lines), "\n".join(doc_lines) or "(none)", context

    # --------------------------------------------------------------- persistence

    def _persist_payload(
        self,
        cycle_id: str,
        payload: object,
        *,
        lineage_id: str | None,
        parent_thesis_id: str | None,
        iteration_index: int,
    ) -> tuple[str, bool]:
        """Validate and persist one raw payload; returns (thesis_id, is_valid)."""
        thesis_id = _new_id("th")
        if lineage_id is None:
            lineage_id = self._repo.create_lineage(cycle_id, root_thesis_id=thesis_id)
            self._ledger.create(lineage_id)
        try:
            draft = validate_draft(payload, self._config.universe_keys)
        except DraftRejection as exc:
            raw_rationale = ""
            raw_hypothesis: dict = {}
            if isinstance(payload, dict):
                raw_rationale = str(payload.get("rationale", ""))
                if isinstance(payload.get("hypothesis"), dict):
                    raw_hypothesis = payload["hypothesis"]
            self._repo.insert_thesis(
                thesis_id=thesis_id,
                cycle_id=cycle_id,
                lineage_id=lineage_id,
                parent_thesis_id=parent_thesis_id,
                iteration_index=iteration_index,
                rationale=raw_rationale or "(invalid draft: no rationale)",
                hypothesis=raw_hypothesis,
                status="invalid_schema",
                status_reason=exc.reason,
            )
            log.warning(
                "rejected invalid thesis draft %s", kv(thesis_id=thesis_id, reason=exc.reason)
            )
            return thesis_id, False
        self._repo.insert_thesis(
            thesis_id=thesis_id,
            cycle_id=cycle_id,
            lineage_id=lineage_id,
            parent_thesis_id=parent_thesis_id,
            iteration_index=iteration_index,
            rationale=draft.rationale,
            hypothesis=draft.hypothesis.model_dump(),
            status="proposed",
        )
        return thesis_id, True

    # ------------------------------------------------------------------ public

    def generate_initial(self, cycle_id: str, n: int) -> GenerationOutcome:
        """Propose the cycle's initial theses, one new lineage per draft."""
        market, qualitative, context = self._discovery_context(cycle_id)
        payloads = self._client.propose(
            market_summary=market,
            qualitative_summary=qualitative,
            universe_keys=self._config.universe_keys,
            n=n,
            context=context,
        )
        outcome = GenerationOutcome([], [])
        for payload in payloads:
            thesis_id, valid = self._persist_payload(
                cycle_id, payload, lineage_id=None, parent_thesis_id=None, iteration_index=0
            )
            (outcome.proposed_thesis_ids if valid else outcome.invalid_thesis_ids).append(thesis_id)
        log.info(
            "generation complete %s",
            kv(
                cycle_id=cycle_id,
                proposed=len(outcome.proposed_thesis_ids),
                invalid=len(outcome.invalid_thesis_ids),
            ),
        )
        return outcome

    def generate_refinement(
        self, cycle_id: str, parent_thesis_id: str, critique: dict
    ) -> tuple[str, bool]:
        """Generate one improved/alternative variant in the parent's lineage,
        informed by the given critique (FR-021). Returns (thesis_id, is_valid)."""
        parent = self._repo.get_thesis(parent_thesis_id)
        market, qualitative, context = self._discovery_context(cycle_id)
        trend_by_key = {i["key"]: i["trend"] for i in context["instruments"]}
        parent_instrument = parent["hypothesis"].get("instruments", [None])[0]
        parent_trend = trend_by_key.get(parent_instrument, 0.0)
        wrong_way = (parent["hypothesis"].get("direction") == "long" and parent_trend < 0) or (
            parent["hypothesis"].get("direction") == "short" and parent_trend > 0
        )
        context = dict(context)
        context["critique"] = {
            "suggested_direction": critique["suggested_direction"],
            "flip_direction": wrong_way,
        }
        if not wrong_way:
            # Steer the alternative away from the instrument that already failed.
            context["exclude_instruments"] = [parent_instrument]
        market += (
            f"\n\nPrior thesis in this lineage (iteration {parent['iteration_index']}) "
            f"was rejected. Critique weaknesses: {critique['weaknesses']}. "
            f"Suggested direction: {critique['suggested_direction']}"
        )
        payloads = self._client.propose(
            market_summary=market,
            qualitative_summary=qualitative,
            universe_keys=self._config.universe_keys,
            n=1,
            context=context,
        )
        payload = payloads[0] if payloads else {}
        return self._persist_payload(
            cycle_id,
            payload,
            lineage_id=parent["lineage_id"],
            parent_thesis_id=parent_thesis_id,
            iteration_index=parent["iteration_index"] + 1,
        )
