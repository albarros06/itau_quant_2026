"""US3 end-to-end: reviewable change control and a complete audit trail
(spec.md User Story 3, Acceptance Scenarios 1-4).
"""

from __future__ import annotations

import yaml

from energy_research.config.settings import load_config
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import replay_cycle
from ops_agent.agent import OpsAgent
from ops_agent.cli import main as ops_cli_main


def _outcome_fingerprint(repo: Repository, cycle_id: str) -> list[tuple]:
    fingerprint = []
    for thesis in repo.theses_for_cycle(cycle_id):
        hyp = thesis["hypothesis"]
        screening = repo.screening_result_for(thesis["thesis_id"])
        fingerprint.append(
            (
                thesis["iteration_index"],
                tuple(hyp.get("instruments", [])),
                hyp.get("direction"),
                thesis["status"],
                None
                if screening is None
                else (screening["verdict"], round(screening["p_value"], 12)),
            )
        )
    return sorted(fingerprint)


def test_pending_proposal_has_no_effect_then_takes_effect_once_approved(ops_agent_repo):
    repo_dir, config = ops_agent_repo

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        assert proposals, "the agent must want a universe/data-source change"

        # Scenario 1: no effect before approval — config on disk is untouched.
        on_disk = yaml.safe_load((repo_dir / "config" / "default.yaml").read_text())
        assert len(on_disk["instrument_universe"]) == 1

        # A tick run against the still-unapproved config records the OLD universe
        # in its config_snapshot, not whatever the pending proposal contains.
        before = agent.tick()
        assert before["cycle_ran"] is True
        pre_approval_cycle_id = before["cycle_id"]

        for proposal in proposals:
            approved = agent.git_store.approve(proposal.id)
            assert approved.status in ("approved", "edited_and_approved")

    pipeline_repo = Repository(
        load_config(repo_dir / "config" / "default.yaml").datastore.db_path,
        load_config(repo_dir / "config" / "default.yaml").datastore.lake_dir,
    )
    try:
        pre_snapshot = pipeline_repo.get_cycle(pre_approval_cycle_id)["config_snapshot"]
        assert len(pre_snapshot["instrument_universe"]) == 1, (
            "the pending proposal must have zero effect on a cycle run before approval"
        )
    finally:
        pipeline_repo.close()

    # Scenario 2: approving takes effect, visible in the NEXT cycle's config_snapshot.
    on_disk_after = yaml.safe_load((repo_dir / "config" / "default.yaml").read_text())
    assert len(on_disk_after["instrument_universe"]) > 1

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        after = agent.tick()
        assert after["cycle_ran"] is True
        post_approval_cycle_id = after["cycle_id"]

    pipeline_repo = Repository(
        load_config(repo_dir / "config" / "default.yaml").datastore.db_path,
        load_config(repo_dir / "config" / "default.yaml").datastore.lake_dir,
    )
    try:
        post_snapshot = pipeline_repo.get_cycle(post_approval_cycle_id)["config_snapshot"]
        assert len(post_snapshot["instrument_universe"]) > 1, (
            "the approved proposal's universe must appear in the next cycle's config_snapshot"
        )
    finally:
        pipeline_repo.close()


def test_log_reconstructs_the_full_action_sequence(ops_agent_repo, capsys, monkeypatch):
    repo_dir, config = ops_agent_repo

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        for proposal in proposals:
            agent.git_store.approve(proposal.id)
        agent.tick()

    capsys.readouterr()  # discard any prior noise
    monkeypatch.chdir(repo_dir)  # research-ops-agent is invoked from the repo root
    exit_code = ops_cli_main(["--config", "config/ops_agent.yaml", "log"])
    assert exit_code == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines, "an auditor must be able to reconstruct activity from `log` alone"

    actions_seen = [line.split(None, 2)[1] for line in lines]
    assert "discover" in actions_seen
    assert "propose" in actions_seen
    assert "cycle_trigger" in actions_seen
    assert "notify_shortlist" in actions_seen
    # Chronological: timestamps (first column) are non-decreasing.
    timestamps = [line.split(None, 1)[0] for line in lines]
    assert timestamps == sorted(timestamps)


def test_replay_is_independent_of_agent_activity_before_or_after(ops_agent_repo):
    repo_dir, config = ops_agent_repo

    with OpsAgent(config, repo_dir=repo_dir) as agent:
        proposals = agent.bootstrap()
        first_tick = agent.tick()
        original_cycle_id = first_tick["cycle_id"]

        for proposal in proposals:
            agent.git_store.approve(proposal.id)
        agent.tick()  # further agent activity AFTER the cycle we're about to replay

    pipeline_config = load_config(repo_dir / "config" / "default.yaml")
    replayed = replay_cycle(pipeline_config, original_cycle_id)

    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        original_fp = _outcome_fingerprint(repo, original_cycle_id)
        replayed_fp = _outcome_fingerprint(repo, replayed.cycle_id)
    finally:
        repo.close()

    assert original_fp == replayed_fp, (
        "SC-007: replay reproduces the original cycle's results independent of any "
        "agent activity that happened before or after"
    )
