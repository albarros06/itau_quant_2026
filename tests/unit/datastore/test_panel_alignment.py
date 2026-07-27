"""Cross-instrument calendar-alignment guard on split-panel reads (Finding #6).

A missing print for one instrument must never silently thin (and gap-stitch) the
panel every downstream statistic runs on: the attrition is surfaced, and beyond a
configured tolerance the read refuses loudly instead of dropping.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from energy_research.datastore.repository import Repository


def _panel() -> pd.DataFrame:
    """Two instruments over 10 days; B has a leading gap (before its history
    starts) plus two interior holes inside the shared window."""
    dates = pd.date_range("2025-01-01", periods=10, freq="D")
    a = pd.Series(np.arange(10, dtype=float) + 100.0, index=dates)
    b = pd.Series(np.arange(10, dtype=float) + 200.0, index=dates)
    b.iloc[0] = np.nan  # leading: before B's first observation -> trimmed, not a hole
    b.iloc[4] = np.nan  # interior hole (2025-01-05)
    b.iloc[5] = np.nan  # interior hole (2025-01-06)
    return pd.DataFrame({"A": a, "B": b})


def _repo(tmp_path, limit):
    return Repository(tmp_path / "db.sqlite", tmp_path / "lake", max_cross_series_gap_days=limit)


class TestPanelAlignment:
    def test_under_tolerance_drops_holes_and_reports_count(self, tmp_path):
        repo = _repo(tmp_path, limit=5)
        try:
            aligned, n_dropped = repo._align_panel(_panel(), "refinement")
        finally:
            repo.close()
        assert n_dropped == 2  # the two interior holes, not the leading gap
        assert not aligned.isna().any().any()
        # Restricted to the overlap window: leading pre-history row is trimmed.
        assert aligned.index[0] == pd.Timestamp("2025-01-02")
        assert list(aligned.index) == [
            pd.Timestamp(d)
            for d in ("2025-01-02", "2025-01-03", "2025-01-04", "2025-01-07",
                      "2025-01-08", "2025-01-09", "2025-01-10")
        ]

    def test_over_tolerance_refuses_loudly(self, tmp_path):
        repo = _repo(tmp_path, limit=1)
        try:
            with pytest.raises(ValueError, match="misaligned"):
                repo._align_panel(_panel(), "refinement")
        finally:
            repo.close()

    def test_surface_only_never_refuses(self, tmp_path):
        repo = _repo(tmp_path, limit=None)  # None => drop + warn, never raise
        try:
            aligned, n_dropped = repo._align_panel(_panel(), "refinement")
        finally:
            repo.close()
        assert n_dropped == 2
        assert not aligned.isna().any().any()

    def test_aligned_panel_is_untouched(self, tmp_path):
        dates = pd.date_range("2025-01-01", periods=6, freq="D")
        clean = pd.DataFrame(
            {"A": np.arange(6.0) + 100.0, "B": np.arange(6.0) + 200.0}, index=dates
        )
        repo = _repo(tmp_path, limit=0)  # zero tolerance, but nothing to drop
        try:
            aligned, n_dropped = repo._align_panel(clean, "final_evaluation")
        finally:
            repo.close()
        assert n_dropped == 0
        pd.testing.assert_frame_equal(aligned, clean)


def _weekend_panel() -> pd.DataFrame:
    """Ten days starting Monday 2025-01-06 (includes Sat 01-11/Sun 01-12). A prints
    every calendar day (ONS-style); B only prints on weekdays (BACEN-style) plus one
    genuine interior weekday hole (2025-01-08) that isn't calendar-driven."""
    dates = pd.date_range("2025-01-06", periods=10, freq="D")
    a = pd.Series(np.arange(10, dtype=float) + 100.0, index=dates)
    b = pd.Series(np.arange(10, dtype=float) + 200.0, index=dates)
    b.iloc[5] = np.nan  # Saturday 2025-01-11
    b.iloc[6] = np.nan  # Sunday 2025-01-12
    b.iloc[2] = np.nan  # genuine interior hole, Wednesday 2025-01-08
    return pd.DataFrame({"A": a, "B": b})


class TestBusinessDayReindex:
    def test_weekend_absence_excluded_not_counted_as_hole(self, tmp_path):
        repo = _repo(tmp_path, limit=5)
        try:
            aligned, n_dropped = repo._align_panel(
                _weekend_panel(),
                "discovery",
                instrument_calendars={"A": "calendar_day", "B": "business_day"},
            )
        finally:
            repo.close()
        # Only the genuine weekday hole counts; the weekend absence is excluded
        # from the join calendar entirely, not counted as misalignment.
        assert n_dropped == 1
        assert pd.Timestamp("2025-01-11") not in aligned.index
        assert pd.Timestamp("2025-01-12") not in aligned.index
        assert pd.Timestamp("2025-01-08") not in aligned.index  # dropped hole
        assert not aligned.isna().any().any()

    def test_genuine_business_day_hole_still_trips_tolerance(self, tmp_path):
        repo = _repo(tmp_path, limit=0)
        try:
            with pytest.raises(ValueError, match="misaligned"):
                repo._align_panel(
                    _weekend_panel(),
                    "discovery",
                    instrument_calendars={"A": "calendar_day", "B": "business_day"},
                )
        finally:
            repo.close()

    def test_all_calendar_day_panel_keeps_weekends(self, tmp_path):
        """Regression guard: a panel with no business-day instrument must be
        completely untouched by reindexing, even across a weekend."""
        dates = pd.date_range("2025-01-06", periods=10, freq="D")
        clean = pd.DataFrame(
            {"A": np.arange(10.0) + 100.0, "B": np.arange(10.0) + 200.0}, index=dates
        )
        repo = _repo(tmp_path, limit=0)
        try:
            aligned_typed, n_dropped_typed = repo._align_panel(
                clean.copy(),
                "discovery",
                instrument_calendars={"A": "calendar_day", "B": "calendar_day"},
            )
            aligned_none, n_dropped_none = repo._align_panel(
                clean.copy(), "discovery", instrument_calendars=None
            )
        finally:
            repo.close()
        pairs = ((aligned_typed, n_dropped_typed), (aligned_none, n_dropped_none))
        for aligned, n_dropped in pairs:
            assert n_dropped == 0
            assert pd.Timestamp("2025-01-11") in aligned.index
            assert pd.Timestamp("2025-01-12") in aligned.index
            pd.testing.assert_frame_equal(aligned, clean)
