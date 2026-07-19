"""US1 end-to-end: credentials -> bootstrap proposals -> approve -> tick ->
completed cycle -> shortlist (spec.md User Story 1, Acceptance Scenarios 1-4).
"""

from __future__ import annotations

import pytest
import yaml

from energy_research.config.settings import load_config
from ops_agent.agent import OpsAgent
from ops_agent.proposals.git_store import AGENT_GIT_IDENTITY_MARKER, GitIdentityError
from tests.integration.conftest import run_git


def test_bootstrap_produces_provisioning_proposals(ops_agent_repo):
    repo_dir, config = ops_agent_repo
    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()

    assert proposals, "bootstrap must produce at least one provisioning proposal"
    proposal = proposals[0]
    assert proposal.status == "proposed"
    assert proposal.rationale.strip()
    assert set(proposal.target_files) <= {"config/default.yaml", "config/providers.yaml"}

    # The proposal branch exists but has zero effect on the operating branch —
    # the working tree on disk is untouched until merge (proposal-lifecycle.md rule 2).
    on_disk = yaml.safe_load((repo_dir / "config" / "default.yaml").read_text())
    assert len(on_disk["instrument_universe"]) == 1, "pending proposal must not touch disk"

    diff = run_git(["diff", "main", proposal.branch_name], cwd=repo_dir)
    assert diff.strip(), "the proposal branch must carry a human-readable, diffable change"


def test_scenario_credentials_to_shortlist_with_zero_hand_written_config(ops_agent_repo):
    repo_dir, config = ops_agent_repo

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        assert proposals

        for proposal in proposals:
            approved = agent.git_store.approve(proposal.id)
            assert approved.status in ("approved", "edited_and_approved")
            assert approved.applied_commit_sha
            assert approved.decided_by  # attributable to a real git identity (FR-012)

    # Discovery-drafted instrument universe now on disk — never hand-written by
    # the researcher (spec Independent Test).
    pipeline_config = load_config(repo_dir / "config" / "default.yaml")
    assert len(pipeline_config.instrument_universe) > 1, (
        "approved proposal must have expanded the seed's single instrument"
    )
    provider_ids = {p.provider_id for p in pipeline_config.providers.market_data}
    assert "sample_provider" in provider_ids

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        result = agent.tick()
        assert result["cycle_ran"] is True
        assert result["report_path"].exists()

        activity = agent.repo.read_activity()
    actions = {row["action"] for row in activity}
    assert "cycle_trigger" in actions
    assert "notify_shortlist" in actions

    notifications_path = config.notifications.path
    assert notifications_path.exists()
    lines = notifications_path.read_text().splitlines()
    assert any('"event": "shortlist"' in line for line in lines)


def test_credential_failure_does_not_block_other_vendors(ops_agent_repo):
    repo_dir, config = ops_agent_repo
    providers_path = repo_dir / "config" / "providers.yaml"
    providers_raw = yaml.safe_load(providers_path.read_text())
    providers_raw["market_data"].append(
        {
            "provider_id": "secondary_market_provider",
            "categories": ["spot"],
            "options": {
                "base_dir": str(repo_dir / "no-such-dropzone"),
                "api_key_env": "MISSING_SECONDARY_CREDENTIAL",
            },
        }
    )
    providers_path.write_text(yaml.safe_dump(providers_raw, sort_keys=False))
    run_git(["commit", "-am", "add a misconfigured second vendor"], cwd=repo_dir)

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        activity = agent.repo.read_activity()

    credential_errors = [r for r in activity if r["action"] == "credential_error"]
    assert any(r["target"] == "secondary_market_provider" for r in credential_errors)
    assert any(r["outcome"] == "failed" for r in credential_errors)

    # sample_provider still produced a proposal despite the other vendor's failure.
    assert any(p.rationale for p in proposals)
    discover_ok = [r for r in activity if r["action"] == "discover" and r["outcome"] == "ok"]
    assert any(r["target"] == "sample_provider" for r in discover_ok)


def test_approve_and_reject_refuse_under_the_agents_own_git_identity(ops_agent_repo):
    repo_dir, config = ops_agent_repo
    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        proposal_id = proposals[0].id

    run_git(["config", "user.name", AGENT_GIT_IDENTITY_MARKER], cwd=repo_dir)
    try:
        with OpsAgent(config, repo_dir=repo_dir) as agent:
            with pytest.raises(GitIdentityError):
                agent.git_store.approve(proposal_id)
            with pytest.raises(GitIdentityError):
                agent.git_store.reject(proposal_id)
    finally:
        run_git(["config", "user.name", "Researcher"], cwd=repo_dir)
