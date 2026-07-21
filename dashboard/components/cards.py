"""Shared HTML renderers: status pill, synthetic badge, metric tile, thesis card.

These emit the design's card/pill/chip markup (Streamlit has no native equivalent)
via ``st.markdown(unsafe_allow_html=True)``, styled by the CSS in ``theme.build_css``.
Keeping them here means every screen renders the same visual atoms.
"""

from __future__ import annotations

import html

import streamlit as st

from dashboard.utils import format as fmt
from dashboard.utils.theme import Theme, status_pill_style


def status_pill_html(status: str, t: Theme) -> str:
    bucket = fmt.status_bucket(status)
    style = status_pill_style(bucket, t)
    return f'<span class="pill" style="{style}">{html.escape(fmt.status_label(status))}</span>'


def synthetic_badge_html(instruments: list[str] | None = None) -> str:
    """Unmistakable SYNTHETIC marker (Principle IV). Lists the offending inputs."""
    detail = ""
    if instruments:
        detail = " · " + html.escape(", ".join(instruments))
    return f'<span class="synthetic-badge">⚠ SYNTHETIC DATA{detail}</span>'


def metric_tile_html(label: str, value: str, sub: str | None = None) -> str:
    sub_html = f'<div class="q-sub">{html.escape(sub)}</div>' if sub else ""
    return (
        '<div class="metric-tile">'
        f'<div class="lbl">{html.escape(label)}</div>'
        f'<div class="metric-val num">{html.escape(value)}</div>'
        f"{sub_html}</div>"
    )


def chip_html(text: str, on: bool = False) -> str:
    cls = "chip on" if on else "chip"
    return f'<span class="{cls}">{html.escape(text)}</span>'


def render_metric_tiles(tiles: list[tuple[str, str, str | None]], cols: int) -> None:
    """Lay out metric tiles in an N-column grid (design: 2-col mobile, 5-col desktop)."""
    columns = st.columns(cols)
    for i, (label, value, sub) in enumerate(tiles):
        with columns[i % cols]:
            st.markdown(metric_tile_html(label, value, sub), unsafe_allow_html=True)


def thesis_card_html(entry: dict, t: Theme) -> str:
    """Compact feed/list card: derived name, status pill, net-of-cost figure, synthetic
    badge. Used by the Thesis Browser feed and the desktop master list."""
    name = fmt.derive_thesis_name(entry.get("hypothesis", {}))
    pill = status_pill_html(entry["final_status"], t)
    # Prefer the final-evaluation net; fall back to the last refinement net.
    net = _headline_net(entry)
    net_html = (
        f'<span class="num {_net_class(net)}">{fmt.fmt_signed_pct(net)}</span>'
        if net is not None
        else '<span class="muted">no backtest</span>'
    )
    synth = (
        synthetic_badge_html(entry.get("synthetic_inputs"))
        if entry.get("synthetic_inputs")
        else ""
    )
    rationale = html.escape((entry.get("rationale") or "")[:140])
    return (
        '<div class="q-card">'
        f'<div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">'
        f'<h4 class="num">{html.escape(name)}</h4>{pill}</div>'
        f'<div style="margin:6px 0;">net-of-cost: {net_html} &nbsp; {synth}</div>'
        f'<div class="q-sub">{rationale}…</div>'
        "</div>"
    )


def _headline_net(entry: dict) -> float | None:
    finals = entry.get("final_evaluation") or []
    if finals:
        return finals[-1].get("net_return")
    refs = entry.get("refinement_backtests") or []
    if refs:
        return refs[-1].get("net_return")
    return None


def _net_class(net: float | None) -> str:
    if net is None:
        return "muted"
    return "cost-pos" if net >= 0 else "cost-neg"
