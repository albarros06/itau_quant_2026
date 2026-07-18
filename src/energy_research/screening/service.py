"""Screening service: discovery-split-only statistical screening with mandatory
multiplicity control (contracts/screening-contract.md).

The only data-access path used is ``Repository.read_discovery_data`` — this layer
has no way to request refinement or final-evaluation data (FR-014). Every screened
thesis receives an explicit pass/fail verdict with a specific reason referencing
the statistic/threshold comparison (FR-015), and the multiplicity-adjusted
threshold is recorded on every result — there is no unadjusted output mode
(FR-030).
"""

from __future__ import annotations

from dataclasses import dataclass

from energy_research.common import seed as seed_mod
from energy_research.common.logging import get_logger, kv
from energy_research.common.signals import hypothesis_returns
from energy_research.config.settings import PipelineConfig
from energy_research.datastore.repository import Repository
from energy_research.screening import methods, multiplicity

log = get_logger("screening.service")


@dataclass
class ScreeningOutcome:
    passed_thesis_ids: list[str]
    failed_thesis_ids: list[str]


class ScreeningService:
    def __init__(self, repo: Repository, config: PipelineConfig):
        self._repo = repo
        self._config = config

    def screen_cycle(self, cycle_id: str, thesis_ids: list[str] | None = None) -> ScreeningOutcome:
        """Screen the given (or all ``proposed``) theses of a cycle as one family.

        The full set is required input: multiplicity adjustment cannot be computed
        per-thesis in isolation (screening-contract.md Input).
        """
        cfg = self._config.screening
        theses = self._repo.theses_for_cycle(cycle_id, status="proposed")
        if thesis_ids is not None:
            theses = [t for t in theses if t["thesis_id"] in thesis_ids]
        if not theses:
            return ScreeningOutcome([], [])

        data = self._repo.read_discovery_data(cycle_id, self._config.universe_keys)
        rng = seed_mod.get_rng()

        tests: list[methods.TestResult] = []
        for thesis in theses:
            hyp = thesis["hypothesis"]
            returns = hypothesis_returns(
                data.prices, hyp["instruments"], hyp["direction"]
            ).to_numpy()
            tests.append(
                methods.block_bootstrap_test(returns, rng, cfg.n_bootstrap, cfg.block_size)
            )

        decision = multiplicity.apply(
            cfg.multiplicity_method, [t.p_value for t in tests], cfg.alpha
        )

        outcome = ScreeningOutcome([], [])
        for thesis, test, passed in zip(theses, tests, decision.passes, strict=True):
            verdict = "pass" if passed else "fail"
            comparison = "<=" if passed else ">"
            reason = (
                f"{test.method} one-sided p-value {test.p_value:.4f} {comparison} "
                f"{decision.method}-adjusted threshold {decision.adjusted_threshold:.4f} "
                f"(statistic {test.statistic_value:+.2f}, family of {len(tests)} theses, "
                f"alpha {cfg.alpha}) on discovery-split data "
                f"{data.date_range[0]}..{data.date_range[1]}"
            )
            self._repo.insert_screening_result(
                thesis_id=thesis["thesis_id"],
                method=test.method,
                statistic_value=test.statistic_value,
                p_value=test.p_value,
                multiplicity_method=decision.method,
                adjusted_threshold=decision.adjusted_threshold,
                verdict=verdict,
                reason=reason,
            )
            if passed:
                self._repo.update_thesis_status(thesis["thesis_id"], "screened_passed", reason)
                outcome.passed_thesis_ids.append(thesis["thesis_id"])
            else:
                self._repo.update_thesis_status(thesis["thesis_id"], "screened_rejected", reason)
                outcome.failed_thesis_ids.append(thesis["thesis_id"])
        log.info(
            "screening complete %s",
            kv(
                cycle_id=cycle_id,
                screened=len(theses),
                passed=len(outcome.passed_thesis_ids),
                adjusted_threshold=decision.adjusted_threshold,
                multiplicity=decision.method,
            ),
        )
        return outcome
