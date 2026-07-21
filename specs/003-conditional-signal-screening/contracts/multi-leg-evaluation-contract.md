# Contract: Multi-Leg Basket Evaluation

Extends [thesis-schema.md](../../001-auto-research-pipeline/contracts/thesis-schema.md)'s
`direction`/`instruments` rules. Implements FR-009, FR-010.

## Contract rules

1. **`long`/`short` trade every declared instrument, equal-weighted**: for
   `direction ∈ {long, short}` with `instruments = [i_1, ..., i_n]`, the strategy return on day
   *t* is `(1/n) * Σ signed_return(i_k, t)` for `k = 1..n`, where `signed_return` is the
   instrument's daily return (`long`) or its negation (`short`) — generalizing the pre-003
   single-instrument case (`n=1` reduces to exactly the old formula, byte-identical, FR-012). No
   instrument in `instruments` may be excluded from this sum.
2. **`spread`/`relative_value` require exactly two instruments**: `len(instruments) == 2`
   enforced at schema validation (`generation/schemas.py::validate_draft`), tightened from the
   pre-003 "at least two" check. A third instrument is a validation failure
   (`invalid_schema`), never silently dropped. The return formula is unchanged:
   `return(i_1, t) - return(i_2, t)`.
3. **Per-leg costs scale with leg count**: `n_legs` passed into `CostModel.compute`
   ([turnover-cost-contract.md](./turnover-cost-contract.md)) equals `len(instruments)` for
   `long`/`short` (was implicitly `1` pre-003) and stays `2` for `spread`/`relative_value`
   (unchanged) — a basket of *n* legs pays *n* legs' worth of transaction costs and slippage.
4. **Traded weights are computed, not stored**: no new persisted field carries per-leg weights.
   Report rendering (FR-010) derives `weight = 1/n` for each `long`/`short` leg and `+1.0`/`-1.0`
   for the two `spread`/`relative_value` legs directly from the already-persisted
   `hypothesis.instruments`/`hypothesis.direction` at render time.
5. **No declared instrument is untraded**: this contract's rule 1 makes "listed but not traded"
   structurally impossible for `long`/`short` (every instrument is summed) and rule 2 makes a
   third `spread` instrument a validation failure rather than a silently-ignored extra —
   together these close the gap observed live (`cyc_a014b2ff1183`: a 3-instrument `long` thesis
   whose backtest matched a 1-instrument thesis's numbers exactly, because only
   `instruments[0]` was traded pre-003).
