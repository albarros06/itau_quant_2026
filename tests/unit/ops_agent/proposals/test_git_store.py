from __future__ import annotations

import subprocess

import pytest

from ops_agent.config import GitConfig
from ops_agent.proposals.git_store import GitStore
from ops_agent.store.repository import Repository


def _git(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def bare_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _git(["init", "-b", "main"], cwd=repo_dir)
    _git(["config", "user.name", "Researcher"], cwd=repo_dir)
    _git(["config", "user.email", "researcher@example.com"], cwd=repo_dir)
    (repo_dir / "config").mkdir()
    (repo_dir / "config" / "default.yaml").write_text("a: 1\n")
    _git(["add", "-A"], cwd=repo_dir)
    _git(["commit", "-m", "seed"], cwd=repo_dir)
    return repo_dir


def test_open_proposal_does_not_touch_the_working_tree_or_move_head(bare_repo, tmp_path):
    repo = Repository(tmp_path / "ops_agent.sqlite")
    try:
        store = GitStore(bare_repo, GitConfig(), repo)
        head_before = _git(["rev-parse", "HEAD"], cwd=bare_repo)
        on_disk_before = (bare_repo / "config" / "default.yaml").read_text()

        proposal = store.open_proposal(
            kind="instrument_universe",
            slug="add-fx",
            rationale="add an FX instrument",
            file_changes={"config/default.yaml": "a: 1\nb: 2\n"},
        )

        assert proposal.branch_name.startswith("ops-proposal/add-fx-")
        assert proposal.branch_name.endswith(proposal.id[:8])
        assert proposal.base_commit_sha == head_before
        assert proposal.target_files == ["config/default.yaml"]
        assert proposal.status == "proposed"

        assert _git(["rev-parse", "HEAD"], cwd=bare_repo) == head_before
        assert (bare_repo / "config" / "default.yaml").read_text() == on_disk_before

        diff = _git(["diff", "main", proposal.branch_name], cwd=bare_repo)
        assert "+b: 2" in diff
    finally:
        repo.close()


def test_open_proposal_commit_message_carries_rationale_and_evidence_ref(bare_repo, tmp_path):
    repo = Repository(tmp_path / "ops_agent.sqlite")
    try:
        store = GitStore(bare_repo, GitConfig(), repo)
        proposal = store.open_proposal(
            kind="data_source",
            slug="new-vendor",
            rationale="onboard new_vendor",
            file_changes={"config/default.yaml": "a: 1\n"},
            discovery_evidence_ref="discover:new_vendor",
        )
        message = _git(["log", "-1", "--format=%B", proposal.branch_name], cwd=bare_repo)
        assert "onboard new_vendor" in message
        assert "Discovery-Evidence-Ref: discover:new_vendor" in message
    finally:
        repo.close()
