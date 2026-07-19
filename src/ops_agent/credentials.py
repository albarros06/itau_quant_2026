"""Credential-by-reference resolution (data-model.md ``CredentialReference``, FR-001).

A credential is *referenced* by environment-variable name everywhere in ``ops_agent``
config, proposals, and logs — never a secret value. ``resolve()`` is the only place
that reads the actual value from the environment, and it hands that value straight
to the caller (a connector/LLM transport) without ever assigning it to anything that
could be logged, serialized into a proposal, or written to ``ops_agent.sqlite``.
"""

from __future__ import annotations

import os
from typing import Literal

from ops_agent.config import StrictModel


class CredentialReference(StrictModel):
    env_var_name: str
    purpose: Literal["llm", "market_data", "qualitative_context"]


class CredentialError(RuntimeError):
    """A referenced credential is missing or empty — always raised visibly,
    never silently skipped (FR-001, Edge Case: invalid credentials)."""


def resolve(ref: CredentialReference) -> str:
    value = os.environ.get(ref.env_var_name)
    if not value:
        raise CredentialError(
            f"credential env var {ref.env_var_name!r} (purpose={ref.purpose!r}) is not set "
            "or empty"
        )
    return value
