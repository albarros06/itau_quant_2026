# Feature Specification: Conditional-Signal Screening & Honest Multi-Leg Evaluation

**Feature Branch**: `003-conditional-signal-screening`

**Created**: 2026-07-21

**Status**: Draft

**Input**: User description: "Make the pipeline evaluate a thesis's stated condition instead
of only unconditional drift. Today, hypotheses carry `condition` as free text that is never
executed: theses with different conditions on the same instrument produce byte-identical
screening statistics and backtests (observed live in cycle `cyc_a014b2ff1183`), so the
LLM's conditional logic — the economically meaningful part, e.g. 'long SE spot when SE
inflows run below their long-term mean' — is invisible to validation. Conditions must
become machine-executable via a closed, schema-validated vocabulary (never free-form
code), evaluated deterministically with no lookahead; screening must test the conditional
strategy's returns; backtest costs must scale with actual entries/exits; and multi-leg
theses must trade exactly the legs they declare."

## Constitution alignment (summary)

- **II (Statistical Rigor)**: the conditional strategy is screened on discovery data only,
  with the existing mandatory multiplicity control; condition evaluation must be
  lookahead-free, enforced in shared code used by both screening and backtesting.
- **III (Constrained LLM Autonomy)**: conditions are structured data in a closed
  vocabulary, schema-validated; free-form expressions or code are rejected, never repaired.
- **IV (Backtest Honesty)**: costs scale with real turnover; financing accrues only while
  in-market; a thesis may not display instruments it did not trade.
- **VII (Fail-Loud)**: conditions that are inexpressible, inactive, or under-observed are
  refused with a stated reason — never silently approximated or evaluated on tiny samples.
- **VIII (Simplicity)**: the condition vocabulary is the smallest set that covers the
  condition patterns actually emitted by the live LLM (corpus in Assumptions), not a
  general indicator language.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A thesis's condition is actually tested (Priority: P1)

A researcher reads a report entry whose hypothesis says "long `BR_POWER_SE_SPOT` when
`BR_ENA_SE_MLT` is below 80% of its long-term mean". Today the screening verdict on that
entry is numerically identical to a plain "long `BR_POWER_SE_SPOT`" thesis — the condition
changed nothing. After this feature, the LLM emits that condition in a structured,
schema-validated form; the pipeline deterministically evaluates it into a daily
in-market/out-of-market position series over the split's data (using only information
available at each decision time); screening tests the *conditional* strategy's returns
with the same block-bootstrap + multiplicity machinery; and the refinement/final backtests
hold the position only on condition-active days. Two theses that differ only in their
condition now produce different — and honest — statistics.

**Why this priority**: This is the feature's reason to exist. Without it, the pipeline can
only ever validate unconditional drift, and every promotion is a regime detection rather
than a testable signal. The observed evidence (identical statistics across differently-
conditioned theses in `cyc_a014b2ff1183`) is the defect being fixed.

**Independent Test**: On a fixture panel where instrument X's returns are positive only on
days the signal series S is below its 20-day average (and ~zero otherwise), a thesis
"long X when S < SMA(S, 20)" passes screening while the unconditional "long X" thesis
fails; swapping in an uninformative condition (e.g. S above its average) makes the
conditional thesis fail too.

**Acceptance Scenarios**:

1. **Given** two proposed theses on the same instrument and direction with different valid
   conditions, **When** the cycle screens them, **Then** their screening statistics,
   p-values, and backtest results differ according to their conditions (no shared
   unconditional shortcut), and each report entry records which condition produced which
   numbers.
2. **Given** a thesis whose condition references a different universe instrument than the
   one traded (e.g. condition on `BR_ENA_SE_MLT`, trade on `BR_POWER_SE_SPOT`), **When**
   the condition is evaluated, **Then** the signal series is read from the same
   split-scoped data as everything else — never from outside the split's date range.
