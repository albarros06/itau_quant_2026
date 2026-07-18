# Feature Specification: Automated Trading-Idea Research Pipeline

**Feature Branch**: `001-auto-research-pipeline`

**Created**: 2026-07-18

**Status**: Draft

**Input**: User description: "Build a system that automatically researches trading ideas for Brazilian energy markets and derivatives, end to end, with minimal manual input."

## Clarifications

### Session 2026-07-18

- Q: When refinement produces an improved thesis, does it get a fresh one-shot final-evaluation
  budget or draw on the original's? → A: Each refined variant is a distinct thesis, but the entire
  refinement lineage shares ONE final-evaluation entitlement (the final evaluation period is spent
  once per lineage, not once per variant).
- Q: When in the pipeline is the one-shot final-evaluation period consumed? → A: Once per lineage,
  at the end — after the refinement loop converges/exhausts, the single best variant is run on the
  final period exactly once as the promotion decision; all loop backtests use refinement data only.
- Q: What does the "bounded number of cycles" bound? → A: Both — a configurable per-lineage
  refinement-depth cap AND a configurable per-run cap on the number of lineages/iterations launched
  (the latter also bounds independent final-evaluation draws per run).
- Q: Must the system account for multiple comparisons across theses when judging evidence/promotion?
  → A: Yes, mandatory — the system MUST apply multiplicity control (e.g., adjusted threshold or
  false-discovery/family-wise-adjusted metric); the method and parameters are configurable but the
  protection cannot be disabled.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run an automated research cycle to a screened, backtested shortlist (Priority: P1)

A quant researcher starts a research cycle with no candidate ideas. Without intervening at
each step, the system proposes candidate trading theses grounded in current market conditions,
screens each for genuine statistical evidence on discovery-reserved history, realistically
backtests the survivors (including trading costs, slippage, and financing), and returns a
shortlist plus a report explaining every thesis it tried and why each was rejected or promoted.

**Why this priority**: This is the headline value — going from "no ideas" to a fully screened,
realistically backtested shortlist without manual intervention. If only this story ships (fed by
a maintained dataset), the researcher already has a working end-to-end research assistant.

**Independent Test**: Point the system at a labeled sample dataset, trigger one research cycle,
and verify it produces (a) a set of proposed theses each with a plain-language rationale and a
specific testable hypothesis, (b) a screening verdict with a specific reason for every thesis,
(c) realistic backtest results for survivors, and (d) a report — with no manual step between
"start" and "shortlist".

**Acceptance Scenarios**:

1. **Given** a maintained, quality-checked dataset, **When** the researcher triggers a research
   cycle, **Then** the system produces one or more candidate theses, each with a plain-language
   rationale and a specific, testable hypothesis, with no manual input required to generate them.
2. **Given** a set of proposed theses, **When** screening runs, **Then** every thesis receives an
   explicit verdict (evidence found / rejected) with a specific stated reason, and no thesis is
   dropped without a recorded reason.
3. **Given** a thesis that failed statistical screening, **When** the cycle proceeds, **Then** that
   thesis is never backtested.
4. **Given** a thesis that passed screening, **When** it is backtested, **Then** the reported
   results include transaction costs, slippage, and financing/carry — not gross P&L alone.
5. **Given** a completed cycle, **When** the researcher opens the report, **Then** they can
   determine why any given thesis was rejected or promoted without reading source code.

---

### User Story 2 - Continuous, provider-agnostic data ingestion and quality assurance (Priority: P1)

The researcher relies on the system to keep an up-to-date, quality-checked dataset covering spot
prices, forward/futures curves, hydrology/reservoir conditions, interest-rate curves, and FX
rates, sourced through a common interface so any provider can be swapped without changing analysis.
Data-quality problems are surfaced loudly and every automated correction is recorded.

**Why this priority**: Every downstream capability depends on trustworthy, current data. Without
this, screening and backtesting produce confident-looking but meaningless results. It is a
distinct, independently valuable capability (a researcher can inspect and trust the dataset even
before any thesis work).

**Independent Test**: Configure a data source, run ingestion, and verify the dataset is cleaned,
quality-checked, and marked current; then inject a data-quality defect (gap, outlier, stale feed)
and verify the system raises a visible error/warning and records any automated correction rather
than silently interpolating.

**Acceptance Scenarios**:

1. **Given** a configured data source, **When** ingestion runs, **Then** current and historical
   series for each configured data category are retrieved, cleaned, and marked with their
   freshness and provenance.
2. **Given** a provider is swapped for a different one in configuration, **When** ingestion runs,
   **Then** downstream analysis continues to work with no changes to analysis logic.
