"""Multiplicity control across all theses screened in a cycle (FR-030, SC-011).

A per-thesis p-value alone is never sufficient for a pass verdict: the family-level
correction is applied over the full set of p-values in the cycle, and the corrected
threshold actually applied is returned so it can be recorded on every
ScreeningResult. The method is configurable; its presence is not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MultiplicityDecision:
    method: str
    adjusted_threshold: float  # the corrected bar actually applied to p-values
    passes: list[bool]  # per input p-value, family-corrected


def benjamini_hochberg(p_values: list[float], alpha: float) -> MultiplicityDecision:
    """Benjamini-Hochberg false-discovery-rate control."""
    m = len(p_values)
    if m == 0:
        return MultiplicityDecision("benjamini_hochberg", 0.0, [])
    order = np.argsort(p_values)
    sorted_p = np.asarray(p_values, dtype=float)[order]
    critical = alpha * (np.arange(1, m + 1) / m)
    below = np.nonzero(sorted_p <= critical)[0]
    if len(below) == 0:
        # Nothing passes; the strictest rank-1 critical value is the bar applied.
        threshold = float(critical[0])
        return MultiplicityDecision("benjamini_hochberg", threshold, [False] * m)
    k = below.max()  # largest rank whose p-value clears its critical value
    threshold = float(critical[k])
    passes = [p <= threshold for p in p_values]
    return MultiplicityDecision("benjamini_hochberg", threshold, passes)


def bonferroni(p_values: list[float], alpha: float) -> MultiplicityDecision:
    m = len(p_values)
    if m == 0:
        return MultiplicityDecision("bonferroni", 0.0, [])
    threshold = alpha / m
    return MultiplicityDecision("bonferroni", threshold, [p <= threshold for p in p_values])


def apply(method: str, p_values: list[float], alpha: float) -> MultiplicityDecision:
    if method == "benjamini_hochberg":
        return benjamini_hochberg(p_values, alpha)
    if method == "bonferroni":
        return bonferroni(p_values, alpha)
    raise ValueError(
        f"unknown multiplicity method {method!r} — multiplicity control is mandatory "
        "and cannot be disabled (FR-030)"
    )
