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
from energy_research.common.conditions import condition_from_hypothesis
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

        data = self._repo.read_discovery_data(
            cycle_id, self._config.universe_keys, self._config.instrument_calendars
        )
        rng = seed_mod.get_rng()
        min_active = self._config.conditional_screening.min_active_days.discovery

        outcome = ScreeningOutcome([], [])

        # First pass: compute each thesis's (conditional) return stream and activity.
        # A condition active on fewer than min_active discovery-split days is refused
        # here — before any statistic exists — and never enters the multiplicity
        # family (contracts/conditional-signal-contract.md rules 10–11).
        tested: list[tuple[dict, object, object]] = []  # (thesis, returns array, activity)
        for thesis in theses:
            hyp = thesis["hypothesis"]
            condition = condition_from_hypothesis(hyp)
            returns_s, activity = hypothesis_returns(
                data.prices, hyp["instruments"], hyp["direction"], condition
            )
            if activity.in_market_days < min_active:
                reason = (
                    f"condition active on only {activity.in_market_days} discovery-split "
                    f"days, below the required minimum {min_active} — refused before "
                    "testing and excluded from the multiplicity family (FR-006)"
                )
                self._repo.update_thesis_status(thesis["thesis_id"], "screened_rejected", reason)
                outcome.failed_thesis_ids.append(thesis["thesis_id"])
                log.warning(
                    "under-observed condition refused %s",
                    kv(
                        thesis_id=thesis["thesis_id"],
                        in_market_days=activity.in_market_days,
                        required=min_active,
                    ),
                )
                continue
            tested.append((thesis, returns_s.to_numpy(), activity))

        tests: list[methods.TestResult] = [
            methods.block_bootstrap_test(returns, rng, cfg.n_bootstrap, cfg.block_size)
            for _, returns, _ in tested
        ]
        decision = multiplicity.apply(
            cfg.multiplicity_method, [t.p_value for t in tests], cfg.alpha
        )

        for (thesis, _, activity), test, passed in zip(tested, tests, decision.passes, strict=True):
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
                other_metrics=activity.as_dict(),
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
