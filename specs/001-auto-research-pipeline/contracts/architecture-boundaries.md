# Contract: Architecture Boundaries

Enforced mechanically (import-linter or equivalent dependency-contract checker) as part of the
test suite, not just documented. A build that violates this contract MUST fail.

## Layers (low → high)

1. `config` — no dependency on any other project layer.
2. `common` — may depend on `config` only.
3. `ingestion` — may depend on `config`, `common`.
4. `cleaning` — may depend on `config`, `common`, `ingestion`.
5. `datastore` — may depend on `config`, `common`. (Not on `ingestion`/`cleaning` — it persists
   whatever `cleaning` hands it via its own write API; it does not reach back upstream.)
6. **Sibling group** (each may depend on `config`, `common`, `datastore`, and **nothing in this
   group may depend on another member of this group**):
   - `generation`
   - `screening`
   - `backtesting`
   - `critique`
   - `reporting`
7. `orchestration` — may depend on everything above.

## Rules

- **Layers contract**: a strict "higher may depend on lower, never the reverse" ordering across
  1–7 as listed.
- **Independence contract**: `generation`, `screening`, `backtesting`, `critique`, `reporting`
  MUST NOT import one another. All coordination between them happens through persisted
  `datastore` records, orchestrated by layer 7.
- **Forbidden-dependency contract**: no layer anywhere may depend on any broker/execution/order-
  placement package, because no such package exists in this project (Constitution Principle III /
  spec Out of Scope). This contract exists to make that omission structurally enforced, not just
  incidental.

## Rationale

See [research.md §1](../research.md#1-layered-architecture--boundary-enforcement). The
independence contract is what makes the train/refinement/final-evaluation split guarantees
(Principle II) and the audit trail (User Story 4) properties of the architecture rather than of
programmer discipline.