3. **Given** a data-quality problem (missing values, outliers, stale or misconfigured feed),
   **When** it is detected, **Then** the system raises a visible error or warning and does not
   silently degrade or interpolate the problem away without a record.
4. **Given** any automated correction or gap-fill is applied, **When** it happens, **Then** an
   explicit, retrievable record of the intervention is created.
5. **Given** synthetic, mock, or sample data is present, **When** it is used or displayed anywhere,
   **Then** it is clearly labeled as synthetic.

---

### User Story 3 - Bounded iterative critique-and-improve (Priority: P2)

When theses are rejected or underperform, the researcher wants the system to automatically
critique them and generate improved or alternative ideas, repeating for a bounded, configurable
number of cycles rather than running indefinitely.

**Why this priority**: This turns a single-pass screener into a genuine research loop that
improves on its own misses, materially increasing the quality of the final shortlist. It builds
on US1 but is not required for US1 to deliver value.

**Independent Test**: Force a rejected/underperforming thesis, set the maximum cycle count to a
small number, run the loop, and verify the system produces critiques, generates revised or
alternative theses from those critiques, and terminates at the configured limit.

**Acceptance Scenarios**:

1. **Given** a rejected or underperforming thesis, **When** the iterative loop runs, **Then** the
   system produces a critique that identifies specific weaknesses.
2. **Given** a critique, **When** the next iteration runs, **Then** the system generates an
   improved or alternative thesis informed by that critique.
3. **Given** a configured maximum number of cycles, **When** that limit is reached, **Then** the
   loop stops and does not continue indefinitely.
4. **Given** the loop terminates, **When** the report is produced, **Then** it includes theses
   from every iteration, not only the final one.

---

### User Story 4 - Transparent audit of every thesis decision (Priority: P3)

A reviewing portfolio manager who did not run the cycle wants to understand and trust the
outcome: for any thesis, see its rationale and hypothesis, the evidence for or against it, why it
was rejected or promoted, and — for promoted theses — realistic final performance, all without
reading code, and reproducible from the recorded configuration.

**Why this priority**: Review and trust are essential for the output to inform real decisions, but
they layer on top of a working cycle and report rather than blocking them.

**Independent Test**: Take the artifacts from a completed cycle and, without running anything or
reading code, trace one promoted and one rejected thesis end to end (rationale → evidence →
verdict → performance); then re-run the cycle from the recorded configuration and seed and verify
the shortlist reproduces.

**Acceptance Scenarios**:

1. **Given** a completed cycle, **When** a reviewer inspects any thesis, **Then** they can see its
   rationale, hypothesis, screening evidence and verdict, and (if promoted) net-of-cost
   performance, using only the produced artifacts.
2. **Given** the recorded configuration, pinned versions, and seed for a cycle, **When** the cycle
   is re-run, **Then** it reproduces the same shortlist and verdicts.
3. **Given** any thesis, **When** a reviewer checks how its final evaluation period was used,
   **Then** they can confirm that period was consumed at most once for that thesis.

---

### Edge Cases

- **No theses proposed**: If generation yields no candidates in a cycle, the system reports an
  empty result with a stated reason rather than failing silently or hanging.
- **All theses rejected**: A cycle that promotes nothing still produces a complete report listing
  every rejected thesis and its reason.
- **Stale or unavailable data at cycle start**: If required data is missing or stale beyond a
  configured tolerance, the cycle refuses to proceed and surfaces the reason rather than analyzing
  degraded data.
- **Attempt to reuse a spent evaluation period**: If a thesis whose final evaluation period is
  already spent is submitted for another final evaluation, the system refuses and records the
  refusal.
- **Malformed automatically generated thesis**: If an auto-generated thesis does not conform to the
  required structured format, it is rejected as invalid rather than partially interpreted.
- **Conflicting or unavailable configuration**: Missing or invalid configuration surfaces a visible
  error rather than falling back to hidden defaults.
- **Generation requests an instrument or market not in configuration**: The thesis is flagged as
  out of the configured universe rather than silently analyzed against absent data.

## Requirements *(mandatory)*

### Functional Requirements

#### Data ingestion & quality

- **FR-001**: System MUST retrieve current and historical market data across all configured data
  categories (e.g., spot prices, forward/futures curves, hydrology/reservoir conditions,
  interest-rate curves, FX rates).
- **FR-002**: System MUST access every market-data source through a single common interface such
  that swapping, adding, or removing a provider requires no change to downstream analysis logic.
- **FR-003**: System MUST clean and quality-check ingested data before it is available for analysis.
- **FR-004**: System MUST raise a visible error or warning on data-quality problems and MUST NOT
  silently degrade, drop, or interpolate over problems without recording that it did so.
