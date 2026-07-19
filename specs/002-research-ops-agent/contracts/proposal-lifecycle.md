# Contract: Proposal Lifecycle (Git-Based Change Control)

Implements FR-011–FR-013, FR-015, and the Edge Cases "Pending proposal at cycle time" and
"Researcher unavailable for approvals."

## Lifecycle

```text
   propose                approve (human `git merge`)
proposed ─────────────► approved ──────────────────────► applied
   │                        ▲
   │  (human edits          │ edited_and_approved
   │   the branch,          │ (human commits changes on the
   │   then merges)         │  branch before merging)
   │                        │
   └──────────► rejected (human leaves branch unmerged;
                 `research-ops-agent reject <id>` records it)
```

`proposed` and `edited_and_approved` are not distinct storage states — `edited_and_approved` is
just `approved` where the merge commit's tree differs from the proposal branch's original tip
(i.e., the human committed changes before merging). Both satisfy FR-004 ("researcher MUST be able
to edit a proposal before approving it").

## Contract rules

1. **Every proposal is a git branch, not a database row with a diff column.** The branch
   `ops-proposal/<slug>-<id[:8]>` is created from the operating branch's current tip
   (`base_commit_sha`) and contains one or more commits touching only `config/default.yaml` and/
   or `config/providers.yaml`. The commit message body is the rationale (human-readable per
   FR-011). The `proposals` table row (data-model.md) is an index for status/listing only — the
   diff a reviewer sees is always `git diff <base_commit_sha>..<branch_name>`, computed live.
2. **No proposal has effect until merged into the operating branch.** 001's `load_config` reads
   `config/default.yaml`/`config/providers.yaml` from the working tree checked out on the
   operating branch at the moment `ingest`/`run_cycle` runs. A proposal branch existing,
   however long it sits unreviewed, changes nothing on disk on the operating branch — this is a
   property of git itself (an unmerged branch doesn't touch other branches' working trees), not
   application logic that could have a bug. Proposals queue indefinitely and never auto-approve
   (spec Assumption) because nothing in `ops_agent` ever merges.
3. **The agent cannot self-approve — structurally.** The scheduled `tick` process's git
   credential (deploy key / token, documented in quickstart.md) is provisioned with permission to
   create and push `ops-proposal/*` branches only; it has no write/merge permission on the
   operating branch, at the git-hosting or filesystem-permission level. `research-ops-agent
   approve|reject` — the only code that touches proposal status — MUST refuse to run under the
   scheduled agent's own identity (checked via a distinct local config/identity marker) and is
   documented as an interactively-run, human-invoked command only.
4. **Approval decision is read from git, not entered by hand.** `research-ops-agent approve <id>`
   performs the merge and then reads the resulting merge commit's author/committer identity and
   timestamp to populate `proposals.decided_by`/`decided_at`/`applied_commit_sha` — there is no
   separate "who approved this" text field a human fills in, so the record cannot be misattributed
   or backdated independent of git's own history.
5. **Rejection is durable and non-destructive.** `reject` sets `status="rejected"` and
   `decided_by`/`decided_at` from the local git identity running the command; the branch is left
   in place (not deleted) so the rejected proposal remains inspectable.
6. **Reconstructability.** `git log --all --grep=<proposal-id>` (or the branch name itself)
   recovers the full proposal, independent of `ops_agent.sqlite`'s survival — the store is an
   index for convenience, git is the source of truth, satisfying FR-015's "MUST remain
   reconstructable afterward" even if the SQLite file were lost.
