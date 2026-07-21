# Dashboard Design Notes — from-design vs. adapted-for-Streamlit

This dashboard reproduces the visual language of the **"BR Energy Quant Dashboard"**
Claude Design project (`claude.ai/design/p/00d124e9-35b6-498c-aca9-b6af4e9526ab`),
imported via the `DesignSync` MCP tool. It is a **read-only consumer** of the
research pipeline's persisted output (SQLite datastore + Parquet lake + per-cycle
reports) — it adds no data source and never implies data it does not have.

This document records, per the brief, what was reproduced faithfully from the
design, what was adapted because Streamlit requires it, and where the design asked
for something the real data cannot honestly supply (surfaced, not worked around).

---

## 1. Reproduced verbatim from the design

| Element | Source in design | Where reproduced |
|---|---|---|
| Colour tokens (light + dark) | `THEME.light` / `THEME.dark` | `utils/theme.py` `LIGHT` / `DARK` — exact hex values |
| Mono numerals w/ `tabular-nums`, system sans for prose | `MONO` / `SANS` | `utils/theme.py`; `.num` class on every number |
| Status colour coding — promoted=green, rejected=red, proposed/pending=amber | design status palette | `utils/format.status_bucket` + `theme.status_pill_style` |
| Card radius 20px mobile / 14px tablet+ | `renderVals()` | `theme.build_css` media queries |
| Status pills (6–7px), risk/filter chips (20px), metric tiles | design components | `theme.build_css`, `components/cards.py` |
| Four screens: Market Overview · Thesis Browser · Thesis Detail · Cycle History | design screen set | `components/*.py` |
| Responsive intent: 1-col mobile / 2-col tablet / 3-col desktop; metrics 2→5 col; master-detail on desktop | `gridCols = mobile?1:tablet?2:3` | flex-wrap columns + CSS-grid tiles (see §2) |
| Fixed bottom tab bar (mobile); side-nav (desktop) | design nav | `components/nav.py` (see §2) |
| Cost waterfall, phase-coloured equity line, list sparklines | design charts | `utils/charts.py` (Altair) |
| Filter/sort "sheet"; accordions (narrative/validation/backtest/risk) | design interactions | `thesis_browser._filter_sheet`, `thesis_detail` expanders |

Both light and dark themes are implemented; the sidebar **Dark mode** toggle swaps
the token set (`theme.get_theme`).

---

## 2. Adapted because Streamlit requires it (design intent preserved)

Streamlit has no native equivalent for several design elements. Each is
reproduced with custom CSS via `st.markdown(unsafe_allow_html=True)` rather than
dropped silently:

- **Fixed bottom tab bar.** Streamlit has no bottom nav. Implemented as a
  `position: fixed` HTML bar of `?screen=` **anchor links** (`nav.render_bottom_nav`),
  shown only at ≤ `mobile_max_px` via a media query. Because navigation is driven by
  `st.query_params`, the bar is genuinely clickable on mobile — not a static
  decoration. Verified rendered on every screen at 390 px (see §5).
- **Desktop side-nav.** The same `?screen=` links are placed in `st.sidebar`
  (`nav.render_side_nav`) — Streamlit's native left panel, which is a persistent
  side-nav on desktop and a hamburger drawer on mobile, matching the design's
  desktop side-nav / tablet side-rail.
- **Responsive card grid (1→2→3 col).** Streamlit `st.columns` do not reflow on
  narrow screens by themselves. CSS sets `flex-wrap: wrap` + a per-column
  `min-width` on `[data-testid="stHorizontalBlock"]`, so a 3-up desktop grid reflows
  to 1-up on a phone with **no viewport JavaScript** — the design's `gridCols`
  behaviour, achieved declaratively.
- **Metric-tile grid (2-col mobile → 5-col desktop).** Rendered as a pure CSS-grid
  block (`.tile-grid`, `repeat(auto-fill, minmax(140px, 1fr))`) so it packs 2 tiles
  on a 390 px phone and 5 on desktop.
- **Card shadows / radii / status pills / synthetic badge.** No native Streamlit
  primitives; all are `theme.build_css` classes. Chart-bearing cards use
  `st.container(border=True)` styled to the design's card look so a real Altair
  widget can live inside the card.
- **Master-detail two-pane (Browser, desktop).** Built with `st.columns([3, 2])`;
  the flex-wrap rule stacks it (list, then preview) on mobile — full parity, just
  reflowed.
- **Filter bottom-sheet.** Represented by an `st.expander("Filters & sort")`, the
  closest native affordance to the design's bottom-sheet.
- **Navigation state.** Uses `st.query_params` (screen / cycle / thesis) as the
  brief specified session-driven navigation; `st.session_state` holds transient UI
  (filter, sort, preview selection).

**Prototype chrome intentionally dropped:** the design's simulated device frame and
its in-canvas light/dark toggle are prototype scaffolding. They are replaced by
Streamlit's real responsive viewport and a real sidebar theme toggle.

**Charts are role-distinct, not one chart resized** (per the brief): axis-free
sparklines in list/overview cards; the full phase-coloured equity line and the
horizontal cost waterfall only on Thesis Detail.

