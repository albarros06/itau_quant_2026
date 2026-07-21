"""Closed conditional-signal vocabulary and its pure, split-scoped evaluator.

A ``SignalCondition`` is the structured, schema-validated replacement for the old
free-text ``condition`` field (003 FR-001/FR-002). ``evaluate_condition`` turns one
into a deterministic daily 0/1 position mask over a single split's price panel — no
I/O, no randomness, output a function of its inputs only
(contracts/conditional-signal-contract.md rules 5–8). It lives in ``common`` because
both ``screening`` and ``backtesting`` must evaluate conditions and neither may
import the other (research.md §1), mirroring ``hypothesis_returns`` beside it.
"""

from __future__ import annotations

import operator
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

SubjectTransform = Literal["level", "sma", "change"]
Comparator = Literal["<", "<=", ">", ">="]
ReferenceKind = Literal["constant", "sma", "rolling_quantile"]

_COMPARATORS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}


class ConditionClause(BaseModel):
    """One comparison of an instrument's (transformed) series against a reference.

    Every field is always present with an explicit ``null`` for the inapplicable
    ones — a structured-output model emits a fixed field set more reliably than it
    reasons about which to omit (contracts/conditional-signal-contract.md).
    """

    model_config = ConfigDict(extra="forbid")

    instrument_key: str
    subject_transform: SubjectTransform
    subject_lookback: int | None = Field(default=None, ge=1)
    comparator: Comparator
    reference_kind: ReferenceKind
    reference_value: float
    reference_lookback: int | None = Field(default=None, ge=1)
    reference_quantile: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _field_combination_validity(self) -> ConditionClause:
        # Subject side: only sma/change take a lookback; level must not.
        if self.subject_transform == "level":
            if self.subject_lookback is not None:
                raise ValueError("subject_transform='level' requires subject_lookback=null")
        elif self.subject_lookback is None:
            raise ValueError(
                f"subject_transform={self.subject_transform!r} requires subject_lookback set"
            )
        # Reference side: constant takes neither lookback nor quantile; sma takes a
        # lookback only; rolling_quantile takes both.
        if self.reference_kind == "constant":
            if self.reference_lookback is not None or self.reference_quantile is not None:
                raise ValueError(
                    "reference_kind='constant' requires reference_lookback=null and "
                    "reference_quantile=null"
                )
        elif self.reference_kind == "sma":
            if self.reference_lookback is None:
                raise ValueError("reference_kind='sma' requires reference_lookback set")
            if self.reference_quantile is not None:
                raise ValueError("reference_kind='sma' requires reference_quantile=null")
        elif self.reference_kind == "rolling_quantile" and (
            self.reference_lookback is None or self.reference_quantile is None
        ):
            raise ValueError(
                "reference_kind='rolling_quantile' requires reference_lookback and "
                "reference_quantile set"
            )
        return self


class SignalCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clauses: list[ConditionClause] = Field(min_length=1)


def condition_from_hypothesis(hypothesis: dict) -> SignalCondition | None:
    """Rebuild a ``SignalCondition`` from a persisted ``hypothesis`` JSON dict.

    ``hypothesis['condition']`` is stored as a plain dict (or absent/``None`` for an
    unconditional thesis); screening and backtesting both use this to recover the
    typed model before evaluating.
    """
    raw = hypothesis.get("condition")
    if raw is None:
        return None
    if isinstance(raw, SignalCondition):
        return raw
    return SignalCondition.model_validate(raw)


def _subject_series(prices: pd.DataFrame, clause: ConditionClause) -> pd.Series:
    series = prices[clause.instrument_key]
    if clause.subject_transform == "level":
        return series
    if clause.subject_transform == "sma":
        return series.rolling(clause.subject_lookback).mean()
    # change
    return series.diff(clause.subject_lookback)


def _reference_series(prices: pd.DataFrame, clause: ConditionClause) -> pd.Series:
    series = prices[clause.instrument_key]
    if clause.reference_kind == "constant":
        return pd.Series(clause.reference_value, index=prices.index)
    if clause.reference_kind == "sma":
        return series.rolling(clause.reference_lookback).mean()
    # rolling_quantile
    return series.rolling(clause.reference_lookback).quantile(clause.reference_quantile)


def _clause_active(prices: pd.DataFrame, clause: ConditionClause) -> pd.Series:
    """Boolean per-day activity for one clause; warmup (NaN either side) is False."""
    if clause.instrument_key not in prices.columns:
        raise KeyError(f"condition references instrument {clause.instrument_key!r} not in panel")
    subject = _subject_series(prices, clause)
    reference = _reference_series(prices, clause)
    valid = subject.notna() & reference.notna()  # rolling/diff warmup → inactive, never active
    return _COMPARATORS[clause.comparator](subject, reference) & valid


def evaluate_condition(prices: pd.DataFrame, condition: SignalCondition | None) -> pd.Series:
    """Deterministic daily 0/1 exposure mask over one split's ``prices`` panel.

    ``None`` is unconditional: constant 1.0 for the whole panel (the pre-003
    always-in-market behavior, FR-012). Otherwise every clause is AND-combined
    (a NaN/warmup clause keeps the whole condition inactive), then the boolean is
    shifted forward exactly one day — a value observable at close of day *t*
    influences exposure from *t+1* only (FR-004, no lookahead). The result is a
    float 0.0/1.0 series indexed identically to ``prices``.
    """
    if condition is None:
        return pd.Series(1.0, index=prices.index)

    active: pd.Series | None = None
    for clause in condition.clauses:
        clause_active = _clause_active(prices, clause)
        active = clause_active if active is None else (active & clause_active)

    assert active is not None  # SignalCondition guarantees >= 1 clause
    active = active.fillna(False)
    shifted = active.shift(1, fill_value=False)  # decision at t → exposure at t+1
    return shifted.astype(float)
