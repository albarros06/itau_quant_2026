"""Contract test: conditional-signal vocabulary validation
(contracts/conditional-signal-contract.md rules 1–4). Mirrors test_thesis_schema.py."""

from __future__ import annotations

import pytest

from energy_research.generation.schemas import DraftRejection, validate_draft

UNIVERSE = ["BR_POWER_SE_SPOT", "BR_ENA_SE_MLT", "BRL_USD_FX"]
# BR_ENA_SE_MLT is a signal-only statistic — valid as a condition-clause gate
# (below) but not tradeable, so it is excluded from the traded-leg subset.
TRADEABLE = ["BR_POWER_SE_SPOT", "BRL_USD_FX"]


def _clause(**kw) -> dict:
    base = {
        "instrument_key": "BR_ENA_SE_MLT",
        "subject_transform": "level",
        "subject_lookback": None,
        "comparator": "<",
        "reference_kind": "constant",
        "reference_value": 80.0,
        "reference_lookback": None,
        "reference_quantile": None,
    }
    base.update(kw)
    return base


def _payload(clauses) -> dict:
    return {
        "rationale": "SE/CO inflows have been running persistently below their long-term mean, "
        "which historically precedes upward spot drift as thermal dispatch rises.",
        "hypothesis": {
            "instruments": ["BR_POWER_SE_SPOT"],
            "direction": "long",
            "horizon": "refinement_window",
            "condition": {"clauses": clauses},
            "testable_claim": "Mean daily long return is positive under the stated condition.",
        },
    }


def test_accepts_valid_condition():
    draft = validate_draft(_payload([_clause()]), UNIVERSE, TRADEABLE)
    assert draft.hypothesis.condition is not None
    assert draft.hypothesis.condition.clauses[0].reference_value == 80.0


def test_accepts_null_condition():
    payload = _payload([_clause()])
    payload["hypothesis"]["condition"] = None
    assert validate_draft(payload, UNIVERSE, TRADEABLE).hypothesis.condition is None


def test_free_text_condition_is_schema_invalid():
    payload = _payload([_clause()])
    payload["hypothesis"]["condition"] = "inflows below their long-term mean"
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


@pytest.mark.parametrize(
    "mutation",
    [
        {"subject_transform": "level", "subject_lookback": 10},  # level must not carry lookback
        {"subject_transform": "sma", "subject_lookback": None},  # sma requires lookback
        {"reference_kind": "constant", "reference_lookback": 5},  # constant must not carry lookback
        {"reference_kind": "sma", "reference_lookback": None},  # sma reference requires lookback
        {"reference_kind": "rolling_quantile", "reference_lookback": 20,
         "reference_quantile": None},  # rolling_quantile requires a quantile
    ],
)
def test_field_combination_validity_rejects_malformed_clauses(mutation):
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(_payload([_clause(**mutation)]), UNIVERSE, TRADEABLE)


def test_quantile_out_of_range_rejected():
    clause = _clause(
        reference_kind="rolling_quantile", reference_lookback=20, reference_quantile=1.5
    )
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(_payload([clause]), UNIVERSE, TRADEABLE)


def test_clause_count_bound_enforced():
    payload = _payload([_clause() for _ in range(4)])  # max_clauses default 3
    with pytest.raises(DraftRejection, match="max_clauses"):
        validate_draft(payload, UNIVERSE, TRADEABLE, max_clauses=3)


def test_lookback_bound_enforced():
    clause = _clause(subject_transform="sma", subject_lookback=999)
    with pytest.raises(DraftRejection, match="max_lookback_days"):
        validate_draft(_payload([clause]), UNIVERSE, TRADEABLE, max_lookback_days=90)


def test_out_of_universe_clause_instrument_rejected():
    clause = _clause(instrument_key="NATGAS_HH_FRONT")
    with pytest.raises(DraftRejection, match="not in the configured universe"):
        validate_draft(_payload([clause]), UNIVERSE, TRADEABLE)


def test_empty_clause_list_rejected():
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(_payload([]), UNIVERSE, TRADEABLE)
