"""Operations agent configuration (data-model.md ``OpsAgentConfig``, Principle VI).

Mirrors ``energy_research.config.settings``'s ``StrictModel``/``extra="forbid"``
discipline exactly: a misconfigured ``ops_agent.yaml`` fails loudly at load time,
with no silent defaults for required sections (research.md §6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LlmConfig(StrictModel):
    api_key_env: str
    model: str
    # Mirrors energy_research.config.settings.GenerationConfig.backend exactly —
    # "deterministic_stub" makes discovery interpretation / onboarding drafting
    # fully offline and reproducible for tests and sample runs (research.md §11);
    # not itself in data-model.md's LlmConfig table but additive and backward
    # compatible (default preserves nothing since this field is required-with-
    # default, same treatment 001 gives its own backend selector).
    backend: Literal["deterministic_stub", "anthropic", "gemini"] = "deterministic_stub"


class OperatingSchedule(StrictModel):
    cycle_cadence_hours: float = Field(gt=0)
    market_refresh_cadence_hours: float = Field(gt=0)
    qualitative_poll_cadence_hours: float = Field(gt=0)


class ResourceBudgetConfig(StrictModel):
    period: Literal["hourly", "daily"]
    max_llm_calls: int = Field(ge=0)
    max_vendor_requests: int = Field(ge=0)


class RemediationConfig(StrictModel):
    """Bounds FR-008's automatic remediation attempts before escalation.

    Required, non-hardcoded per Constitution Principle VI — the same "threshold
    lives in config" treatment 001 gives ``data_quality.freshness_tolerance_days``.
    """

    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=30.0, gt=0)


class GitConfig(StrictModel):
    proposal_branch_prefix: str = "ops-proposal/"
    operating_branch: str = "main"
    remote: str | None = None


class NotificationConfig(StrictModel):
    sink: Literal["file"] = "file"
    path: Path = Path("data/ops_agent/notifications.jsonl")


class OpsAgentConfig(StrictModel):
    """The root of ``config/ops_agent.yaml``."""

    pipeline_config_path: Path
    llm: LlmConfig
    operating_schedule: OperatingSchedule
    resource_budgets: ResourceBudgetConfig
    remediation: RemediationConfig = RemediationConfig()
    git: GitConfig = GitConfig()
    notifications: NotificationConfig = NotificationConfig()


def load_ops_agent_config(path: str | Path) -> OpsAgentConfig:
    """Load and validate ``config/ops_agent.yaml``.

    Missing or invalid configuration raises a visible error (pydantic
    ``ValidationError`` / ``FileNotFoundError``) — no hidden defaults for required
    sections (Constitution Principle VI).
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} did not parse to a mapping")
    return OpsAgentConfig.model_validate(raw)
