# Phase 0 Research: Conditional-Signal Screening & Honest Multi-Leg Evaluation

Each decision below resolves one open design question raised while reading the existing
codebase (`common/signals.py`, `screening/service.py`, `backtesting/{engine,costs,service}.py`,
`generation/{schemas,llm_client}.py`, `datastore/{schema,repository}.py`,
`reporting/report_builder.py`) against the clarified spec.

## 1. Where the condition vocabulary's schema lives

**Decision**: A new `energy_research.common.conditions` module defines the `SignalCondition` /
`ConditionClause` Pydantic models (the closed vocabulary of FR-002) and a single pure function
`evaluate_condition(prices: pd.DataFrame, condition: SignalCondition | None) -> pd.Series`
(boolean position mask, lookahead-shifted). This sits in `common`, not `generation`, because
`screening` and `backtesting` both need to evaluate conditions and neither may import the other
or `generation` (architecture-boundaries.md); `common` is the only layer both may import.

**Rationale**: Mirrors the existing precedent exactly — `common/signals.py::hypothesis_returns`
is already the shared, layer-neutral function both `screening/service.py` and
`backtesting/engine.py` call directly. Condition evaluation is the same kind of pure,
split-scoped, side-effect-free transform and belongs beside it.

**Alternatives considered**: Defining the vocabulary in `generation/schemas.py` alone (where
`HypothesisDraft` lives) and having `screening`/`backtesting` import it — rejected: nothing in
`common`/`screening`/`backtesting` may import `generation` (layers contract), and duplicating the
model would violate Principle VIII (one definition, reused).

## 2. Composing conditions with existing single-leg / multi-leg return logic

**Decision**: Extend `common/signals.py::hypothesis_returns` to accept an optional
`SignalCondition`. Internally: (a) compute the equal-weight basket return series for
`long`/`short` (all declared legs, FR-009) or the spread series for `spread`/`relative_value`
(unchanged, exactly two legs) — the existing per-direction logic, generalized from
"first instrument only" to "all declared legs"; (b) if a condition is present, evaluate it via
`conditions.evaluate_condition` against the same split-scoped `prices` panel to get a 0/1 position
mask, lag it by one day (decision at close *t* → exposure from *t+1*, FR-004), and multiply it
elementwise into the leg return series *before* combining legs — inactive days contribute exactly
zero to every leg's return, not just to the combined figure, so per-leg entry/exit accounting
(needed for FR-007) stays correct even for baskets.

**Rationale**: Keeps exactly one seam (`hypothesis_returns`) as the single source of truth for
"what does this thesis's return stream look like", so screening and backtesting continue to call
one function and cannot drift apart (Principle II's "split integrity ... enforced by shared code,
not reimplemented per feature" reasoning applies equally to conditional-signal logic). The
unconditional case (`condition=None`) has the mask short-circuited to "always 1", making the
pre-003 code path byte-identical (FR-012, SC-006) — no special-casing needed downstream.

**Alternatives considered**: A separate `conditional_hypothesis_returns` function used only when a
condition is present, with the original left untouched for the unconditional path — rejected:
two functions is exactly the kind of unjustified duplication Principle VIII warns against, and it
would require every call site to branch, doubling the surface for the two paths to silently
diverge.

## 3. Position-mask mechanics (lookahead, warmup, multi-clause combination)

**Decision**: `evaluate_condition` builds each clause's subject/reference series with pandas
rolling/shift operations restricted to the split's own panel (`.rolling(n).mean()`,
`.diff(n)`, `.rolling(n).quantile(q)` — all of which are NaN for the first `n-1` rows by
construction, giving warmup-as-NaN for free). Clauses combine with elementwise boolean AND
(`&`), NaN propagating to False (`.fillna(False)`) so any clause without enough history keeps
the whole condition inactive. The final boolean series is **shifted forward by one day**
(`.shift(1)`, first day False) before being cast to a 0/1 float mask — this single shift is what
enforces "decision at *t*, exposure from *t+1*" (FR-004) for every clause uniformly, rather than
requiring each clause to reason about lookahead itself.

