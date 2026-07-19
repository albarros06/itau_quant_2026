# Contract: Resource Budget Enforcement

Implements FR-022 and SC-010. Scope decision recorded in research.md §9.

## What counts as discretionary spend (bounded)

- Every LLM call made by `ops_agent.discovery.interpret` or `ops_agent.onboarding.draft`.
- Every vendor HTTP request made by `ops_agent.discovery.vendor_probe` (discovery calls,
  onboarding probes, ad-hoc health checks initiated by the agent outside a normal ingestion run).

## What is out of scope (not bounded by this contract)

- 001's own `generation`/`critique` LLM calls inside `run_cycle` — governed entirely by 001's
  `refinement`/`generation` config (FR-020: 001's guarantees hold unchanged).
- Routine market/qualitative fetches performed by `ingest_all` on the configured cadence — bounded
  by `operating_schedule`, not by this budget.

## Contract rules

1. **Every discretionary call goes through the guard.** `ops_agent.budget.guard(kind: "llm" |
   "vendor_request")` is the only sanctioned entry point for incrementing usage; every call site
   in `discovery/` and `onboarding/` MUST wrap its external call with it — a contract test
   statically confirms every LLM/HTTP call inside those two subpackages is reachable only through
   `guard(...)`.
2. **Exhaustion halts further discretionary activity for the period, not the whole agent.**
   Once `llm_calls_used >= max_llm_calls` (or the vendor-request equivalent), `guard` raises
   `BudgetExhausted` for any further discretionary call in that period; `agent.tick()` catches it,
   logs `action="budget_blocked"`, and skips only the discretionary step in progress — scheduled
   `ingest`/`cycle_trigger` steps for that same tick proceed normally (research.md §9).
3. **Exhaustion is a one-time, notified event per period.** The first `BudgetExhausted` in a
   period sets `resource_budget_usage.exhausted_at` and fires a `notify()` call (budget-exhaustion
   event, contracts via research.md §8); subsequent blocked attempts in the same period are still
   logged (`budget_blocked`) but do not re-notify, so a busy period produces one clear signal, not
   a flood.
4. **Counters reset only at a period boundary**, computed from `period_key` (data-model.md), never
   by a manual reset path — there is no code path that zeroes usage early, which would otherwise
   be a way to silently work around a budget.
5. **No spend without limit.** There is no "unlimited" budget value; `max_llm_calls` and
   `max_vendor_requests` are required, non-negative integers in `config/ops_agent.yaml` — a
   missing budget section is a config-validation error at startup (Constitution Principle VI: no
   hidden defaults for a required control), not an implicit "no limit."
