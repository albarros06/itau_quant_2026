"""Backtesting service: refinement-split runs and the ledger-gated final run.

Refinement runs require a recorded ``pass`` screening verdict first — no thesis is
backtested without evidence (FR-013, SC-003). The single final-evaluation run per
lineage happens only after ``EvaluationLedger.spend()`` returns GRANTED; a REFUSED
outcome records the refusal and runs nothing (contracts/evaluation-ledger-contract.md
— the atomic spend lives here in backtesting, orchestration only decides when).
"""

from __future__ import annotations

from energy_research.backtesting.costs import CostModel
from energy_research.backtesting.engine import run_backtest
from energy_research.common.conditions import condition_from_hypothesis
from energy_research.common.logging import get_logger, kv
from energy_research.common.signals import hypothesis_returns
from energy_research.config.settings import PipelineConfig
from energy_research.datastore.ledger import EvaluationLedger, SpendOutcome
from energy_research.datastore.repository import Repository

log = get_logger("backtesting.service")


class BacktestingService:
    def __init__(self, repo: Repository, ledger: EvaluationLedger, config: PipelineConfig):
        self._repo = repo
        self._ledger = ledger
        self._config = config
        self._cost_model = CostModel(config.backtesting)

    def _activity_gate(self, data, hypothesis: dict, split: str) -> str | None:
        """Refuse a condition active on too few days of ``split`` (FR-006). Returns a
        rejection reason naming both counts, or None if the condition clears the bar."""
        min_active = getattr(self._config.conditional_screening.min_active_days, split)
        _, activity = hypothesis_returns(
            data.prices,
            hypothesis["instruments"],
            hypothesis["direction"],
            condition_from_hypothesis(hypothesis),
        )
        if activity.in_market_days >= min_active:
            return None
        log.warning(
            "under-observed condition refused %s",
            kv(split=split, in_market_days=activity.in_market_days, required=min_active),
        )
        return (
            f"condition active on only {activity.in_market_days} {split}-split days, below "
            f"the required minimum {min_active} — refused before backtesting, no result "
            "persisted (FR-006)"
        )

    def run_refinement(self, thesis_id: str) -> dict:
        """Refinement-split backtest for a screening survivor; updates status to
        ``backtested`` or ``rejected_underperform``."""
        thesis = self._repo.get_thesis(thesis_id)
        screening = self._repo.screening_result_for(thesis_id)
        if screening is None or screening["verdict"] != "pass":
            raise PermissionError(
                f"thesis {thesis_id} has no recorded screening pass verdict — it must "
                "not be backtested (FR-013, SC-003)"
            )
        data = self._repo.read_refinement_data(thesis["cycle_id"], self._config.universe_keys)
        gate = self._activity_gate(data, thesis["hypothesis"], "refinement")
        if gate is not None:
            self._repo.update_thesis_status(thesis_id, "rejected_underperform", gate)
            return {"net_return": None, "gross_return": None}
        result = run_backtest(data, thesis["hypothesis"], self._cost_model)
        self._repo.insert_backtest_result(
            thesis_id=thesis_id,
            split_type="refinement",
            gross_return=result.gross_return,
            transaction_costs=result.transaction_costs,
            slippage=result.slippage,
            financing_carry=result.financing_carry,
            net_return=result.net_return,
            other_metrics=result.other_metrics,
        )
        bar = self._config.backtesting.underperform_net_return_threshold
        if result.net_return <= bar:
            reason = (
                f"refinement-split net return {result.net_return:+.4f} (gross "
                f"{result.gross_return:+.4f} minus costs {result.transaction_costs:.4f} "
                f"+ slippage {result.slippage:.4f} + financing "
                f"{result.financing_carry:.4f}) did not exceed the underperformance "
                f"bar {bar:+.4f}"
            )
            self._repo.update_thesis_status(thesis_id, "rejected_underperform", reason)
        else:
            self._repo.update_thesis_status(
                thesis_id,
                "backtested",
                f"refinement-split net return {result.net_return:+.4f} above the "
                f"underperformance bar",
            )
        return {"net_return": result.net_return, "gross_return": result.gross_return}

    def run_final_evaluation(self, thesis_id: str) -> str:
        """Spend the lineage's one-time entitlement and run the final backtest.

        Returns the thesis's terminal status: ``promoted``, ``rejected_after_final``,
        or ``refused`` (ledger already spent — recorded, nothing run).
        """
        thesis = self._repo.get_thesis(thesis_id)
        outcome = self._ledger.spend(thesis["lineage_id"], thesis_id)
        if outcome == SpendOutcome.REFUSED:
            reason = (
                f"final evaluation refused: lineage {thesis['lineage_id']}'s one-time "
                "final-evaluation entitlement was already spent (FR-019); refusal "
                "recorded in the evaluation ledger"
            )
            self._repo.update_thesis_status(thesis_id, "refused", reason)
            log.warning(
                "final evaluation refused %s",
                kv(thesis_id=thesis_id, lineage_id=thesis["lineage_id"]),
            )
            return "refused"

        # The final-evaluation read is ledger-gated (FR-019), so the activity gate
        # necessarily runs after the spend; an under-observed final thesis is
        # recorded rejected_after_final with no BacktestResult (turnover-cost rule 5).
        data = self._repo.read_final_evaluation_data(thesis["cycle_id"], self._config.universe_keys)
        gate = self._activity_gate(data, thesis["hypothesis"], "final_evaluation")
        if gate is not None:
            self._repo.update_thesis_status(thesis_id, "rejected_after_final", gate)
            return "rejected_after_final"
        result = run_backtest(data, thesis["hypothesis"], self._cost_model)
        self._repo.insert_backtest_result(
            thesis_id=thesis_id,
            split_type="final_evaluation",
            gross_return=result.gross_return,
            transaction_costs=result.transaction_costs,
            slippage=result.slippage,
            financing_carry=result.financing_carry,
            net_return=result.net_return,
            other_metrics=result.other_metrics,
        )
        bar = self._config.backtesting.promotion_net_return_threshold
        detail = (
            f"final-evaluation net return {result.net_return:+.4f} (gross "
            f"{result.gross_return:+.4f}, transaction costs "
            f"{result.transaction_costs:.4f}, slippage {result.slippage:.4f}, "
            f"financing/carry {result.financing_carry:.4f}) vs promotion bar {bar:+.4f}"
        )
        if result.net_return > bar:
            self._repo.update_thesis_status(thesis_id, "promoted", detail)
            return "promoted"
        self._repo.update_thesis_status(thesis_id, "rejected_after_final", detail)
        return "rejected_after_final"