3. **Given** a condition whose indicator needs an n-day warmup (e.g. a 20-day moving
   average), **When** the position series is built, **Then** the first n−1 days of the
   split are out-of-market (insufficient information), not treated as NaN or as active.
4. **Given** a signal value observable at day t, **When** the position series is built,
   **Then** the earliest day that value can influence a position is t+1 (decision at
   close, exposure from the next day) — there is no same-day lookahead.
5. **Given** an unconditional thesis (no condition / condition "always"), **When** it is
   screened and backtested, **Then** results are identical to the pre-003 pipeline's
   output for the same data and configuration.

---

### User Story 2 - Costs reflect real turnover (Priority: P2)

A conditional strategy enters and exits the market as its condition switches on and off.
The current cost model charges one flat round-trip per backtest regardless of trading
activity, which under-costs an in/out strategy that flips dozens of times and makes
condition-churning look artificially cheap. After this feature, transaction costs and
slippage are charged per entry/exit event per leg, and financing/carry accrues only on
in-market days — so a twitchy condition pays for its churn and a patient one doesn't.

**Why this priority**: Without turnover-aware costs, conditional screening (US1) would
systematically favor high-frequency flip-flopping conditions — an honesty regression
disguised as a feature. US1 must not ship without this.

**Independent Test**: Two fixture strategies with identical gross conditional returns but
2× difference in entry/exit count show ~2× difference in persisted transaction+slippage;
a strategy in-market 50% of days accrues ~half the financing of an always-in one.

**Acceptance Scenarios**:

1. **Given** a conditional backtest with E entry events and E exit events across L legs,
   **When** the result is persisted, **Then** transaction costs and slippage each equal
   the configured per-side rate × notional × (entries + exits) × legs, and the breakdown
   remains itemized next to net (Principle IV).
2. **Given** a strategy in-market for D of N split days, **When** financing/carry is
   computed, **Then** it accrues over D days, not N.
3. **Given** any backtest result, **When** it is persisted, **Then** the entry/exit counts
   and in-market day count are stored alongside the cost breakdown, so a reviewer can
   recompute the costs from the recorded activity.

---

### User Story 3 - A thesis trades exactly the legs it declares (Priority: P2)

Today a "long [`BR_POWER_SE_SPOT`, `BR_ENA_SE_MLT`, `BR_HYDRO_SE_RESERVOIR`]" thesis is
reported with all three instruments but the engine trades only the first — the report
reads like a basket while the math is a single leg (observed live: a three-instrument
thesis with results byte-identical to a one-instrument one). After this feature, a
multi-instrument long/short is an explicit equal-weight basket of every declared leg, with
per-leg costs; spread/relative-value remains first-minus-second; and every report entry
states the exact traded weights. No instrument may appear on a thesis without
participating in its results.

**Why this priority**: This is a standing Principle IV violation in the current system —
reports imply exposure that does not exist. It is independent of US1 but shares the same
strategy-evaluation seam, so it belongs in this feature.

**Independent Test**: A two-instrument long basket's returns equal the average of the two
single-instrument longs' returns (before costs), its costs equal 2× the single-leg costs,
and its report entry lists both legs at weight 0.5 each.

**Acceptance Scenarios**:

1. **Given** a long/short hypothesis with n instruments, **When** it is screened or
   backtested, **Then** strategy returns are the equal-weight (1/n each) combination of
   all n legs' returns, and costs are charged for n legs.
2. **Given** a spread/relative-value hypothesis, **When** evaluated, **Then** behavior is
   unchanged (leg1 − leg2, two legs of costs) and any instruments beyond the first two are
   rejected at schema validation rather than silently ignored.
3. **Given** any report entry with a backtest, **When** the researcher reads it, **Then**
   the entry states each traded leg and its weight, and no listed instrument is untraded.

---

### User Story 4 - Under-observed conditions are refused, and activity is visible (Priority: P3)

