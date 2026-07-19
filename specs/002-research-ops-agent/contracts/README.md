# Contracts

This feature has no networked API either — "contracts" here are the structural guarantees that
make autonomy trustworthy (spec User Story 3's framing) and the interfaces `ops_agent` builds
against. Each contract is what `/speckit-tasks` and `/speckit-implement` build to and what
contract tests in `tests/contract/` verify mechanically, not by review discipline.

- [ops-agent-boundary.md](./ops-agent-boundary.md) — the structural limit on the agent's reach
  (FR-019): exactly which `energy_research` entry points `ops_agent` may call, enforced by an
  import-linter independence contract plus a static reach audit.
- [proposal-lifecycle.md](./proposal-lifecycle.md) — the git-branch-based diffable proposal and
  approval contract (FR-011–FR-013, FR-015), including why the agent cannot self-approve.
- [declarative-connector.md](./declarative-connector.md) — the Data Source Descriptor shape and
  the shared connector's interpretation rules for config-only vendor onboarding (FR-016–FR-018).
- [activity-log-contract.md](./activity-log-contract.md) — the append-only audit-log contract
  (FR-014, SC-003).
- [budget-contract.md](./budget-contract.md) — what counts as discretionary agent spend and the
  exhaustion-halts-activity contract (FR-022, SC-010).
