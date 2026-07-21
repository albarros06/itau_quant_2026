"""Design tokens + CSS, reproduced verbatim from the "BR Energy Quant Dashboard"
Claude Design project (claude.ai/design/p/00d124e9-…), not reinterpreted.

Streamlit has no native concept of a fixed bottom tab bar, status pills, card
shadows/radii, a filter bottom-sheet, or a two-pane master-detail layout — every
one of those design elements is reproduced here as custom CSS injected via
``st.markdown(unsafe_allow_html=True)``. What genuinely cannot be reproduced is
noted in DESIGN_NOTES.md rather than dropped silently.

The two token dicts (LIGHT/DARK) hold the exact hex values from the design's
``THEME`` object; the mono font stack and ``tabular-nums`` numeral treatment are
the design's, applied to every number the dashboard prints.
"""

from __future__ import annotations

from dataclasses import dataclass

MONO = 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace'
SANS = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, '
    "sans-serif"
)

# Exact tokens from the design project's THEME.light / THEME.dark.
LIGHT: dict[str, str] = {
    "accent": "#2f5fda",
    "accentText": "#ffffff",
    "promoted": "#1e9a5c",
    "promotedBg": "#e6f6ee",
    "rejected": "#c9424a",
    "rejectedBg": "#fbe9ea",
    "pending": "#b7791f",
    "pendingBg": "#faf1de",
    "surface": "#ffffff",
    "surfaceAlt": "#f3f5f8",
    "border": "#e2e5ea",
    "text": "#161a20",
    "textMuted": "#6b7280",
    "pageBg": "#e9ebef",
}

DARK: dict[str, str] = {
    "accent": "#5b9dff",
    "accentText": "#eaf1ff",
    "promoted": "#3ecb8b",
    "promotedBg": "rgba(62,203,139,.14)",
    "rejected": "#ea6b72",
    "rejectedBg": "rgba(234,107,114,.14)",
    "pending": "#e7b24a",
    "pendingBg": "rgba(231,178,74,.14)",
    "surface": "#141821",
    "surfaceAlt": "#1b202b",
    "border": "#262c38",
    "text": "#e8ebf0",
    "textMuted": "#8a93a3",
    "pageBg": "#05060a",
}


@dataclass(frozen=True)
class Theme:
    name: str  # 'light' | 'dark'
    tokens: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.tokens[key]


def get_theme(dark: bool) -> Theme:
    return Theme("dark", DARK) if dark else Theme("light", LIGHT)


# Status color coding from the design: the pipeline's 9-value status is bucketed to
# three colored families — promoted (green), rejected (red), proposed/pending
# (amber) — but the *precise* status string is always shown as the pill label, so
# no information is lost (see format.status_bucket).
_BUCKET_COLORS = {
    "promoted": ("promoted", "promotedBg"),
    "rejected": ("rejected", "rejectedBg"),
    "pending": ("pending", "pendingBg"),
}


def status_pill_style(bucket: str, t: Theme) -> str:
    fg_key, bg_key = _BUCKET_COLORS.get(bucket, ("textMuted", "surfaceAlt"))
    return f"color:{t[fg_key]};background:{t[bg_key]};"