A condition that is active for only a handful of days in the discovery split cannot be
tested honestly — a mean over 4 days can "pass" any threshold by luck. The pipeline
refuses to screen conditions whose active-day count falls below a configured minimum,
recording the refusal and its reason on the thesis. Every screened/backtested entry
reports its activity statistics — active days per split, in-market fraction, entry/exit
counts — so a reviewer can see at a glance whether a promising number rests on 6 active
days or 600.

**Why this priority**: Guardrail for US1. It prevents conditional screening from becoming
a small-sample p-hacking machine, but only matters once US1 exists.

**Independent Test**: A fixture condition active on fewer than the configured minimum
days is marked rejected with a reason naming the observed and required counts; its
lineage proceeds to critique/refinement like any other rejection; no screening statistic
is recorded for it.

**Acceptance Scenarios**:

1. **Given** a condition active on fewer than `min_active_days` days of the discovery
   split, **When** screening runs, **Then** the thesis is rejected with a reason stating
   the active-day count and the required minimum, and no p-value is recorded for it.
2. **Given** a condition that never becomes active in the discovery split, **When**
   screening runs, **Then** the same refusal path applies (count 0), never a
   divide-by-zero, NaN statistic, or silent pass.
3. **Given** any promoted or rejected thesis with a backtest, **When** its report entry is
   rendered, **Then** active days, in-market fraction, and entry/exit counts appear per
   split alongside the existing cost breakdown.

---

### Edge Cases

- **Inexpressible conditions**: the LLM proposes a condition outside the closed vocabulary
  (e.g. referencing a qualitative forecast document, an instrument not in the universe, or
  an unsupported operator). Schema validation rejects the payload; the thesis is recorded
  `invalid_schema` with the validation detail — never repaired, approximated, or partially
  applied (Principle III). The generation prompt must state the vocabulary so this is the
  exception, not the rule.
- **Condition on the traded instrument itself** (e.g. "long spot when spot < its 60-day
  average"): allowed — the no-lookahead rule (signal at t → position at t+1) applies
  identically, and a test must prove the same-day return of a threshold-crossing day
  cannot enter the strategy's return for that day.
- **Signal series shorter than the traded series in a split** (e.g. ENA ends two days
  before CMO): the position series is defined only on days where the signal's decision
  information exists; trailing days without signal data are out-of-market, and the
  activity stats make this visible.
- **All-NaN or constant signal in a split** (e.g. the Selic target flat for the whole
  window under a change-based transform): evaluation yields a valid all-inactive series →
  refused via the min-activity gate with a stated reason, not an error.
- **Clause count/lookback bounds**: conditions with more than the maximum clauses or
  lookbacks longer than the discovery split are schema-invalid (a 400-day SMA on a
  ~1,100-day discovery split leaves too little evaluable data; bound lookbacks in config).
- **Replay of pre-003 cycles**: recorded config snapshots without condition settings must
  replay exactly as before — the unconditional path is byte-compatible and the new config
  keys have defaults matching pre-003 behavior.
- **Non-finite interaction**: conditional return streams pass through the existing
  non-finite guards (engine refusal + datastore backstop) unchanged; a condition cannot
  mask or bypass them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The thesis hypothesis schema MUST accept an optional structured `condition`
  drawn from a closed vocabulary; absent/null means unconditional (always in-market).
  Free-text conditions MUST no longer be accepted as the machine-facing field (prose
  belongs in `rationale`/`testable_claim`).
- **FR-002**: The condition vocabulary MUST consist of 1..K clauses (K configurable,
  default 3) combined with all-of semantics, where each clause compares a **subject** — a
  transform of one universe instrument's series: `level`, `sma(n)`, or `change(n)`
  (n-day difference or n-day rolling mean of daily changes) — against a **reference**:
  a constant, `sma(n)` of the same series, or `rolling_quantile(n, q)` of the same series
  (q ∈ [0,1]; q=0 expresses "n-day minimum") — using comparators `<, <=, >, >=`. Lookbacks
  MUST be bounded by configuration. This vocabulary is the smallest cover of the observed
  live LLM corpus (see Assumptions); anything outside it is schema-invalid (Principle
  III/VIII).
- **FR-003**: Condition evaluation MUST be a deterministic, pure function from
  split-scoped data + condition → daily position series, implemented once and shared by
  screening and backtesting (split integrity via shared code, per the constitution's
  Engineering Constraints). It MUST NOT fetch data, evaluate code, or access anything
  outside the provided split-scoped panel.
- **FR-004**: Evaluation MUST be lookahead-free: a clause's decision on day t may use only
  observations dated ≤ t, and the resulting exposure applies from day t+1. Indicator
  warmup days (fewer than n observations available) are out-of-market.
- **FR-005**: Screening MUST test the conditional strategy's return stream (position ×
  leg returns) on discovery-split data using the existing statistical standard
  (block bootstrap, one-sided, with mandatory multiplicity control across the wave's
  family). Conditional variants count in the same BH/Bonferroni family as any other
  thesis; there is no separate, weaker track.
