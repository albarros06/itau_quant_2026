"""Screen 3 — Thesis Detail.

Stacked accordions (narrative / validation / backtest / risk), a metric-tile grid
(2-col mobile → 5-col desktop), the horizontal cost waterfall, and the full
phase-coloured reconstructed equity line. Net-of-cost figures and the cost
breakdown always appear together (Principle IV); the equity line is labeled a
*reconstructed underlying path*, and when the lake cannot cover the cycle's split
windows the section says so instead of drawing a blank/faked curve (Principle VII).
"""

from __future__ import annotations

import html

import streamlit as st

from dashboard.components import nav
from dashboard.components.cards import metric_tile_html, synthetic_badge_html
from dashboard.utils import charts
from dashboard.utils import format as fmt
from dashboard.utils.data import DashboardData
from dashboard.utils.theme import Theme, status_pill_style


def _metrics_from(entry: dict) -> tuple[dict, str]:
    """Return (other_metrics, split_label) for the most decisive backtest available."""
    finals = entry.get("final_evaluation") or []
    if finals:
        return finals[-1].get("other_metrics", {}) or {}, "final evaluation"
    refs = entry.get("refinement_backtests") or []
    if refs:
        return refs[-1].get("other_metrics", {}) or {}, "refinement"
    return {}, ""


def _decisive_bt(entry: dict) -> dict | None:
    return (entry.get("final_evaluation") or entry.get("refinement_backtests") or [None])[-1]


