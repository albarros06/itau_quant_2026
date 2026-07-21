"""Screen 2 — Thesis Browser.

Mobile: a vertical feed of thesis cards with a filter/sort "sheet" (an expander).
Desktop: a master list beside a preview pane (the design's master-detail), which
reflows to stacked on mobile via the column flex-wrap CSS. Every card is reachable
and openable at mobile width (Principle V).
"""

from __future__ import annotations

import html

import streamlit as st

from dashboard.components import nav
from dashboard.components.cards import (
    _headline_net,  # shared net extraction
    synthetic_badge_html,
    thesis_card_html,
)
from dashboard.utils import charts
from dashboard.utils import format as fmt
from dashboard.utils.data import DashboardData
from dashboard.utils.theme import Theme, status_pill_style

_SORTS = {
    "net ↓ (best first)": ("net", True),
    "net ↑ (worst first)": ("net", False),
    "status": ("status", False),
    "name": ("name", False),
}
_FILTERS = ["all", "promoted", "rejected", "pending"]


def _cycle_label(data: DashboardData, c: dict) -> str:
    s = data.cycle_summary(c["cycle_id"])
    return (
        f"{fmt.short_id(c['cycle_id'])} · {fmt.fmt_date(c['generated_at'])} · "
        f"{s['total']} theses ({s['counts']['promoted']}✓ {s['counts']['rejected']}✗)"
    )


def _sorted_filtered(data: DashboardData, cycle_id: str) -> list[dict]:
    entries = data.report_entries(cycle_id)
    flt = st.session_state.get("browser_filter", "all")
    if flt != "all":
        entries = [e for e in entries if fmt.status_bucket(e["final_status"]) == flt]
    key, desc = _SORTS[st.session_state.get("browser_sort", next(iter(_SORTS)))]
    if key == "net":
        entries.sort(
            key=lambda e: (_headline_net(e) is None, _headline_net(e) or 0.0), reverse=desc
        )
    elif key == "status":
        entries.sort(key=lambda e: e["final_status"])
    else:
        entries.sort(key=lambda e: fmt.derive_thesis_name(e.get("hypothesis", {})))
    return entries


def _filter_sheet() -> None:
    with st.expander("Filters & sort", expanded=False):
        st.session_state["browser_filter"] = st.radio(
            "Status", _FILTERS, horizontal=True,
            index=_FILTERS.index(st.session_state.get("browser_filter", "all")),
        )
        st.session_state["browser_sort"] = st.selectbox(
            "Sort by", list(_SORTS), index=list(_SORTS).index(
                st.session_state.get("browser_sort", next(iter(_SORTS)))
            ),
        )


def _preview_pane(data: DashboardData, cycle_id: str, entry: dict | None, t: Theme) -> None:
    with st.container(border=True):
        if entry is None:
            st.markdown('<div class="q-sub">Select a thesis to preview it here.</div>',
                        unsafe_allow_html=True)
            return
        name = fmt.derive_thesis_name(entry.get("hypothesis", {}))
        bucket = fmt.status_bucket(entry["final_status"])
        synth = (
            synthetic_badge_html(entry["synthetic_inputs"])
            if entry.get("synthetic_inputs")
            else ""
        )
        rationale = html.escape(entry.get("rationale", "")[:220])
        st.markdown(
            f'<div class="num" style="font-weight:700;font-size:1.05rem;">{html.escape(name)}</div>'
            f'<span class="pill" style="{status_pill_style(bucket, t)}">'
            f'{html.escape(fmt.status_label(entry["final_status"]))}</span> {synth}'
            f'<div class="q-sub" style="margin-top:6px;">{rationale}…</div>',
            unsafe_allow_html=True,
        )
        bt = (entry.get("final_evaluation") or entry.get("refinement_backtests") or [None])[-1]
        if bt is not None:
            st.caption("net-of-cost breakdown")
            st.altair_chart(charts.cost_waterfall(bt, t, height=150), width="stretch")
        if st.button("Open full detail →", key="preview_open", width="stretch"):
            nav.go("detail", cycle=cycle_id, thesis=entry["thesis_id"])


def render(data: DashboardData, t: Theme, cycle_id: str | None) -> None:
    st.markdown("## Thesis Browser")
    cycles = data.list_report_cycles()
    if not cycles:
        st.info("No research cycles with reports yet.")
        return
    ids = [c["cycle_id"] for c in cycles]
    default_ix = ids.index(cycle_id) if cycle_id in ids else 0
    chosen = st.selectbox(
        "Cycle", ids, index=default_ix,
        format_func=lambda cid: _cycle_label(data, next(c for c in cycles if c["cycle_id"] == cid)),
    )
    if chosen != st.query_params.get("cycle"):
        st.query_params["cycle"] = chosen
    cycle_id = chosen

    _filter_sheet()
    entries = _sorted_filtered(data, cycle_id)
    st.caption(f"{len(entries)} thesis(es) shown")

    list_col, preview_col = st.columns([3, 2])
    with list_col:
        for e in entries:
            st.markdown(thesis_card_html(e, t), unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            with b1:
                if st.button("Preview", key=f"prev_{e['thesis_id']}", width="stretch"):
                    st.session_state["browser_preview"] = e["thesis_id"]
                    st.rerun()
            with b2:
                if st.button("Open →", key=f"open_{e['thesis_id']}", width="stretch"):
                    nav.go("detail", cycle=cycle_id, thesis=e["thesis_id"])
    with preview_col:
        prev_id = st.session_state.get("browser_preview")
        prev_entry = next((e for e in entries if e["thesis_id"] == prev_id), None)
        if prev_entry is None and entries:
            prev_entry = entries[0]
        _preview_pane(data, cycle_id, prev_entry, t)