---

## 3. Honest deviations — design asked for data the pipeline does not have

The design's mockup used synthetic placeholder JS data with fields the real
pipeline never produces. Rather than fabricate them (Constitution Principle IV), the
dashboard shows only real data and **labels each gap in the UI**:

1. **Equity line is a *reconstructed underlying path*, not a stored strategy
   equity.** The pipeline stores per-split cost-honest returns, not a daily equity
   series. `data.reconstruct_equity` rebuilds the cumulative return of the traded
   instrument across the cycle's **real** refinement + final-evaluation split
   windows (direction per the hypothesis), and the section is explicitly labeled as
   such. When the current lake cannot cover a cycle's split windows — e.g. an older
   cycle whose spot series has since been replaced by a shorter real feed — the
   section says so and draws **nothing**, rather than a blank or faked line
   (Principle VII). Verified by `test_equity_refuses_when_window_not_covered`.
2. **Market Overview shows real instruments only, config-driven.** Only instruments
   present in the lake are rendered (today the SE/CO submarket set). No S/NE/N
   submarket cards are fabricated. Instruments and their roles come from
   `config.yaml` `overview:` + the pipeline universe.
3. **Thesis display name is derived, and labeled derived.** The data has no thesis
   name / signal family; the name is built as `instruments · direction · horizon`
   and a caption states it is derived, never a stored field.
4. **Metric tiles show only computed metrics.** Net return (net of cost), Sharpe,
   max drawdown, days, and window come from `backtest_results.other_metrics`. The
   mockup's Sortino / hit-rate / turnover are **omitted, not fabricated**, with a
   caption saying so.
5. **Validation shows the one real screening test.** Block-bootstrap statistic,
   one-sided p-value, multiplicity method, BH-adjusted threshold, and verdict — the
   pipeline's actual test. The mockup's ADF / Ljung-Box / DSR / walk-forward tiles
   are not in the data and are omitted (captioned).
6. **SYNTHETIC labeling is prominent everywhere** (cards, badges, banners, equity).
   Most current data is synthetic-sourced, so the badge appears often — correct per
   Principle IV; there is no path by which a synthetic result reads as real.

**A note on the "richer structured store" the brief invited:** it already exists.
`research_reports.thesis_entries` holds one JSON list per cycle, each entry carrying
rationale, hypothesis, `synthetic_inputs`, the full screening block, and backtests
with the complete cost breakdown. The dashboard reads **this**, not the Markdown
reports — no separate store was needed.

---

## 4. Constitution compliance

- **IV Backtest Honesty** — net-of-cost is always shown with its gross→−costs→net
  waterfall; synthetic data is labeled on every surface it appears.
- **V Mobile-First** — every screen and action is reachable at 390 px; verified with
  real screenshots (§5), not assumed.
- **VI Config Over Hardcoding** — paths, display limits, overview instrument roles,
  breakpoints, and thresholds live in `dashboard/config.yaml`; pipeline paths + the
  instrument universe resolve through `energy_research.config.load_config`.
- **VII Fail-Loud** — missing series / uncoverable split windows produce an explicit
  labeled message, never a silent blank.
- **VIII Simplicity** — the data layer is a thin read-only facade over the existing
  `Repository`; a per-run connection (tiny dataset) avoids cross-thread SQLite
  caching complexity. `dashboard/` sits outside the import-linter roots and depends
  on `energy_research` read APIs only — the same one-directional consumer pattern as
  `ops_agent`.

---

## 5. Mobile-first verification & desktop→mobile parity self-check

Verified by rendering the running app in headless Chromium at **390 px (mobile)**
and **1280 px (desktop)** for all four screens:

| Desktop feature | Reachable on mobile? | How |
|---|---|---|
| Screen navigation (side-nav) | ✅ | Fixed bottom tab bar (same `?screen=` links) |
| Cycle selection | ✅ | `st.selectbox` (full-width on mobile) |
| Filter / sort | ✅ | "Filters & sort" expander (sheet) |
| Thesis list + open a thesis | ✅ | Feed cards, each with Preview / Open → buttons |
| Master-detail preview pane | ✅ | Reflows below the list (flex-wrap), same content |
| Metric tiles | ✅ | 2-col grid on mobile (5-col on desktop) |
| Cost waterfall + net-of-cost figures | ✅ | Full-width chart, stacked accordion |
| Reconstructed equity (or its unavailable notice) | ✅ | Full-width in the Backtest accordion |
| Validation / risk / narrative accordions | ✅ | Stacked `st.expander`s |
| Cycle history + drill-in | ✅ | Cards with "Browse this cycle →" |
| Dark-mode toggle, Refresh | ✅ | Sidebar (hamburger drawer on mobile) |

**Result: no feature is desktop-only.** Every desktop action has a mobile path;
larger screens only add layout density (3-up grids, the side-by-side preview pane,
5-across metrics), never functionality.

---

## 6. Running & testing

```bash
uv sync                                   # installs streamlit + altair
uv run streamlit run dashboard/app.py     # launch (reads data/research.sqlite)
uv run pytest tests/dashboard             # data-layer mapping + formatting tests
```
