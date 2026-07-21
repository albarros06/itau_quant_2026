"""Pure formatting + classification helpers (no Streamlit import, so they are
cheap to unit-test). Everything user-visible that involves a number, a date, a
status, or a thesis name flows through here, so the design's numeric/status
conventions live in exactly one place.
"""

from __future__ import annotations

from datetime import date, datetime

# The pipeline's 9 thesis statuses bucketed into the design's three colour families.
# The precise status is always shown as the label; only the *colour* is bucketed.
_STATUS_BUCKET: dict[str, str] = {
    "promoted": "promoted",
    "screened_rejected": "rejected",
    "rejected_underperform": "rejected",
    "rejected_after_final": "rejected",
    "invalid_schema": "rejected",
    "refused": "rejected",
    "proposed": "pending",
    "screened_passed": "pending",
    "backtested": "pending",
    "final_evaluation_pending": "pending",
}


def status_bucket(status: str) -> str:
    """Map a pipeline status to a design colour family: promoted/rejected/pending.

    Unknown statuses fall back to 'pending' (amber) rather than being coloured as a
    success or failure — we never imply an outcome the data does not state.
    """
    return _STATUS_BUCKET.get(status, "pending")


def status_label(status: str) -> str:
    """Human label for a status pill — the exact status, underscores → spaces."""
    return status.replace("_", " ")


def fmt_num(value: float | int | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def fmt_signed(value: float | None, decimals: int = 4) -> str:
    """Signed number (e.g. a net return), always with an explicit +/−."""
    if value is None:
        return "—"
    return f"{value:+,.{decimals}f}"


def fmt_pct(fraction: float | None, decimals: int = 2) -> str:
    """Fraction → percent string. 0.132 → '13.20%'."""
    if fraction is None:
        return "—"
    return f"{fraction * 100:,.{decimals}f}%"


def fmt_signed_pct(fraction: float | None, decimals: int = 2) -> str:
    if fraction is None:
        return "—"
    return f"{fraction * 100:+,.{decimals}f}%"


def fmt_brl(value: float | None, decimals: int = 2) -> str:
    """Brazilian-real amount. The lake's power prices are R$/MWh."""
    if value is None:
        return "—"
    return f"R$ {value:,.{decimals}f}"


def fmt_date(value: str | date | datetime | None) -> str:
    """ISO-ish input → YYYY-MM-DD. Tolerant of full timestamps and date objects."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value)
    # Trim a time component if present ('2026-07-19T16:41:...' or '... 16:41').
    for sep in ("T", " "):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    return s


def fmt_date_range(pair: object) -> str:
    """A ['2024-11-27', '2025-11-20'] pair → '2024-11-27 → 2025-11-20'."""
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        return "—"
    return f"{fmt_date(pair[0])} → {fmt_date(pair[1])}"


def derive_thesis_name(hypothesis: dict) -> str:
    """Derived display name (the data has no stored thesis name / signal family).

    Built from the hypothesis as ``instruments · direction · horizon`` — surfaced
    in the UI as *derived*, never presented as a stored field (honest deviation #3).
    Example: 'BR_POWER_SE_SPOT · short · refinement_window'.
    """
    instruments = hypothesis.get("instruments") or []
    inst = " ".join(instruments) if instruments else "(no instrument)"
    direction = hypothesis.get("direction") or "—"
    horizon = hypothesis.get("horizon") or "—"
    return f"{inst} · {direction} · {horizon}"


def short_id(identifier: str, keep: int = 8) -> str:
    """'th_11d4f0437991' → 'th_11d4f043' for compact list rows."""
    if len(identifier) <= keep + 3:
        return identifier
    if "_" in identifier:
        prefix, body = identifier.split("_", 1)
        return f"{prefix}_{body[:keep]}"
    return identifier[: keep + 3]
