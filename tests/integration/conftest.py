"""Shared fixture: a fresh git repo with a minimal, credentials-only pipeline seed
config, for ops_agent's US1-US4 integration tests (quickstart.md, research.md §11).

The seed config is the smallest thing that satisfies 001's ``PipelineConfig``
schema (``instrument_universe``/``providers.market_data`` both require at least one
entry) — everything beyond that single seed instrument/provider is expected to
arrive via agent-drafted, researcher-approved proposals, not hand-editing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from ops_agent.config import OpsAgentConfig

RESEARCHER_NAME = "Researcher"
RESEARCHER_EMAIL = "researcher@example.com"

DEFAULT_YAML_SEED = {
    "providers_file": "providers.yaml",
    "datastore": {
        "db_path": "data/research.sqlite",
        "lake_dir": "data/lake",
        "reports_dir": "data/reports",
    },
    "instrument_universe": [
        {"key": "BR_POWER_SE_SPOT", "category": "spot", "description": "seed instrument"},
    ],
    "data_quality": {
        "freshness_tolerance_days": 7,
        "max_gap_days": 7,
        "outlier_zscore_threshold": 8.0,
    },
    "splits": {"discovery_fraction": 0.5, "refinement_fraction": 0.3},
    "screening": {
        "method": "block_bootstrap",
        "n_bootstrap": 200,
        "block_size": 10,
        "alpha": 0.10,
        "multiplicity_method": "benjamini_hochberg",
    },
    "backtesting": {
        "transaction_cost_bps": 5.0,
        "slippage_bps": 3.0,
        "financing_annual_rate": 0.11,
    },
    "refinement": {"max_refinement_depth_per_lineage": 1, "max_lineages_per_run": 4},
    "generation": {"backend": "deterministic_stub", "max_theses_per_cycle": 4},
    "reproducibility": {"seed": 20260719},
}

PROVIDERS_YAML_SEED = {
    "market_data": [
        {"provider_id": "sample_provider", "categories": ["spot"], "options": {}},
    ],
    "qualitative_context": [
        {"provider_id": "sample_provider", "categories": ["news"], "options": {}},
    ],
}


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def ops_agent_repo(tmp_path) -> tuple[Path, OpsAgentConfig]:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", RESEARCHER_NAME], cwd=repo_dir)
    run_git(["config", "user.email", RESEARCHER_EMAIL], cwd=repo_dir)

    config_dir = repo_dir / "config"
    config_dir.mkdir()
    (config_dir / "default.yaml").write_text(yaml.safe_dump(DEFAULT_YAML_SEED, sort_keys=False))
    (config_dir / "providers.yaml").write_text(
        yaml.safe_dump(PROVIDERS_YAML_SEED, sort_keys=False)
    )

    ops_agent_config = OpsAgentConfig(
        pipeline_config_path="config/default.yaml",
        llm={"api_key_env": "TEST_LLM_KEY", "model": "stub-model", "backend": "deterministic_stub"},
        operating_schedule={
            "cycle_cadence_hours": 1e-7,
            "market_refresh_cadence_hours": 1e-7,
            "qualitative_poll_cadence_hours": 1e-7,
        },
        resource_budgets={"period": "daily", "max_llm_calls": 50, "max_vendor_requests": 50},
        notifications={
            "sink": "file",
            "path": str(repo_dir / "data" / "ops_agent" / "notifications.jsonl"),
        },
    )
    (config_dir / "ops_agent.yaml").write_text(
        yaml.safe_dump(ops_agent_config.model_dump(mode="json"), sort_keys=False)
    )

    run_git(["add", "-A"], cwd=repo_dir)
    run_git(
        ["commit", "-m", "seed: minimal credentials-only configuration"], cwd=repo_dir
    )
    return repo_dir, ops_agent_config