**Rationale**: Using pandas' own rolling/shift primitives (already a project dependency, already
used by `hypothesis_returns`'s `pct_change()`) rather than hand-rolled loops keeps the
implementation small (Principle VIII) and gives warmup-as-NaN and lookahead-as-one-shift as
structural properties of the chosen primitives, not case-by-case logic that could be gotten wrong
per clause.

**Alternatives considered**: Shifting each clause's *subject* series individually before
comparison — rejected: mathematically equivalent for single clauses but subtly wrong for
`change(n)`/`sma(n)` **references** that mix timeframes; shifting the final combined boolean
exactly once is simpler to prove correct and is what SC-003's lookahead probe test directly
checks.

## 4. Cost-model API change for turnover-aware accounting

**Decision**: `CostModel.compute` changes signature from `(n_legs, n_days, gross_exposure)` to
`(n_legs, entries, exits, in_market_days, gross_exposure)`. `traded_notional` becomes
`(entries + exits) * n_legs * gross_exposure` (replacing the hardcoded `2.0 *`), and
`financing` uses `in_market_days` in place of `n_days`. The caller (now inside
`common.signals` or `backtesting.engine`, wherever the position mask is available) computes
`entries`/`exits`/`in_market_days` from the same 0/1 mask used for returns: entries = count of
0→1 transitions, exits = count of 1→0 transitions (+1 implicit "exit" at series end if still
in-market, matching the existing "round trip" assumption for an always-in strategy), so an
unconditional thesis produces `entries=1, exits=1, in_market_days=n_days` — identical to today's
`2.0 * n_legs` traded notional and full-window financing (FR-012, SC-006).

**Rationale**: Smallest change that makes costs a function of realized activity (FR-007) while
keeping `CostBreakdown`'s three-field shape (transaction_costs/slippage/financing_carry) and the
constitution's NOT-NULL persistence guarantee untouched.

**Alternatives considered**: Charging a fixed cost per clause-active *span* rather than
per-transition — rejected: transitions (entries/exits) are the standard, unambiguous unit for
transaction-cost accounting and directly match "one round trip = one entry + one exit", the
mental model the existing `2.0 * n_legs` constant already encoded.

## 5. Where ActivityStats is persisted

**Decision — backtest results**: `other_metrics` (existing `TEXT NOT NULL DEFAULT '{}'` JSON
column on `backtest_results`) gains four new keys: `in_market_days`, `total_days`, `entries`,
`exits`. No schema change needed — this column already exists for exactly this kind of additive,
non-guaranteed metric (`sharpe`, `max_drawdown`, etc. already live there).