- **FR-005**: System MUST create an explicit, retrievable record of every automated correction,
  gap-fill, or fallback applied to data.
- **FR-006**: System MUST record the freshness and provenance of every data series and MUST treat
  data staler than a configured tolerance as unfit for a research cycle.
- **FR-007**: System MUST clearly label synthetic, mock, or sample data as such everywhere it is
  stored, used, or displayed, with no path by which synthetic results can be mistaken for real.

#### Thesis generation

- **FR-008**: System MUST automatically propose candidate trading theses grounded in current market
  conditions and qualitative context (e.g., news, hydrology outlook, macro regime), with minimal
  manual input.
- **FR-009**: Each proposed thesis MUST include a plain-language rationale and a specific, testable
  hypothesis.
- **FR-010**: Automatically generated theses MUST be produced as structured, schema-validated
  records only — never as free-form executable code and never directly executed.
- **FR-011**: A generated thesis that fails structure/schema validation MUST be rejected as invalid
  rather than partially interpreted or silently repaired and used.
- **FR-012**: The system MUST have no capability to place orders, commit capital, or connect to a
  broker or execution venue (see Out of Scope).

#### Statistical screening

- **FR-013**: System MUST screen every proposed thesis for genuine statistical evidence before it
  is backtested.
- **FR-014**: Screening MUST use only historical data reserved for discovery, keeping discovery,
  refinement, and final-evaluation data strictly separated.
- **FR-015**: A thesis that fails screening MUST be rejected with a clear, specific, recorded reason
  and MUST NOT be backtested; no thesis may be dropped without a recorded reason.
- **FR-016**: The statistical evidence standard used for screening MUST be configurable, not
  hardcoded.
- **FR-030** *(added via Clarification Q4; numbered after FR-016 in insertion order, not document
  position — it belongs conceptually to Statistical Screening alongside FR-013–FR-016)*: The
  system MUST account for multiple comparisons when judging statistical evidence and promotion
  across the many theses/lineages evaluated in a run (e.g., a multiplicity-adjusted threshold or a
  false-discovery / family-wise-adjusted metric), so that promotion is not inflated by testing many
  ideas. The specific correction method and its parameters MUST be configurable, but the
  multiplicity control MUST NOT be disable-able.

#### Backtesting

- **FR-017**: System MUST backtest surviving theses with realistic assumptions including transaction
  costs, slippage, and financing/carry, and MUST report net performance inclusive of these costs
  rather than gross P&L alone.
- **FR-018**: Backtesting MUST maintain a strict separation between the data used to discover an
  idea, the data used to refine it, and a final evaluation period. All backtests performed during
  the refinement loop MUST use refinement data only; no refinement or variant-selection decision
  may read the final-evaluation period. (See FR-019 for the exact once-per-lineage timing and
  enforcement of the final-evaluation period itself.)
- **FR-019**: The final evaluation period MUST be used at most once per thesis **lineage** (a thesis
  and all improved/alternative variants derived from it through refinement share a single
  final-evaluation entitlement). The system MUST track and enforce this "used-once-per-lineage"
  constraint, refusing and recording any attempted reuse by any variant in the lineage.

#### Iterative refinement

- **FR-020**: System MUST automatically critique rejected or underperforming theses, identifying
  specific weaknesses.
- **FR-021**: System MUST use those critiques to generate improved or alternative theses.
- **FR-022**: The refinement loop MUST be bounded by two configurable limits and MUST terminate
  rather than running indefinitely: (a) a per-lineage refinement-depth cap limiting how many
  improvement attempts a single lineage may undergo, and (b) a per-run cap limiting how many
  lineages/iterations a research cycle may launch (which also bounds the number of independent
  final-evaluation draws per run).

#### Reporting & transparency

- **FR-023**: At the end of each research cycle, System MUST produce a report listing every thesis
  tried, whether it was rejected or promoted, and the specific reason.
- **FR-024**: For every promoted thesis, the report MUST include its realistic, net-of-cost final
  performance.
- **FR-025**: The report MUST be understandable — a reviewer MUST be able to determine why any
  thesis was accepted or rejected without reading source code.
- **FR-026**: The report MUST include theses from all iterations of the refinement loop, not only
  the final iteration.

#### Configuration & reproducibility

- **FR-027**: Market- and provider-specific values (e.g., instruments/tickers, tenors, thresholds,
  risk limits) MUST live in configuration, not in code.
- **FR-028**: Every research run MUST be reproducible from its recorded configuration plus pinned
  versions and fixed seeds alone, producing the same shortlist and verdicts.
