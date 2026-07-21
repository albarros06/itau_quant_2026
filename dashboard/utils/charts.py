"""Altair chart builders (Streamlit-native via ``st.altair_chart``).

Chart roles are distinct, not one chart resized (per the design and the brief):
- ``sparkline`` — axis-free mini line for list/overview cards.
- ``cost_waterfall`` — horizontal gross → −costs → net bars for Thesis Detail
  (Principle IV: the cost breakdown always accompanies net P&L).
- ``equity_line`` — full phase-coloured reconstructed underlying path for Thesis
  Detail only.

Colours are taken from the active design Theme so light/dark stay faithful.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from dashboard.utils.theme import MONO, Theme

alt.data_transformers.disable_max_rows()


def _base(t: Theme) -> dict:
    return {"font": MONO, "text_color": t["text"], "muted": t["textMuted"], "grid": t["border"]}


def sparkline(series: pd.Series, t: Theme, up_color: str | None = None, height: int = 40):
    """Axis-free trailing mini line. Colour reflects the trailing direction."""
    if series is None or len(series) < 2:
        return None
    df = pd.DataFrame({"date": pd.to_datetime(series.index), "value": series.to_numpy()})
    rising = df["value"].iloc[-1] >= df["value"].iloc[0]
    color = up_color or (t["promoted"] if rising else t["rejected"])
    return (
        alt.Chart(df)
        .mark_line(strokeWidth=1.8, color=color)
        .encode(
            x=alt.X("date:T", axis=None),
            y=alt.Y("value:Q", axis=None, scale=alt.Scale(zero=False)),
            tooltip=[
                alt.Tooltip("date:T", title="date"),
                alt.Tooltip("value:Q", title="value", format=",.2f"),
            ],
        )
        .properties(height=height)
        .configure_view(strokeWidth=0)
    )


def cost_waterfall(bt: dict, t: Theme, height: int = 190):
    """Horizontal cost waterfall: gross, −transaction, −slippage, −financing, net.

    ``bt`` is a backtest dict with gross_return / transaction_costs / slippage /
    financing_carry / net_return. Deductions are drawn in the rejected (red) colour,
    the gross and net anchors in the accent/green colour — making net-of-cost the
    visually dominant figure (Principle IV)."""
    gross = float(bt["gross_return"])
    tx = float(bt["transaction_costs"])
    slip = float(bt["slippage"])
    fin = float(bt["financing_carry"])
    net = float(bt["net_return"])

    steps = [
        ("gross", gross, 0.0, gross, "anchor"),
        ("− transaction", -tx, gross - tx, gross, "cost"),
        ("− slippage", -slip, gross - tx - slip, gross - tx, "cost"),
        ("− financing", -fin, gross - tx - slip - fin, gross - tx - slip, "cost"),
        ("net", net, 0.0, net, "net"),
    ]
    rows = []
    for order, (label, delta, low, high, kind) in enumerate(steps):
        rows.append(
            {
                "label": label,
                "order": order,
                "low": min(low, high),
                "high": max(low, high),
                "delta": delta,
                "kind": kind,
            }
        )
    df = pd.DataFrame(rows)
    color_scale = alt.Scale(
        domain=["anchor", "cost", "net"],
        range=[t["accent"], t["rejected"], t["promoted"] if net >= 0 else t["rejected"]],
    )
    bars = (
        alt.Chart(df)
        .mark_bar(height=18, cornerRadius=3)
        .encode(
            y=alt.Y("label:N", sort=alt.SortField("order"), title=None,
                    axis=alt.Axis(labelFont=MONO, labelColor=t["text"])),
            x=alt.X("low:Q", title="return", axis=alt.Axis(format="+,.3f", gridColor=t["border"],
                    labelColor=t["textMuted"], titleColor=t["textMuted"])),
            x2="high:Q",
            color=alt.Color("kind:N", scale=color_scale, legend=None),
            tooltip=[
                alt.Tooltip("label:N", title=""),
                alt.Tooltip("delta:Q", title="Δ", format="+,.4f"),
            ],
        )
        .properties(height=height)
    )
    return bars.configure_view(strokeWidth=0)


def equity_line(frame: pd.DataFrame, t: Theme, height: int = 240):
    """Phase-coloured reconstructed underlying path. ``frame`` has date / cum_return
    / split_type columns (refinement, final_evaluation)."""
    if frame is None or frame.empty:
        return None
    df = frame.copy()
    df["date"] = pd.to_datetime(df["date"])
    phase_scale = alt.Scale(
        domain=["refinement", "final_evaluation"],
        range=[t["accent"], t["pending"]],
    )
    line = (
        alt.Chart(df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(labelColor=t["textMuted"],
                    gridColor=t["border"])),
            y=alt.Y("cum_return:Q", title="cumulative return",
                    axis=alt.Axis(format="+,.2%", labelColor=t["textMuted"],
                                  titleColor=t["textMuted"], gridColor=t["border"])),
            color=alt.Color("split_type:N", scale=phase_scale,
                            legend=alt.Legend(title="split phase", orient="top",
                                              labelColor=t["text"], titleColor=t["textMuted"])),
            tooltip=[
                alt.Tooltip("date:T", title="date"),
                alt.Tooltip("cum_return:Q", title="cum return", format="+,.3%"),
                alt.Tooltip("split_type:N", title="phase"),
            ],
        )
        .properties(height=height)
    )
    zero = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(
        color=t["textMuted"], strokeDash=[3, 3], opacity=0.6
    ).encode(y="y:Q")
    return (zero + line).configure_view(strokeWidth=0)
