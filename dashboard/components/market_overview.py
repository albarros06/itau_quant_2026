"""Screen 1 — Market Overview.

A responsive grid of instrument cards (spot, reservoir, forward tenors, FX, rate),
each with latest value, provenance, span, and a sparkline; plus a forward-curve
shape card. Only instruments actually present in the lake are shown — nothing is
fabricated for a submarket that was never ingested (honest deviation #2).
"""

from __future__ import annotations

import html

import streamlit as st

from dashboard.components.cards import synthetic_badge_html
from dashboard.utils import charts
from dashboard.utils import format as fmt
from dashboard.utils.data import DashboardData, InstrumentSnapshot
from dashboard.utils.theme import Theme

_UNIT = {
    "spot": "R$/MWh",
    "forward_curve": "R$/MWh",
    "hydrology": "% stored",
    "fx": "BRL/USD",
    "interest_rate": "%/yr",
}


def _card(snap: InstrumentSnapshot, t: Theme) -> None:
    with st.container(border=True):
        unit = _UNIT.get(snap.category, "")
        prov = (
            synthetic_badge_html([snap.key])
            if snap.provenance == "synthetic"
            else (
                f'<span class="pill" style="color:{t["promoted"]};'
                f'background:{t["promotedBg"]};">REAL · {html.escape(snap.provider_id)}</span>'
            )
        )
        value = fmt.fmt_num(snap.latest_value, 2)
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:start;gap:8px;">'
            f'<div><div class="num" style="font-weight:650;">{html.escape(snap.key)}</div>'
            f'<div class="q-sub">{html.escape(snap.category)} · {html.escape(unit)}</div></div>'
            f"<div>{prov}</div></div>"
            f'<div class="num" style="font-size:1.5rem;font-weight:700;margin:6px 0 2px;">'
            f"{value}</div>"
            f'<div class="q-sub">as of {fmt.fmt_date(snap.latest_date)} · '
            f"span {fmt.fmt_date_range(list(snap.span)) if snap.span else '—'}</div>",
            unsafe_allow_html=True,
        )
        spark = charts.sparkline(snap.spark, t)
        if spark is not None:
            st.altair_chart(spark, width="stretch")
        else:
            st.markdown('<div class="q-sub">not enough points for a trend line</div>',
                        unsafe_allow_html=True)


def render(data: DashboardData, t: Theme) -> None:
    st.markdown("## Market Overview")
    snaps = data.overview_snapshots()
    if not snaps:
        st.markdown(
            '<div class="banner warn">No instrument series are present in the lake yet. '
            "Run <code>research-pipeline ingest</code> first.</div>",
            unsafe_allow_html=True,
        )
        return

    any_synth = any(s.provenance == "synthetic" for s in snaps)
    if any_synth:
        st.markdown(
            '<div class="banner warn">⚠ Some series below are <b>SYNTHETIC</b> sample data, '
            "clearly labeled per card. They must not be read as real market observations "
            "(Constitution Principle IV).</div>",
            unsafe_allow_html=True,
        )

    # Forward-curve shape card first (it summarises two tenors).
    shape = data.forward_curve_shape()
    if shape is not None:
        with st.container(border=True):
            badge = (
                synthetic_badge_html()
                if shape["synthetic"]
                else (
                    f'<span class="pill" style="color:{t["promoted"]};'
                    f'background:{t["promotedBg"]};">REAL</span>'
                )
            )
            color = t["pending"] if shape["shape"] == "contango" else t["accent"]
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;">'
                f'<div class="num" style="font-weight:650;">Forward curve</div>{badge}</div>'
                f'<div class="num" style="font-size:1.35rem;font-weight:700;color:{color};'
                f'margin:6px 0 2px;text-transform:capitalize;">{shape["shape"]}</div>'
                f'<div class="q-sub num">M1 {fmt.fmt_num(shape["front"])} → '
                f'M3 {fmt.fmt_num(shape["back"])} (Δ {fmt.fmt_signed(shape["diff"], 2)})</div>',
                unsafe_allow_html=True,
            )

    # Instrument cards in a reflowing 3-up grid (1-up on mobile via flex-wrap CSS).
    cols = st.columns(3)
    for i, snap in enumerate(snaps):
        with cols[i % 3]:
            _card(snap, t)