- **FR-029**: System MUST record, for each cycle, the configuration snapshot and seed used, so a run
  can be reproduced and audited later.

### Key Entities *(include if feature involves data)*

- **Data Series**: A time-ordered set of values for one market data category from a source; carries
  freshness, provenance, and a real/synthetic label.
- **Data Quality Record**: A recorded data-quality issue or automated intervention (gap-fill,
  correction, fallback), with what happened and why.
- **Trading Thesis**: A candidate idea with a plain-language rationale, a specific testable
  hypothesis, provenance (which cycle/iteration produced it), a lineage reference (the parent
  thesis it was refined from, if any) identifying its refinement family, and a lifecycle status.
- **Thesis Lineage**: A thesis and all improved/alternative variants derived from it through
  refinement; holds the single shared final-evaluation entitlement (spent-once at the lineage level).
- **Screening Result**: The evidence and verdict for a thesis (evidence found / rejected) with a
  specific reason, tied to discovery-only data.
- **Data Split Allocation**: The discovery / refinement / final-evaluation partitioning, including
  whether the final-evaluation period has been spent for a given thesis lineage.
- **Backtest Result**: Realistic performance for a thesis, including the breakdown of transaction
  costs, slippage, and financing/carry.
- **Critique**: An assessment of a rejected or underperforming thesis identifying specific
  weaknesses, feeding the next iteration.
- **Research Cycle**: One end-to-end run, including its bounded iterations, configuration snapshot,
  and seed.
- **Research Report**: The end-of-cycle artifact summarizing every thesis tried, verdicts, reasons,
  and net-of-cost performance for promoted theses.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A researcher can go from "no ideas" to a screened, realistically backtested shortlist
  in a single cycle with zero manual steps between triggering the cycle and receiving the report.
- **SC-002**: 100% of theses that do not advance carry a specific, recorded rejection reason (no
  silently dropped theses).
- **SC-003**: 100% of theses reaching backtest have first passed statistical screening on
  discovery-only data (no thesis is backtested without evidence).
- **SC-004**: 100% of backtest results presented include transaction costs, slippage, and
  financing/carry (no gross-only headline results).
- **SC-005**: 100% of theses have their final evaluation period consumed at most once, verifiable
  from the recorded artifacts.
- **SC-006**: 100% of detected data-quality issues are surfaced and recorded; none are silently
  interpolated away.
- **SC-007**: Every refinement loop terminates within its configured maximum number of cycles
  (0 non-terminating runs).
- **SC-008**: A reviewer who did not run the cycle can correctly explain why any selected thesis was
  accepted or rejected using only the report, within 5 minutes and without reading code.
- **SC-009**: Re-running a cycle from its recorded configuration and seed reproduces the same
  shortlist and verdicts.
- **SC-010**: Swapping a data provider in configuration requires zero changes to analysis logic and
  the pipeline still completes a cycle successfully.
- **SC-011**: 100% of runs apply an active multiplicity control when judging evidence/promotion
  across theses; no run reports promotions on an unadjusted, per-thesis basis alone.

## Assumptions

- **Research cycles are triggered on demand** by the researcher (and may additionally be scheduled),
  while data ingestion refreshes on a configurable schedule and on demand before a cycle. This spec
  does not mandate a specific cadence.
- **The system persists a thesis history** across runs so that the "final evaluation used at most
  once per thesis" constraint can be enforced over a thesis's lifetime, not just within one run.
- **Automated thesis generation and critique are expected to be performed by a large language
  model** (per the project constitution), but requirements here are stated mechanism-agnostically;
  the binding constraints are that generated output is structured/schema-validated, inert (never
  executed), and has no capital/execution path.
- **The interactive dashboard is a separate feature.** This feature produces a structured,
  human-readable report artifact that such a dashboard (or a reviewer) can consume; the report is
  not required to be a live UI here.
- **The specific instrument universe, data providers, thresholds, tenors, and risk limits** are
  project/feature configuration and are intentionally not fixed in this spec.
- **"Genuine statistical evidence"** is defined by a configurable validity standard applied to
  discovery-only data; the exact statistical method and thresholds are a planning/config concern.
- **A quality-checked baseline dataset is available** for exercising User Story 1 independently
  (e.g., a clearly labeled sample dataset) even before continuous ingestion (US2) is complete.

## Out of Scope

- Placing live orders, submitting or routing trades.
- Committing or allocating real capital, or simulating capital allocation beyond backtesting/
  evaluation.
- Any direct connection or integration with a broker or execution venue.
- Deciding what to actually trade — a human reviews the shortlist and makes all trading decisions.
