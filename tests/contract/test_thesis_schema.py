"""Contract test: thesis generation output schema (contracts/thesis-schema.md)."""

from __future__ import annotations

import pytest

from energy_research.generation.schemas import DraftRejection, validate_draft

UNIVERSE = ["BR_POWER_SE_SPOT", "BR_POWER_SE_FWD_M1", "BRL_USD_FX", "BR_HYDRO_SE_RESERVOIR"]
# BR_HYDRO_SE_RESERVOIR is a signal-only statistic: in the universe (valid as a
# condition gate) but not tradeable, so it may never appear in hypothesis.instruments.
TRADEABLE = ["BR_POWER_SE_SPOT", "BR_POWER_SE_FWD_M1", "BRL_USD_FX"]


def valid_payload() -> dict:
    return {
        "rationale": "Reservoir levels are falling while forward prices lag the spot move, "
        "suggesting the front-month forward is underpricing hydrological risk.",
        "hypothesis": {
            "instruments": ["BR_POWER_SE_FWD_M1"],
            "direction": "long",
            "horizon": "1M",
            "condition": None,
            "testable_claim": "Front-month forward returns are positively drifting under "
            "the stated condition.",
        },
    }


def test_accepts_valid_draft():
    draft = validate_draft(valid_payload(), UNIVERSE, TRADEABLE)
    assert draft.hypothesis.direction == "long"
    assert draft.hypothesis.instruments == ["BR_POWER_SE_FWD_M1"]


def test_rejects_missing_required_fields():
    payload = valid_payload()
    del payload["hypothesis"]["testable_claim"]
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_short_rationale():
    payload = valid_payload()
    payload["rationale"] = "buy power"
    with pytest.raises(DraftRejection):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_unknown_direction():
    payload = valid_payload()
    payload["hypothesis"]["direction"] = "yolo"
    with pytest.raises(DraftRejection):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_extra_properties():
    """additionalProperties: false — nothing executable or unexpected rides along."""
    payload = valid_payload()
    payload["execute_order"] = "buy 100 lots"
    with pytest.raises(DraftRejection):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_out_of_universe_instrument():
    payload = valid_payload()
    payload["hypothesis"]["instruments"] = ["NATGAS_HH_FRONT"]
    with pytest.raises(DraftRejection, match="not in the configured instrument universe"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_duplicate_instruments():
    """A repeated instrument breaks common.signals.hypothesis_returns (selecting a
    duplicate-named column returns a DataFrame, not a Series) — must be rejected
    at the schema boundary, not crash downstream in screening/backtesting."""
    payload = valid_payload()
    payload["hypothesis"]["instruments"] = ["BR_POWER_SE_FWD_M1", "BR_POWER_SE_FWD_M1"]
    with pytest.raises(DraftRejection, match="contains duplicates"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_spread_with_single_instrument():
    payload = valid_payload()
    payload["hypothesis"]["direction"] = "spread"
    with pytest.raises(DraftRejection, match="requires exactly two instruments"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_free_text_condition():
    """The pre-003 free-text condition is gone: a string is a schema failure, not
    silently accepted (contracts/conditional-signal-contract.md rule 1)."""
    payload = valid_payload()
    payload["hypothesis"]["condition"] = "reservoir below median"
    with pytest.raises(DraftRejection, match="schema validation failed"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_rejects_non_mapping_payload():
    with pytest.raises(DraftRejection):
        validate_draft("SELECT * FROM theses", UNIVERSE, TRADEABLE)


def test_rejects_signal_only_instrument_as_traded_leg():
    """A signal-only statistic (in the universe but not tradeable — no price, no
    position, no short side) may never be a traded leg in hypothesis.instruments;
    it has no P&L interpretation as a basket position."""
    payload = valid_payload()
    payload["hypothesis"]["instruments"] = ["BR_HYDRO_SE_RESERVOIR"]
    with pytest.raises(DraftRejection, match="signal-only"):
        validate_draft(payload, UNIVERSE, TRADEABLE)


def test_accepts_signal_only_instrument_as_condition_gate():
    """The same signal-only key is the legitimate use case as a `condition` gate —
    using a statistic to decide *when* a thesis is active must not regress."""
    payload = valid_payload()
    payload["hypothesis"]["condition"] = {
        "clauses": [
            {
                "instrument_key": "BR_HYDRO_SE_RESERVOIR",
                "subject_transform": "level",
                "subject_lookback": None,
                "comparator": "<",
                "reference_kind": "constant",
                "reference_value": 80.0,
                "reference_lookback": None,
                "reference_quantile": None,
            }
        ]
    }
    draft = validate_draft(payload, UNIVERSE, TRADEABLE)
    assert draft.hypothesis.condition is not None
    assert draft.hypothesis.condition.clauses[0].instrument_key == "BR_HYDRO_SE_RESERVOIR"
