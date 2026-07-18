"""TradingThesisDraft: the ONLY channel through which LLM output enters the system.

Mirrors contracts/thesis-schema.md exactly. Validation is strict (``extra="forbid"``)
and failure is terminal for the draft — no repair, no coercion (FR-011). Instruments
outside the configured universe fail validation with a specific reason
(spec Edge Case: "Generation requests an instrument or market not in configuration").
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class HypothesisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: list[str] = Field(min_length=1)
    direction: Literal["long", "short", "spread", "relative_value"]
    horizon: str
    condition: str
    testable_claim: str = Field(min_length=10)


class TradingThesisDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str = Field(min_length=20)
    hypothesis: HypothesisDraft


class DraftRejection(Exception):
    """A draft failed validation; carries the specific reason recorded on the thesis."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_draft(payload: object, universe_keys: list[str]) -> TradingThesisDraft:
    """Independently re-validate a raw LLM payload (two-stage validation, rule 1).

    Raises :class:`DraftRejection` with a specific reason on any failure; never
    repairs or partially accepts (FR-011).
    """
    try:
        draft = TradingThesisDraft.model_validate(payload)
    except ValidationError as exc:
        raise DraftRejection(f"schema validation failed: {exc.errors()}") from exc

    unknown = [i for i in draft.hypothesis.instruments if i not in universe_keys]
    if unknown:
        raise DraftRejection(
            f"instruments {unknown} are not in the configured instrument universe "
            f"{universe_keys} — thesis is out of the configured universe"
        )
    directions_needing_pair = ("spread", "relative_value")
    if (
        draft.hypothesis.direction in directions_needing_pair
        and len(draft.hypothesis.instruments) < 2
    ):
        raise DraftRejection(
            f"direction {draft.hypothesis.direction!r} requires at least two instruments, "
            f"got {draft.hypothesis.instruments}"
        )
    return draft
