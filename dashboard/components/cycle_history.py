"""Screen 4 — Cycle History / Research Tracker.

A card for the most recent cycle (its run outcome as progress-style steps) plus a
list of past cycles, each with status-bucket counts and best net/Sharpe, tappable
to browse that cycle's theses. Aggregates come straight from the persisted reports.
"""

from __future__ import annotations

import html

import streamlit as st

from dashboard.components import nav
from dashboard.components.cards import synthetic_badge_html
from dashboard.utils import format as fmt
from dashboard.utils.data import DashboardData
from dashboard.utils.theme import Theme


def _counts_bar(counts: dict, t: Theme) -> str:
    total = max(1, sum(counts.values()))
    seg = []
    for bucket, color in (("promoted", t["promoted"]), ("rejected", t["rejected"]),
                          ("pending", t["pending"])):
        pct = 100 * counts.get(bucket, 0) / total
        if pct > 0:
            seg.append(f'<div style="width:{pct:.1f}%;background:{color};"></div>')
    return (
        '<div style="display:flex;height:8px;border-radius:5px;overflow:hidden;'
        f'margin:6px 0;">{"".join(seg)}</div>'
    )


def _cycle_card(data: DashboardData, c: dict, t: Theme, *, headline: bool) -> None:
    s = data.cycle_summary(c["cycle_id"])
    counts = s["counts"]
    with st.container(border=True):
        synth = synthetic_badge_html() if s["any_synthetic"] else ""
        title = "Most recent cycle" if headline else fmt.short_id(c["cycle_id"], 12)
        best_net = fmt.fmt_signed_pct(s["best_net"]) if s["best_net"] is not None else "—"
        best_sharpe = fmt.fmt_num(s["best_sharpe"], 2) if s["best_sharpe"] is not None else "—"
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div class="num" style="font-weight:700;">{html.escape(title)}</div>'
            f'<div class="q-sub num">{fmt.fmt_date(c["generated_at"])}</div></div>'
            f'<div class="q-sub num">{fmt.short_id(c["cycle_id"], 12)} · seed {c["seed"]} · '
            f'{html.escape(c["status"])}</div>'
            f'{_counts_bar(counts, t)}'
            f'<div class="q-sub num">{s["total"]} theses · '
            f'<span class="cost-pos">{counts["promoted"]} promoted</span> · '
            f'<span class="cost-neg">{counts["rejected"]} rejected</span> · '
            f'{counts["pending"]} other</div>'
            f'<div class="q-sub num">best net {best_net} · best Sharpe {best_sharpe}'
            f'</div> {synth}',
            unsafe_allow_html=True,
        )
        if st.button("Browse this cycle →", key=f"browse_{c['cycle_id']}",
                     width="stretch"):
            nav.go("browser", cycle=c["cycle_id"])


def render(data: DashboardData, t: Theme, current_cycle_id: str | None) -> None:
    st.markdown("## Cycle History")
    cycles = data.list_report_cycles()
    if not cycles:
        st.info("No research cycles with reports yet. Run the pipeline to populate history.")
        return
    limit = int(data.cfg["display"].get("cycle_list_limit", 20))

    st.markdown('<div class="q-sub">Every completed research cycle, newest first. Tap one to '
                "browse its theses.</div>", unsafe_allow_html=True)
    _cycle_card(data, cycles[0], t, headline=True)

    if len(cycles) > 1:
        st.markdown("### Earlier cycles")
        cols = st.columns(2)
        for i, c in enumerate(cycles[1:limit]):
            with cols[i % 2]:
                _cycle_card(data, c, t, headline=False)
