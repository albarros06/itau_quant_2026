from __future__ import annotations

import numpy as np
import pytest

from energy_research.screening.methods import block_bootstrap_test
from energy_research.screening.multiplicity import benjamini_hochberg, bonferroni


class TestBlockBootstrap:
    def test_strong_positive_drift_yields_small_p(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0.003, 0.01, size=600)
        result = block_bootstrap_test(returns, np.random.default_rng(2), 400, 10)
        assert result.p_value < 0.01
        assert result.statistic_value > 3

    def test_pure_noise_yields_large_p(self):
        rng = np.random.default_rng(4)
        returns = rng.normal(0.0, 0.02, size=600)
        result = block_bootstrap_test(returns, np.random.default_rng(104), 400, 10)
        assert result.p_value > 0.05

    def test_negative_drift_never_passes_one_sided_test(self):
        rng = np.random.default_rng(5)
        returns = rng.normal(-0.003, 0.01, size=600)
        result = block_bootstrap_test(returns, np.random.default_rng(6), 400, 10)
        assert result.p_value > 0.5

    def test_too_short_series_is_inconclusive_not_a_pass(self):
        result = block_bootstrap_test(np.array([0.01, 0.02]), np.random.default_rng(7), 100, 10)
        assert result.p_value == 1.0

    def test_deterministic_given_same_rng_seed(self):
        returns = np.random.default_rng(8).normal(0.001, 0.01, size=400)
        a = block_bootstrap_test(returns, np.random.default_rng(9), 200, 10)
        b = block_bootstrap_test(returns, np.random.default_rng(9), 200, 10)
        assert a == b


class TestMultiplicity:
    def test_bh_known_example(self):
        # p = [0.01, 0.02, 0.03, 0.5], alpha = 0.1 → critical = [.025, .05, .075, .1]
        # largest k with p_(k) <= crit_k is rank 3 (0.03 <= 0.075) → threshold .075
        decision = benjamini_hochberg([0.01, 0.02, 0.03, 0.5], alpha=0.1)
        assert decision.adjusted_threshold == pytest.approx(0.075)
        assert decision.passes == [True, True, True, False]

    def test_bh_nothing_passes_records_strictest_bar(self):
        decision = benjamini_hochberg([0.5, 0.9], alpha=0.1)
        assert decision.passes == [False, False]
        assert decision.adjusted_threshold == pytest.approx(0.05)  # alpha * 1/m

    def test_bh_threshold_never_exceeds_alpha(self):
        decision = benjamini_hochberg([0.001, 0.002, 0.003], alpha=0.1)
        assert decision.adjusted_threshold <= 0.1

    def test_bonferroni(self):
        decision = bonferroni([0.01, 0.04], alpha=0.06)
        assert decision.adjusted_threshold == pytest.approx(0.03)
        assert decision.passes == [True, False]

    def test_empty_family(self):
        assert benjamini_hochberg([], 0.1).passes == []
