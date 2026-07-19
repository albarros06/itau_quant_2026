"""US2 end-to-end: hands-off continuous operation (spec.md User Story 2,
Acceptance Scenarios 1-5).

Unlike US1's fixture (which starts from a single-instrument seed to be
approved/expanded), these tests start from an already-provisioned operation —
US2 is about *staying current*, not provisioning.
"""

from __future__ import annotations

import json

import pytest
import yaml

from ops_agent.agent import OpsAgent
from tests.integration.conftest import run_git

_TINY_CADENCE_HOURS = 1e-7  # effectively "always due once any real time has passed"


def _write_pipeline_seed(repo_dir, *, freshness_tolerance_days: float = 7) -> None:
    config_dir = repo_dir / "config"
    config_dir.mkdir(exist_ok=True)
    context_dir = repo_dir / "dropzone" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "news.jsonl").write_text(
        json.dumps({"source": "wire", "ts": "2026-07-01T00:00:00+00:00", "text": "initial item"})
        + "\n"
    )

    default_yaml = {
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
            "freshness_tolerance_days": freshness_tolerance_days,
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
    providers_yaml = {
        "market_data": [{"provider_id": "sample_provider", "categories": ["spot"], "options": {}}],
        "qualitative_context": [
            {
                "provider_id": "qualitative_context_provider",
                "categories": ["news"],
                "options": {"base_dir": str(context_dir), "provenance": "synthetic"},
            }
        ],
    }
    (config_dir / "default.yaml").write_text(yaml.safe_dump(default_yaml, sort_keys=False))
    (config_dir / "providers.yaml").write_text(yaml.safe_dump(providers_yaml, sort_keys=False))


def _ops_agent_config_dict(repo_dir, **schedule_overrides):
    from ops_agent.config import OpsAgentConfig

    schedule = {
        "cycle_cadence_hours": _TINY_CADENCE_HOURS,
        "market_refresh_cadence_hours": _TINY_CADENCE_HOURS,
        "qualitative_poll_cadence_hours": _TINY_CADENCE_HOURS,
        **schedule_overrides,
    }
    return OpsAgentConfig(
        pipeline_config_path="config/default.yaml",
        llm={"api_key_env": "TEST_LLM_KEY", "model": "stub-model", "backend": "deterministic_stub"},
        operating_schedule=schedule,
        resource_budgets={"period": "daily", "max_llm_calls": 50, "max_vendor_requests": 50},
        remediation={"max_retries": 2, "backoff_seconds": 0.001},
        notifications={
            "sink": "file",
            "path": str(repo_dir / "data" / "ops_agent" / "notifications.jsonl"),
        },
    )


@pytest.fixture
def provisioned_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Researcher"], cwd=repo_dir)
    run_git(["config", "user.email", "researcher@example.com"], cwd=repo_dir)
    _write_pipeline_seed(repo_dir)
    ops_config = _ops_agent_config_dict(repo_dir)
    (repo_dir / "config" / "ops_agent.yaml").write_text(
        yaml.safe_dump(ops_config.model_dump(mode="json"), sort_keys=False)
    )
    run_git(["add", "-A"], cwd=repo_dir)
    run_git(["commit", "-m", "seed: already-provisioned operation"], cwd=repo_dir)
    return repo_dir, ops_config


def test_unprompted_ingestion_and_on_schedule_cycle_reflect_new_context(provisioned_repo):
    repo_dir, config = provisioned_repo

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        first = agent.tick()
        assert first["cycle_ran"] is True

    # Publish new material to the qualitative feed — no researcher action.
    context_dir = repo_dir / "dropzone" / "context"
    (context_dir / "news.jsonl").write_text(
        (context_dir / "news.jsonl").read_text()
        + json.dumps(
            {"source": "wire", "ts": "2026-07-19T00:00:00+00:00", "text": "fresh breaking item"}
        )
        + "\n"
    )

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        second = agent.tick()
        assert second["cycle_ran"] is True
        activity = agent.repo.read_activity()

    ingest_targets = [r["target"] for r in activity if r["action"] == "ingest"]
    assert "qualitative_feeds" in ingest_targets, (
        "the new document must be picked up unprompted on the next poll"
    )
    assert second["cycle_id"] != first["cycle_id"]


def test_no_new_material_is_logged_as_checked_and_empty(provisioned_repo):
    repo_dir, config = provisioned_repo
    with OpsAgent(config, repo_dir=repo_dir) as agent:
        agent.tick()  # first tick: state was None, poll always "due"; picks up the seed doc

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        agent.tick()  # nothing new published since; poll is due again but finds nothing
        activity = agent.repo.read_activity()

    checked_empty = [r for r in activity if r["action"] == "checked_and_empty"]
    assert any(r["target"] == "qualitative_feeds" for r in checked_empty)


def test_permanently_stale_data_escalates_rather_than_running_or_failing_silently(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    run_git(["init", "-b", "main"], cwd=repo_dir)
    run_git(["config", "user.name", "Researcher"], cwd=repo_dir)
    run_git(["config", "user.email", "researcher@example.com"], cwd=repo_dir)

    # An impossibly tight freshness tolerance guarantees StaleDataError even
    # immediately after ingestion — sample_provider's own series always end
    # "now", so no ordinary tolerance would ever trigger staleness; this
    # simulates a vendor whose feed can never satisfy the configured tolerance.
    _write_pipeline_seed(repo_dir, freshness_tolerance_days=1e-9)
    ops_config = _ops_agent_config_dict(repo_dir)
    (repo_dir / "config" / "ops_agent.yaml").write_text(
        yaml.safe_dump(ops_config.model_dump(mode="json"), sort_keys=False)
    )
    run_git(["add", "-A"], cwd=repo_dir)
    run_git(["commit", "-m", "seed: permanently-stale tolerance"], cwd=repo_dir)

    with OpsAgent(ops_config, repo_dir=repo_dir) as agent:
        result = agent.tick()
        activity = agent.repo.read_activity()

    assert result["cycle_ran"] is False
    assert result.get("escalated") is True

    remediate_attempts = [r for r in activity if r["action"] == "remediate"]
    # Every attempt re-ingests then re-checks freshness via run_cycle itself; an
    # impossible tolerance means every attempt stays stale, so all max_retries
    # attempts are exhausted (plus one final summary "exhausted" log entry).
    assert len(remediate_attempts) == ops_config.remediation.max_retries + 1
    assert all(r["outcome"] == "failed" for r in remediate_attempts), (
        "the freshness tolerance never passes, so every remediation attempt is a failure"
    )

    escalations = [r for r in activity if r["action"] == "escalate"]
    assert escalations, "remediation exhaustion must escalate, never fail silently"
    assert escalations[0]["outcome"] == "failed"
    assert "BR_POWER_SE_SPOT" in escalations[0]["reason"]

    notifications = ops_config.notifications.path.read_text().splitlines()
    assert any('"event": "escalation"' in line for line in notifications)
