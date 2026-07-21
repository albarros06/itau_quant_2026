"""Navigation: the design's desktop side-nav and mobile fixed bottom tab bar.

Both are the *same* set of destinations rendered as ``?screen=`` anchor links, so
navigation is genuinely clickable at every width (Principle V):

- ``render_side_nav`` puts the links in ``st.sidebar`` — Streamlit's native left
  panel, which is a persistent side-nav on desktop and a hamburger drawer on
  mobile, matching the design's desktop side-nav / tablet side-rail.
- ``render_bottom_nav`` emits the design's fixed bottom tab bar (Streamlit has no
  such element natively) as ``position: fixed`` HTML anchor links, shown only at
  mobile width via the CSS in ``theme.build_css``.

Screen selection is driven by ``st.query_params`` so the fixed HTML bar actually
navigates; drill-down actions use ``go()`` to keep the params in sync.
"""

from __future__ import annotations

import streamlit as st

from dashboard.utils.theme import Theme

# (key, label, emoji icon) — four screens, exactly the design's set.
SCREENS: list[tuple[str, str, str]] = [
    ("overview", "Market Overview", "📈"),
    ("browser", "Thesis Browser", "🧭"),
    ("detail", "Thesis Detail", "🔬"),
    ("history", "Cycle History", "🗂"),
]
_KEYS = {k for k, _, _ in SCREENS}
DEFAULT_SCREEN = "overview"


def current_screen() -> str:
    screen = st.query_params.get("screen", DEFAULT_SCREEN)
    return screen if screen in _KEYS else DEFAULT_SCREEN


def go(screen: str, **params: str) -> None:
    """Navigate to a screen, updating query params, then rerun. Used by drill-down
    buttons (open a thesis, pick a cycle)."""
    st.query_params["screen"] = screen
    for key, value in params.items():
        if value is None:
            st.query_params.pop(key, None)
        else:
            st.query_params[key] = value
    st.rerun()


def _link(screen: str, label: str, icon: str, active: str, *, bottom: bool) -> str:
    is_active = screen == active
    if bottom:
        cls = "tab active" if is_active else "tab"
        return (
            f'<a href="?screen={screen}" target="_self" class="{cls}" '
            f'style="text-decoration:none;">'
            f'<span class="ic">{icon}</span>{label.split()[-1]}</a>'
        )
    weight = "700" if is_active else "500"
    color = "var(--accent)" if is_active else "var(--text)"
    bg = "var(--surface-alt)" if is_active else "transparent"
    return (
        f'<a href="?screen={screen}" target="_self" '
        f'style="display:block;padding:9px 12px;margin:2px 0;border-radius:10px;'
        f'text-decoration:none;font-weight:{weight};color:{color};background:{bg};">'
        f'{icon}&nbsp; {label}</a>'
    )


def render_side_nav(active: str, t: Theme) -> None:
    with st.sidebar:
        st.markdown(
            '<div style="font-family:var(--mono);font-weight:700;font-size:1.05rem;'
            'margin:2px 0 10px;">BR Energy&nbsp;<span class="accent">Quant</span></div>',
            unsafe_allow_html=True,
        )
        links = "".join(
            _link(k, label, icon, active, bottom=False) for k, label, icon in SCREENS
        )
        st.markdown(links, unsafe_allow_html=True)


def render_bottom_nav(active: str) -> None:
    tabs = "".join(_link(k, label, icon, active, bottom=True) for k, label, icon in SCREENS)
    st.markdown(f'<div class="bottom-nav">{tabs}</div>', unsafe_allow_html=True)
