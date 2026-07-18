"""Contract test: critique output schema (contracts/critique-schema.md)."""

from __future__ import annotations

import pytest

from energy_research.critique.schemas import CritiqueRejection, validate_critique


def valid_payload() -> dict:
    return {
        "weaknesses": [
            "Screening p-value 0.31 exceeded the BH-adjusted threshold 0.025 for "
            "BR_POWER_SE_SPOT — the hypothesized short drift is indistinguishable "
            "from noise on discovery data.",
        ],
        "suggested_direction": "Target BR_POWER_SE_FWD_M1 instead, whose discovery "
        "drift is positive and stable across subsamples.",
    }


def test_accepts_valid_critique():
    critique = validate_critique(valid_payload())
    assert len(critique.weaknesses) == 1


def test_rejects_empty_weaknesses():
    payload = valid_payload()
    payload["weaknesses"] = []
    with pytest.raises(CritiqueRejection):
        validate_critique(payload)


def test_rejects_missing_suggested_direction():
    payload = valid_payload()
    del payload["suggested_direction"]
    with pytest.raises(CritiqueRejection, match="schema validation failed"):
        validate_critique(payload)


def test_rejects_short_suggested_direction():
    payload = valid_payload()
    payload["suggested_direction"] = "improve"
    with pytest.raises(CritiqueRejection):
        validate_critique(payload)


def test_rejects_generic_weaknesses():
    payload = valid_payload()
    payload["weaknesses"] = ["needs more data"]
    with pytest.raises(CritiqueRejection, match="generic"):
        validate_critique(payload)


def test_rejects_too_short_weakness():
    payload = valid_payload()
    payload["weaknesses"] = ["bad p"]
    with pytest.raises(CritiqueRejection, match="too short"):
        validate_critique(payload)


def test_rejects_extra_properties():
    payload = valid_payload()
    payload["execute"] = "sell everything"
    with pytest.raises(CritiqueRejection):
        validate_critique(payload)