**Decision — screening results**: `screening_results` has **no** JSON metrics column today (only
fixed columns: `statistic_value`, `p_value`, `multiplicity_method`, `adjusted_threshold`,
`verdict`, `reason`). This feature adds one: `other_metrics TEXT NOT NULL DEFAULT '{}'`, mirroring
`backtest_results` exactly. Because `create_schema` only runs `CREATE TABLE IF NOT EXISTS`
(verified: no ALTER/migration mechanism exists anywhere in this codebase today — this is the
project's first schema change to an existing table), `create_schema` also runs one idempotent,
guarded statement: check `PRAGMA table_info(screening_results)` for the column and
`ALTER TABLE screening_results ADD COLUMN other_metrics TEXT NOT NULL DEFAULT '{}'` if absent, run
inside the same connection `create_schema` already owns. This is intentionally the minimum viable
migration primitive — one guarded ALTER, not a migrations framework — matching Principle VIII
("abstractions only in response to a demonstrated, present need"); a second future column would
be the trigger to reconsider that decision, not this one.

**Rationale**: Reuses the established `other_metrics` JSON-blob convention for anything
additional-but-not-guaranteed rather than inventing a second mechanism; the one required ALTER is
scoped, tested, and does not touch any other table.

**Alternatives considered**: Encoding ActivityStats into the existing `reason` free-text field —
rejected: `reason` is prose for a human reader (already demonstrated by existing p-value/threshold
sentences); machine-checkable stats belong in structured JSON so `tests/dashboard` and future
tooling can read them without parsing sentences, per Principle VII's "retrievable record" language.

## 6. Multi-leg basket weighting and schema enforcement

**Decision**: `HypothesisDraft` (generation/schemas.py) keeps `direction` and `instruments` as
today, but validation (`validate_draft`) enforces exactly what `hypothesis_returns` now does:
`spread`/`relative_value` require **exactly** 2 instruments (today's check is "at least two" —
tightened to "exactly two", closing the silent-ignore gap FR-009 identifies), while
`long`/`short` accept 1..N with equal weight `1/N` implied by the instrument count — no explicit
weight field needed in the schema (Principle VIII: the simplest representation that satisfies
FR-009 is "count of instruments", not a parallel weights array the LLM would have to keep
consistent).

**Rationale**: Equal weight is fully determined by `len(instruments)`, so no new schema field is
needed at all — only a tightened validation rule. The report (FR-010) computes and displays
`weight = 1/len(instruments)` per leg at render time from the same hypothesis object already
persisted.

**Alternatives considered**: An explicit `weights: list[float]` field summing to 1 — rejected:
gives the LLM a way to under/over-specify weights inconsistently with `instruments`' length,
which schema validation would then have to police anyway; equal-weight-by-count has no such
failure mode and matches the spec's explicit "equal-weight (1/n each)" requirement (FR-009).

## 7. Config surface

**Decision**: A new `ConditionalScreeningConfig` section under `PipelineConfig`:
```yaml
conditional_screening:
  max_clauses: 3
  max_lookback_days: 90
  min_active_days:
    discovery: 100
    refinement: 60
    final_evaluation: 30
```
Defaults match the Clarifications session exactly. `max_lookback_days` bounds every clause's `n`
(subject and reference lookbacks alike) at schema-validation time in `generation/schemas.py`
(Edge Case: "Clause count/lookback bounds"); `min_active_days` is read per split by whichever
service is evaluating that split (`screening.ScreeningService` for discovery,
`backtesting.BacktestingService` for refinement/final).

**Rationale**: One new, clearly-scoped config section (Principle VI) rather than overloading
`ScreeningConfig`/`BacktestingConfig`, since these bounds apply to condition evaluation
specifically and are meaningful even to unconditional theses only in the degenerate sense (they
never trigger the gate). Recorded verbatim in the cycle's `config_snapshot` for reproducibility
(FR-013, Principle VIII) with zero extra code — `PipelineConfig.snapshot()` already serializes the
whole model.

## 8. Generation/critique prompt changes

**Decision**: `generation/llm_client.py`'s `_SYSTEM` prompt gains one paragraph stating the
condition vocabulary (subjects, transforms, references, comparators, max clauses, max lookback)
and the valid instrument-key list (already passed as `universe_keys`); `HypothesisDraft.condition`
becomes `SignalCondition | None` so `TradingThesisDraft.model_json_schema()` (already how the
schema reaches the LLM, `common/llm.py`'s `_inline_refs`/`_strip_unsupported` already handle
nested schemas) automatically carries the new structure to the provider's structured-output mode
— no separate schema-string maintenance. `critique/service.py`'s prompt gets the equivalent
addition so refined theses can propose new/adjusted conditions.

**Rationale**: The schema is already the single source of truth handed to the LLM
(`TradingThesisDraft.model_json_schema()`); extending the Pydantic model is sufficient, and the
existing `_inline_refs` schema-flattening (written for exactly this "Gemini rejects `$defs`/`$ref`"
reason) already handles the additional nesting `SignalCondition` introduces.

**Alternatives considered**: A separate free-text "condition guidance" prompt block with no schema
enforcement — rejected: this is exactly the free-form-condition status quo the feature exists to
fix; the vocabulary must be schema-enforced (Principle III), not merely prompted.

## 9. Regression-locking the unconditional path

**Decision**: `tests/unit/common/test_signals_conditions.py` (new) includes a byte-equality
regression test: for a fixture panel and every existing direction, `hypothesis_returns(prices,
instruments, direction, condition=None)` must produce results identical (via `np.array_equal`, no
tolerance) to a frozen pre-003 reference computed once from the current implementation before any
change lands. The same fixture drives an equivalent screening-statistic and backtest-cost
regression check.

**Rationale**: This is the mechanical enforcement of SC-006 and FR-012 — "regression-locked" is
otherwise just a sentence in the spec; freezing the pre-change reference output as a test fixture
is what makes it a gate a future change cannot silently break.
