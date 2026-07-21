"""Unit tests for the dashboard's pure formatting/classification helpers."""

from __future__ import annotations

from dashboard.utils import format as fmt


def test_status_bucket_maps_all_pipeline_statuses():
    assert fmt.status_bucket("promoted") == "promoted"
    for s in ("screened_rejected", "rejected_underperform", "rejected_after_final",
              "invalid_schema", "refused"):
        assert fmt.status_bucket(s) == "rejected"
    for s in ("proposed", "screened_passed", "backtested", "final_evaluation_pending"):
        assert fmt.status_bucket(s) == "pending"


def test_unknown_status_never_reads_as_success_or_failure():
    # An unrecognised status must fall back to amber (pending), never green/red.
    assert fmt.status_bucket("some_new_status") == "pending"


def test_status_label_humanises_underscores():
    assert fmt.status_label("rejected_after_final") == "rejected after final"


def test_number_formatters():
    assert fmt.fmt_num(1234.5) == "1,234.50"
    assert fmt.fmt_num(None) == "—"
    assert fmt.fmt_signed(0.1234) == "+0.1234"
    assert fmt.fmt_signed(-0.5) == "-0.5000"
    assert fmt.fmt_pct(0.1321) == "13.21%"
    assert fmt.fmt_signed_pct(0.05) == "+5.00%"
    assert fmt.fmt_brl(100.0) == "R$ 100.00"


def test_date_formatters():
    assert fmt.fmt_date("2026-07-19T16:41:32.278103+00:00") == "2026-07-19"
    assert fmt.fmt_date("2025-11-20") == "2025-11-20"
    assert fmt.fmt_date(None) == "—"
    assert fmt.fmt_date_range(["2024-11-27", "2025-11-20"]) == "2024-11-27 → 2025-11-20"
    assert fmt.fmt_date_range("nope") == "—"


def test_derive_thesis_name_from_hypothesis():
    h = {"instruments": ["BR_POWER_SE_SPOT"], "direction": "short", "horizon": "refinement_window"}
    assert fmt.derive_thesis_name(h) == "BR_POWER_SE_SPOT · short · refinement_window"
    assert fmt.derive_thesis_name({}) == "(no instrument) · — · —"


def test_short_id_keeps_prefix():
    assert fmt.short_id("th_11d4f0437991") == "th_11d4f043"
    assert fmt.short_id("short") == "short"
