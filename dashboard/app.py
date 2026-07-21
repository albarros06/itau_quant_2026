"""BR Energy Quant Dashboard — Streamlit entrypoint.

A read-only, mobile-first consumer of the research pipeline's persisted output
(SQLite datastore + Parquet lake + per-cycle reports). Reproduces the visual
language of the "BR Energy Quant Dashboard" Claude Design project. Four screens,
navigated via ``st.query_params`` so the design's fixed bottom tab bar is genuinely
clickable on mobile; see DESIGN_NOTES.md for from-design vs adapted decisions.

Run:  uv run streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st
import yaml

# `streamlit run dashboard/app.py` puts the script's own directory on sys.path, not
# the project root, so `import dashboard.*` would fail. Put the root on the path
# before importing this package's modules (and energy_research, resolved via the
# editable install). Kept above the dashboard imports on purpose (E402 suppressed).
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dashboard.components import (  # noqa: E402
    cycle_history,
    market_overview,
    nav,
    thesis_browser,
    thesis_detail,
)
from dashboard.utils.data import DashboardData  # noqa: E402
from dashboard.utils.theme import build_css, get_theme  # noqa: E402

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


@st.cache_data
def _load_dashboard_config() -> dict:
    return yaml.safe_load(_CONFIG_PATH.read_text())


def _current_cycle(data: DashboardData) -> str | None:
    """Cycle in the query params if valid, else the configured default."""
    want = st.query_params.get("cycle")
    valid = {c["cycle_id"] for c in data.list_report_cycles()}
    if want in valid:
        return want
    return data.resolve_default_cycle()


def main() -> None:
    cfg = _load_dashboard_config()
    st.set_page_config(page_title="BR Energy Quant", page_icon="📈", layout="wide")

    # Dark-mode toggle (design ships a light/dark theme; we honour both).
    with st.sidebar:
        dark = st.toggle("Dark mode", value=st.session_state.get("dark", False), key="dark")
    theme = get_theme(dark)
    st.markdown(
        build_css(theme, cfg["viewport"]["mobile_max_px"], cfg["viewport"]["desktop_min_px"]),
        unsafe_allow_html=True,
    )

    data = DashboardData(cfg, _ROOT)
    try:
        screen = nav.current_screen()
        nav.render_side_nav(screen, theme)
        with st.sidebar:
            if st.button("↻ Refresh data", width="stretch"):
                st.rerun()

        cycle_id = _current_cycle(data)
        thesis_id = st.query_params.get("thesis")

        if screen == "overview":
            market_overview.render(data, theme)
        elif screen == "browser":
            thesis_browser.render(data, theme, cycle_id)
        elif screen == "detail":
            thesis_detail.render(data, theme, cycle_id, thesis_id)
        elif screen == "history":
            cycle_history.render(data, theme, cycle_id)

        nav.render_bottom_nav(screen)
    finally:
        data.close()


main()
