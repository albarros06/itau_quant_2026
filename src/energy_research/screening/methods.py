"""Statistical screening methods (research.md §4).

Default: circular block bootstrap significance test on the thesis's hypothesized
strategy returns — robust to the serial autocorrelation typical of financial time
series. Method selection is configuration-driven (FR-016); this module contains
the implementations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class TestResult:
    method: str
    statistic_value: float  # t-like statistic sqrt(n) * mean / std
    p_value: float  # one-sided: H1 = mean strategy return > 0


def block_bootstrap_test(
    returns: np.ndarray, rng: np.random.Generator, n_bootstrap: int, block_size: int
) -> TestResult:
    """One-sided circular block bootstrap test of H0: mean return <= 0."""
    returns = np.asarray(returns, dtype=float)
    n = len(returns)
    if n < 2 * block_size:
        return TestResult("block_bootstrap", statistic_value=0.0, p_value=1.0)

    observed_mean = returns.mean()
    # Sample std (ddof=1): the return series is a sample, not the population; keep
    # this in lockstep with backtesting.engine's Sharpe (same convention).
    std = returns.std(ddof=1)
    statistic = float(np.sqrt(n) * observed_mean / std) if std > 0 else 0.0

    # Resample under the null: demean, then draw circular blocks.
    centered = returns - observed_mean
    n_blocks = int(np.ceil(n / block_size))
    starts = rng.integers(0, n, size=(n_bootstrap, n_blocks))
    offsets = np.arange(block_size)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n  # (B, n_blocks, block)
    samples = centered[idx].reshape(n_bootstrap, -1)[:, :n]
    boot_means = samples.mean(axis=1)

    p_value = float((1 + np.sum(boot_means >= observed_mean)) / (n_bootstrap + 1))
    return TestResult("block_bootstrap", statistic_value=statistic, p_value=p_value)