def _metric_tiles(entry: dict) -> None:
    om, split_label = _metrics_from(entry)
    bt = _decisive_bt(entry)
    tiles: list[str] = []
    if bt is not None:
        tiles.append(metric_tile_html("Net return", fmt.fmt_signed_pct(bt.get("net_return")),
                                      f"{split_label} · net of cost"))
    if "sharpe" in om:
        tiles.append(metric_tile_html("Sharpe", fmt.fmt_num(om.get("sharpe"), 2), "annualised"))
    if "max_drawdown" in om:
        tiles.append(metric_tile_html("Max drawdown", fmt.fmt_pct(om.get("max_drawdown")), None))
    if "n_days" in om:
        tiles.append(metric_tile_html("Days", fmt.fmt_num(om.get("n_days"), 0), "in backtest"))
    if "date_range" in om:
        tiles.append(metric_tile_html("Window", fmt.fmt_date_range(om.get("date_range")), None))
    if not tiles:
        st.markdown('<div class="q-sub">No backtest metrics — this thesis did not reach a '
                    "backtest.</div>", unsafe_allow_html=True)
        return
    st.markdown(f'<div class="tile-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)
    st.caption(
        "Only metrics the pipeline actually computed are shown. Sortino / hit-rate / "
        "turnover from the mockup are omitted, not fabricated."
    )


def _narrative(entry: dict) -> None:
    h = entry.get("hypothesis", {}) or {}
    st.markdown(f"**Rationale.** {html.escape(entry.get('rationale',''))}")
    rows = [
        ("Instruments", ", ".join(h.get("instruments") or []) or "—"),
        ("Direction", h.get("direction", "—")),
        ("Horizon", h.get("horizon", "—")),
        ("Condition", h.get("condition", "—")),
        ("Testable claim", h.get("testable_claim", "—")),
    ]
    body = "".join(
        f'<div class="q-sub" style="margin:3px 0;"><b>{html.escape(k)}:</b> '
        f"{html.escape(str(v))}</div>" for k, v in rows
    )
    st.markdown(body, unsafe_allow_html=True)


def _validation(entry: dict, t: Theme) -> None:
    s = entry.get("screening")
    if not s:
        st.markdown('<div class="q-sub">Not screened — this thesis was rejected before the '
                    "statistical validity test.</div>", unsafe_allow_html=True)
        return
    bucket = "promoted" if s["verdict"] == "pass" else "rejected"
    st.markdown(
        f'<span class="pill" style="{status_pill_style(bucket, t)}">'
        f'{s["verdict"].upper()}</span>',
        unsafe_allow_html=True,
    )
    tiles = [
        metric_tile_html("Method", s.get("method", "—"), None),
        metric_tile_html("p-value", fmt.fmt_num(s.get("p_value"), 4), "one-sided"),
        metric_tile_html("Adj. threshold", fmt.fmt_num(s.get("adjusted_threshold"), 4),
                         s.get("multiplicity_method", "")),
        metric_tile_html("Statistic", fmt.fmt_signed(s.get("statistic_value"), 4), None),
    ]
    st.markdown(f'<div class="tile-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)
    reason = html.escape(s.get("reason", ""))
    st.markdown(
        f'<div class="q-sub" style="margin-top:6px;">{reason}</div>', unsafe_allow_html=True
    )
    st.caption(
        "This is the pipeline's one real screening test (block bootstrap + multiplicity "
        "control). The mockup's ADF / Ljung-Box / DSR / walk-forward tiles are not in the "
        "data and are omitted."
    )


def _backtest(data: DashboardData, cycle_id: str, entry: dict, t: Theme) -> None:
    bt = _decisive_bt(entry)
    if bt is None:
        st.markdown('<div class="q-sub">No backtest was run for this thesis.</div>',
                    unsafe_allow_html=True)
        return
    st.markdown("**Cost waterfall** — gross → −transaction → −slippage → −financing → **net**")
    st.altair_chart(charts.cost_waterfall(bt, t), width="stretch")
    st.markdown(
        f'<div class="q-sub num">gross {fmt.fmt_signed(bt["gross_return"])} · '
        f'tx −{fmt.fmt_num(bt["transaction_costs"],4)} · '
        f'slippage −{fmt.fmt_num(bt["slippage"],4)} · '
        f'financing −{fmt.fmt_num(bt["financing_carry"],4)} · '
        f'<b>net {fmt.fmt_signed(bt["net_return"])}</b></div>',
        unsafe_allow_html=True,
    )

    st.markdown("**Reconstructed underlying path** "
                '<span class="q-sub">(not a stored strategy-equity curve — the cumulative '
                "return of the traded instrument over this cycle's real split windows, "
                "direction per the hypothesis)</span>", unsafe_allow_html=True)
    eq = data.reconstruct_equity(cycle_id, entry)
    if eq.available:
        if eq.synthetic:
            st.markdown(synthetic_badge_html(eq.instruments), unsafe_allow_html=True)
        st.altair_chart(charts.equity_line(eq.frame, t), width="stretch")
    else:
        st.markdown(f'<div class="banner warn">Underlying path not shown: {html.escape(eq.reason)}.'
                    "</div>", unsafe_allow_html=True)


def _risk(entry: dict, t: Theme) -> None:
    om, _ = _metrics_from(entry)
    chips = []
    if "max_drawdown" in om:
        chips.append(f"max DD {fmt.fmt_pct(om['max_drawdown'])}")
    if "n_days" in om:
        chips.append(f"{int(om['n_days'])} days")
    if "date_range" in om:
        chips.append(fmt.fmt_date_range(om["date_range"]))
    if entry.get("synthetic_inputs"):
        chips.append("SYNTHETIC inputs")
    chip_html = "".join(f'<span class="chip">{html.escape(c)}</span>' for c in chips)
    st.markdown(chip_html or '<span class="q-sub">no risk metrics</span>', unsafe_allow_html=True)

    led = entry.get("evaluation_ledger")
    if led:
        state = f"spent by {led['spent_by_thesis_id']}" if led.get("spent") else "not spent"
        st.markdown(f'<div class="q-sub" style="margin-top:8px;">Final-evaluation entitlement: '
                    f"{html.escape(str(state))}</div>", unsafe_allow_html=True)
    st.markdown(f'<div class="q-sub"><b>Final status:</b> '
                f'{html.escape(fmt.status_label(entry["final_status"]))} — '
                f'{html.escape(entry.get("final_status_reason",""))}</div>', unsafe_allow_html=True)


def render(data: DashboardData, t: Theme, cycle_id: str | None, thesis_id: str | None) -> None:
    if not cycle_id or not thesis_id:
        st.info("Open a thesis from the Thesis Browser to see its detail.")
        if st.button("← Go to Thesis Browser"):
            nav.go("browser", cycle=cycle_id or "")
        return
    entry = data.thesis_entry(cycle_id, thesis_id)
    if entry is None:
        st.warning(f"Thesis {thesis_id} not found in cycle {cycle_id}.")
        if st.button("← Back to Browser"):
            nav.go("browser", cycle=cycle_id)
        return

    if st.button("← Back to Browser"):
        nav.go("browser", cycle=cycle_id)

    name = fmt.derive_thesis_name(entry.get("hypothesis", {}))
    bucket = fmt.status_bucket(entry["final_status"])
    synth = synthetic_badge_html(entry["synthetic_inputs"]) if entry.get("synthetic_inputs") else ""
    st.markdown(
        f'<h2 class="num" style="margin-bottom:2px;">{html.escape(name)}</h2>'
        f'<span class="pill" style="{status_pill_style(bucket, t)}">'
        f'{html.escape(fmt.status_label(entry["final_status"]))}</span> {synth}'
        f'<div class="q-sub num" style="margin-top:4px;">{fmt.short_id(thesis_id, 12)} · '
        f'lineage {fmt.short_id(entry["lineage_id"], 8)} · '
        f'iteration {entry["iteration_index"]}</div>',
        unsafe_allow_html=True,
    )
    st.caption("Name derived from the hypothesis (instruments · direction · horizon) — the "
               "pipeline stores no thesis name.")

    _metric_tiles(entry)

    with st.expander("Narrative & hypothesis", expanded=True):
        _narrative(entry)
    with st.expander("Validation (statistical screening)", expanded=False):
        _validation(entry, t)
    with st.expander("Backtest — net of cost", expanded=True):
        _backtest(data, cycle_id, entry, t)
    with st.expander("Risk & provenance", expanded=False):
        _risk(entry, t)
