"""ThesisCritique schema (contracts/critique-schema.md, FR-020).

Same constrained-autonomy rules as thesis generation: structured, schema-validated,
never free-form, no repair on failure. The post-check rejects weaknesses generic
enough to apply to any thesis, consistent with FR-020's "specific weaknesses".
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_GENERIC_PHRASES = (
    "needs more data",
    "could be improved",
    "not good enough",
    "may not work",
    "requires further analysis",
)


class ThesisCritique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weaknesses: list[str] = Field(min_length=1)
    suggested_direction: str = Field(min_length=10)


class CritiqueRejection(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_critique(payload: object) -> ThesisCritique:
    """Independently re-validate a raw critique payload; reject, never repair."""
    try:
        critique = ThesisCritique.model_validate(payload)
    except ValidationError as exc:
        raise CritiqueRejection(f"schema validation failed: {exc.errors()}") from exc
    for weakness in critique.weaknesses:
        if len(weakness.strip()) < 10:
            raise CritiqueRejection(f"weakness {weakness!r} is too short to be specific (FR-020)")
        if weakness.strip().lower() in _GENERIC_PHRASES:
            raise CritiqueRejection(
                f"weakness {weakness!r} is generic enough to apply to any thesis — "
                "critiques must identify specific weaknesses (FR-020)"
            )
    return critique
