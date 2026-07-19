"""Git-branch-based proposal lifecycle (contracts/proposal-lifecycle.md, research.md §7).

Every proposal is a git branch, not a database row with a diff column
(rule 1). ``open_proposal`` writes the branch via low-level git plumbing
(``read-tree``/``hash-object``/``write-tree``/``commit-tree``/``update-ref``) so it
never touches the calling process's working tree or index — a pending proposal
branch has zero effect on the operating branch, which is a property of git itself
(rule 2), not application logic that could have a bug.

``approve``/``reject`` are the only functions that touch proposal status, and both
refuse to run under the scheduled agent's own git identity (rule 3) — the agent has
no code path, credentialed or not, to move a proposal to ``approved``.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ops_agent.config import GitConfig
from ops_agent.proposals.models import ProposalKind, ProvisioningProposal
from ops_agent.store.repository import Repository

# Deployment convention (quickstart.md §0): the scheduled agent's cron job sets
# GIT_AUTHOR_NAME/GIT_COMMITTER_NAME to this value and holds no merge credential on
# the operating branch. approve()/reject() refuse to run under it as a defense in
# depth on top of that credential-level guarantee (contracts/proposal-lifecycle.md
# rule 3).
AGENT_GIT_IDENTITY_MARKER = "ops-agent"


class GitIdentityError(RuntimeError):
    """approve()/reject() were invoked under the scheduled agent's own git identity."""


def _git(
    args: list[str], cwd: Path, env: dict[str, str] | None = None, input_text: str | None = None
) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=env, input=input_text
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


class GitStore:
    def __init__(self, repo_dir: str | Path, config: GitConfig, repo: Repository):
        self._repo_dir = Path(repo_dir)
        self._config = config
        self._repo = repo

    def _current_git_identity(self) -> tuple[str, str]:
        name = _git(["config", "user.name"], cwd=self._repo_dir)
        email = _git(["config", "user.email"], cwd=self._repo_dir)
        return name, email

    def _refuse_if_agent_identity(self, action: str) -> None:
        name, _ = self._current_git_identity()
        if name == AGENT_GIT_IDENTITY_MARKER:
            raise GitIdentityError(
                f"{action} must be run interactively by the researcher's own git identity, "
                f"never the scheduled agent's ({AGENT_GIT_IDENTITY_MARKER!r}) "
                "(contracts/proposal-lifecycle.md rule 3)"
            )

    def open_proposal(
        self,
        *,
        kind: ProposalKind,
        slug: str,
        rationale: str,
        file_changes: dict[str, str],
        discovery_evidence_ref: str | None = None,
    ) -> ProvisioningProposal:
        """``file_changes``: repo-relative path -> full new file content.

        Writes one commit to a new ``ops-proposal/*`` branch via git plumbing —
        never checks anything out, never touches the caller's working tree/index.
        """
        base_commit_sha = _git(["rev-parse", self._config.operating_branch], cwd=self._repo_dir)
        proposal_id = uuid.uuid4().hex
        branch_name = f"{self._config.proposal_branch_prefix}{slug}-{proposal_id[:8]}"

        with tempfile.TemporaryDirectory() as tmp:
            index_path = Path(tmp) / "index"
            env = {**os.environ, "GIT_INDEX_FILE": str(index_path)}
            _git(["read-tree", base_commit_sha], cwd=self._repo_dir, env=env)
            for path, content in file_changes.items():
                blob_sha = _git(
                    ["hash-object", "-w", "--stdin"],
                    cwd=self._repo_dir,
                    env=env,
                    input_text=content,
                )
                _git(
                    ["update-index", "--add", "--cacheinfo", f"100644,{blob_sha},{path}"],
                    cwd=self._repo_dir,
                    env=env,
                )
            tree_sha = _git(["write-tree"], cwd=self._repo_dir, env=env)

        message = f"{kind}: {slug}\n\n{rationale}"
        if discovery_evidence_ref:
            message += f"\n\nDiscovery-Evidence-Ref: {discovery_evidence_ref}"
        commit_sha = _git(
            ["commit-tree", tree_sha, "-p", base_commit_sha, "-m", message], cwd=self._repo_dir
        )
        _git(["update-ref", f"refs/heads/{branch_name}", commit_sha], cwd=self._repo_dir)

        self._repo.create_proposal(
            id=proposal_id,
            kind=kind,
            branch_name=branch_name,
            base_commit_sha=base_commit_sha,
            target_files=list(file_changes.keys()),
            rationale=rationale,
            discovery_evidence_ref=discovery_evidence_ref,
        )
        return ProvisioningProposal.model_validate(self._repo.get_proposal(proposal_id))

    def approve(self, proposal_id: str) -> ProvisioningProposal:
        """Performs the merge into the operating branch as the current (human)
        git identity, then reads decided_by/decided_at/applied_commit_sha from
        the resulting merge commit's own metadata — never entered by hand
        (contracts/proposal-lifecycle.md rule 4)."""
        self._refuse_if_agent_identity("approve")
        row = self._repo.get_proposal(proposal_id)
        if row is None:
            raise LookupError(f"no proposal {proposal_id!r}")
        branch_name, base_commit_sha = row["branch_name"], row["base_commit_sha"]

        # The agent's open_proposal() always leaves exactly one commit ahead of
        # base_commit_sha; more than one means the human committed changes on the
        # branch before merging (edited_and_approved, FR-004).
        commit_count = int(
            _git(["rev-list", "--count", f"{base_commit_sha}..{branch_name}"], cwd=self._repo_dir)
        )
        edited = commit_count > 1

        _git(["checkout", self._config.operating_branch], cwd=self._repo_dir)
        _git(
            ["merge", "--no-ff", branch_name, "-m", f"Merge proposal {proposal_id}"],
            cwd=self._repo_dir,
        )
        merge_commit_sha = _git(["rev-parse", "HEAD"], cwd=self._repo_dir)
        decided_by = _git(["log", "-1", "--format=%an <%ae>", merge_commit_sha], cwd=self._repo_dir)
        decided_at = _git(["log", "-1", "--format=%aI", merge_commit_sha], cwd=self._repo_dir)

        status = "edited_and_approved" if edited else "approved"
        self._repo.decide_proposal(
            proposal_id,
            status=status,
            decided_by=decided_by,
            decided_at=decided_at,
            applied_commit_sha=merge_commit_sha,
        )
        return ProvisioningProposal.model_validate(self._repo.get_proposal(proposal_id))

    def reject(self, proposal_id: str) -> ProvisioningProposal:
        """Durable and non-destructive: the branch is left in place, not deleted
        (contracts/proposal-lifecycle.md rule 5)."""
        self._refuse_if_agent_identity("reject")
        row = self._repo.get_proposal(proposal_id)
        if row is None:
            raise LookupError(f"no proposal {proposal_id!r}")
        name, email = self._current_git_identity()
        self._repo.decide_proposal(
            proposal_id,
            status="rejected",
            decided_by=f"{name} <{email}>",
            decided_at=datetime.now(UTC).isoformat(),
            applied_commit_sha=None,
        )
        return ProvisioningProposal.model_validate(self._repo.get_proposal(proposal_id))