- **FR-006**: A configurable `min_active_days` gate MUST reject (with a reason naming
  observed vs required counts) any thesis whose condition is active on fewer days of the
  split being evaluated; no statistic or backtest result is recorded for it. This gate
  applies to discovery (screening), refinement, and final-evaluation independently.
- **FR-007**: The cost model MUST charge transaction costs and slippage per
  entry/exit event per leg (per-side bps of notional) and accrue financing/carry only on
  in-market days. Unconditional always-in strategies therefore pay exactly one entry and
  one exit per leg, preserving comparability with pre-003 results.
- **FR-008**: Backtest results MUST persist activity statistics — in-market days, total
  split days, entry count, exit count, per split — alongside the existing cost breakdown,
  and the existing non-finite and gross-only persistence guards MUST apply unchanged.
- **FR-009**: Multi-instrument `long`/`short` hypotheses MUST be evaluated as equal-weight
  baskets of every declared leg with per-leg costs; `spread`/`relative_value` MUST require
  exactly two instruments (schema-enforced). No declared instrument may be excluded from
  evaluation. Traded legs and weights MUST be recorded on the result and shown in the
  report.
- **FR-010**: Report entries MUST render the structured condition both machine-readably
  (the validated object) and as deterministic plain language (e.g. "active when
  BR_ENA_SE_MLT < 80.0"), plus the activity statistics of FR-008. Synthetic labeling
  rules are unchanged.
- **FR-011**: The generation and critique prompts/schemas MUST instruct the LLM to emit
  conditions only in the vocabulary of FR-002 (including the list of valid instrument
  keys); schema-invalid conditions follow the existing invalid-output path — rejected and
  recorded, never repaired (Principle III).
- **FR-012**: Unconditional evaluation MUST be regression-locked: for null conditions and
  single-instrument hypotheses, screening statistics and backtest results MUST equal the
  pre-003 implementation's on identical data and configuration, and replays of pre-003
  cycles MUST be unaffected. All new configuration keys MUST default to pre-003 behavior.
- **FR-013**: All new thresholds and bounds — max clauses, max lookback, `min_active_days`
  per split — MUST live in configuration, not code (Principle VI), and MUST be recorded in
  the cycle's config snapshot for reproducibility (Principle VIII).

### Key Entities

- **SignalCondition**: the validated structured condition — clauses (subject instrument
  key, transform + lookback, comparator, reference + parameters), all-of combination.
  Stored inside the thesis hypothesis; additive to the existing schema.
- **PositionSeries**: the deterministic daily exposure series (0/1 for long/short gating;
  applied symmetrically to both legs of a spread) derived from a SignalCondition over one
  split's data. Never persisted raw — reproducible from condition + split + config.
- **ActivityStats**: in-market days, total days, entries, exits for one evaluation;
  persisted with each screening/backtest result and rendered in reports.
- **TurnoverCostBreakdown**: extension of the existing cost components with the
  event-based accounting inputs (entries, exits, legs, in-market days) that produced them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Theses that differ only in condition produce different screening statistics
  and backtest results; the byte-identical-results artifact observed in
  `cyc_a014b2ff1183` (three promotions with equal numbers) is impossible for
  differently-conditioned theses on the same data.
- **SC-002**: On the planted-signal fixture (returns positive only while the condition is
  true), the conditional thesis passes screening and the unconditional one fails; with the
  condition inverted, the conditional thesis fails. Both directions verified in the test
  suite.
- **SC-003**: A lookahead probe — a single extreme return placed on the first day a
  condition becomes decidable — never appears in the strategy's return stream for that
  day; shifting all signals forward by one day changes results. Verified by test.
- **SC-004**: Doubling a fixture condition's entry/exit count doubles persisted
  transaction+slippage; halving in-market days halves financing. Recomputing costs from
  persisted ActivityStats reproduces the persisted cost components exactly.
- **SC-005**: 100% of report entries with backtests list every traded leg with its weight,
  and no entry lists an untraded instrument (checked mechanically over a full cycle's
  report).
- **SC-006**: The unconditional regression suite shows byte-equal statistics and results
  versus the pre-003 implementation on the shared fixture, and a pre-003 cycle replays to
  its recorded shortlist unchanged.
- **SC-007**: Zero screening results exist in the datastore whose condition was active
  fewer than `min_active_days` days; every such thesis carries a refusal reason with the
  observed count.
- **SC-008**: ≥ 90% of the machine-checkable condition patterns in the observed live LLM
  corpus (Assumptions) are expressible in the FR-002 vocabulary; the remainder are
  rejected loudly at schema validation, and a live Vertex cycle completes with at least
  one validly-conditioned thesis screened end to end.

## Assumptions

- **Observed condition corpus** (from live Gemini cycles in `data/research.sqlite`,
  2026-07-21) that the FR-002 vocabulary must cover — patterns seen: "5-day SMA of daily
  returns is negative" (`change`/`sma` + `< 0`), "level below its 20-/60-day SMA"
  (`level < sma(n)`), "level declined over the past 5 days" (`change(5) < 0`), "level
  below its 90-day minimum" (`level <= rolling_quantile(90, 0)`), "below its 20th
  percentile over N days" (`level < rolling_quantile(n, 0.2)`), "ENA below median /
  below X% of long-term mean" (`level < constant`, since `*_MLT` series are already
  %-of-mean), and AND-combinations of 2–3 of these. Patterns referencing qualitative
  forecasts ("official outlook forecasts…") are not machine-checkable against the
  datastore and are intentionally out of vocabulary — the prompt directs such reasoning
  into `rationale`.
- Daily frequency only; no intraday conditions.
- The condition gates exposure on/off (position 0 or 1 signed by direction); v1 has no
  fractional sizing, no per-leg differential weighting beyond equal weight, no stop-loss
  semantics.
- No parameter search: the LLM proposes fixed lookbacks/thresholds; the pipeline never
  optimizes or sweeps condition parameters (that would explode the multiplicity family and
  invite overfitting — refinement iterations remain the only variation mechanism, already
  multiplicity-controlled per wave).
- Existing screening method (block bootstrap) and multiplicity options are reused
  unchanged; this feature changes *what* return stream is tested, not *how*.
- Data sources are unchanged (no new providers required); conditions may reference any
  universe instrument, which is the point of having EAR/ENA series alongside prices.
- Out of scope: portfolio construction across theses, capital allocation, execution (no
  such path exists, per Principle III and the import-linter contract), intraday data,
  option-like payoffs, and any UI work beyond the report fields (the dashboard consumes
  reports and will pick the new fields up in a separate change).