def build_css(t: Theme, mobile_max_px: int, desktop_min_px: int) -> str:
    """Full stylesheet: app chrome, cards, pills, chips, metric tiles, the fixed
    bottom tab bar, the filter bottom-sheet, and the master-detail two-pane grid.

    Card radius is 20px on mobile and 14px from tablet up, exactly as the design's
    ``renderVals()`` switches it. The bottom tab bar is shown only at/under
    ``mobile_max_px``; the desktop preview pane only from ``desktop_min_px``.
    """
    return f"""
    <style>
    :root {{
      --accent: {t['accent']}; --accent-text: {t['accentText']};
      --promoted: {t['promoted']}; --rejected: {t['rejected']}; --pending: {t['pending']};
      --surface: {t['surface']}; --surface-alt: {t['surfaceAlt']}; --border: {t['border']};
      --text: {t['text']}; --muted: {t['textMuted']}; --page-bg: {t['pageBg']};
      --mono: {MONO}; --sans: {SANS};
    }}
    /* App background + base type (design pageBg / text). */
    .stApp {{ background: var(--page-bg); }}
    html, body, [class*="css"] {{ font-family: var(--sans); color: var(--text); }}
    .block-container {{ padding-top: 1rem; padding-bottom: 5.5rem; max-width: 1180px; }}
    /* Every number uses the mono stack with tabular figures (design). */
    .num, .metric-val, .pill, .chip, .waterfall-lbl {{
      font-family: var(--mono); font-variant-numeric: tabular-nums;
    }}

    /* --- Card (radius 20px mobile / 14px tablet+, design shadow) ------------- */
    .q-card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 20px; padding: 16px; margin-bottom: 12px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 6px 18px rgba(0,0,0,.05);
    }}
    @media (min-width: {mobile_max_px + 1}px) {{ .q-card {{ border-radius: 14px; }} }}
    .q-card h4 {{ margin: 0 0 4px 0; font-size: 1rem; }}
    .q-sub {{ color: var(--muted); font-size: .8rem; }}

    /* --- Status pill (design 6-7px radius) ---------------------------------- */
    .pill {{
      display: inline-block; padding: 3px 9px; border-radius: 7px;
      font-size: .72rem; font-weight: 600; letter-spacing: .01em;
    }}
    /* --- Risk / filter chip (design 20px radius) ---------------------------- */
    .chip {{
      display: inline-block; padding: 4px 11px; border-radius: 20px;
      font-size: .74rem; border: 1px solid var(--border);
      background: var(--surface-alt); color: var(--text); margin: 0 6px 6px 0;
    }}
    .chip.on {{
      background: var(--accent); color: var(--accent-text); border-color: var(--accent);
    }}

    /* --- Metric tile -------------------------------------------------------- */
    .metric-tile {{
      background: var(--surface-alt); border: 1px solid var(--border);
      border-radius: 12px; padding: 10px 12px;
    }}
    .metric-tile .lbl {{ color: var(--muted); font-size: .68rem; text-transform: uppercase;
      letter-spacing: .04em; }}
    .metric-tile .metric-val {{ font-size: 1.15rem; font-weight: 650; }}

    /* --- SYNTHETIC badge (Principle IV: unmistakable) ----------------------- */
    .synthetic-badge {{
      display: inline-block; padding: 3px 9px; border-radius: 7px; font-size: .7rem;
      font-weight: 700; letter-spacing: .04em; font-family: var(--mono);
      color: {t['pending']}; background: {t['pendingBg']};
      border: 1px dashed {t['pending']};
    }}

    /* --- Fixed bottom tab bar (mobile only; Streamlit has none natively) ----- */
    @media (max-width: {mobile_max_px}px) {{
      .bottom-nav {{
        position: fixed; left: 0; right: 0; bottom: 0; z-index: 999;
        display: flex; justify-content: space-around;
        background: var(--surface); border-top: 1px solid var(--border);
        padding: 6px 4px; box-shadow: 0 -2px 12px rgba(0,0,0,.06);
      }}
      .bottom-nav .tab {{ font-size: .62rem; color: var(--muted); text-align: center;
        font-family: var(--sans); }}
      .bottom-nav .tab.active {{ color: var(--accent); font-weight: 700; }}
      .bottom-nav .tab .ic {{ display:block; font-size: 1.15rem; line-height: 1.1; }}
    }}
    @media (min-width: {mobile_max_px + 1}px) {{ .bottom-nav {{ display: none; }} }}

    /* --- Responsive card grid via Streamlit columns ------------------------- */
    /* Columns wrap and each keeps a minimum width, so a 3-column desktop grid
       reflows to 1 column on a 390px phone with no viewport JS — the design's
       gridCols = mobile?1:tablet?2:desktop?3 behaviour, done with flex-wrap. */
    [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 12px; }}
    [data-testid="stColumn"] {{ min-width: 300px; flex: 1 1 300px; }}

    /* --- Metric-tile grid (pure CSS grid): 2-col mobile → 5-col desktop ------ */
    .tile-grid {{
      display: grid; gap: 10px; margin: 6px 0 4px;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    }}

    /* Native bordered containers (st.container(border=True)) styled as design cards,
       so a card can wrap a real Streamlit chart widget (sparkline/waterfall). */
    [data-testid="stVerticalBlockBorderWrapper"] {{
      background: var(--surface); border: 1px solid var(--border) !important;
      border-radius: 20px; padding: 6px 4px;
      box-shadow: 0 1px 2px rgba(0,0,0,.04), 0 6px 18px rgba(0,0,0,.05);
    }}
    @media (min-width: {mobile_max_px + 1}px) {{
      [data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 14px; }}
    }}

    /* Section banner used for the top-level SYNTHETIC / honesty notice. */
    .banner {{
      border-radius: 12px; padding: 10px 14px; margin-bottom: 12px;
      font-size: .82rem; border: 1px solid var(--border); background: var(--surface-alt);
    }}
    .banner.warn {{ border-color: {t['pending']}; }}

    .cost-neg {{ color: var(--rejected); }}
    .cost-pos {{ color: var(--promoted); }}
    .accent {{ color: var(--accent); }}
    .muted {{ color: var(--muted); }}
    </style>
    """
