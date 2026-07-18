from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from energy_research.cleaning.pipeline import clean_series
from energy_research.cleaning.quality_checks import detect_issues
from energy_research.config.settings import DataQualityConfig
from energy_research.ingestion.connector import RawObservation

QC = DataQualityConfig(freshness_tolerance_days=7, max_gap_days=5, outlier_zscore_threshold=6.0)


_BASE_TS = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def obs(days_ago: float, value: float, provenance="synthetic") -> RawObservation:
    return RawObservation(
        category="spot",
        instrument_key="X",
        ts=_BASE_TS - timedelta(days=days_ago),
        value=value,
        provenance=provenance,
    )


class TestCleanSeries:
    def test_sorts_and_dedupes_keeping_last(self):
        raw = [obs(1, 10.0), obs(3, 8.0), obs(1, 11.0)]
        cleaned = clean_series(raw)
        assert list(cleaned.frame["value"]) == [8.0, 11.0]
        assert cleaned.provenance == "synthetic"

    def test_freshness_is_newest_observation(self):
        raw = [obs(9, 1.0), obs(2, 2.0)]
        cleaned = clean_series(raw)
        assert abs((datetime.now(UTC) - cleaned.freshness_ts).days - 2) <= 0

    def test_rejects_empty_input(self):
        with pytest.raises(ValueError, match="empty"):
            clean_series([])

    def test_rejects_unknown_provenance(self):
        with pytest.raises(ValueError, match="provenance"):
            clean_series([obs(1, 1.0, provenance="probably_fine")])

    def test_mixed_provenance_labels_series_synthetic(self):
        cleaned = clean_series([obs(2, 1.0, "real"), obs(1, 2.0, "synthetic")])
        assert cleaned.provenance == "synthetic"


class TestDetectIssues:
    def _frame(self, dates, values):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(dates),
                "value": values,
                "provenance": "synthetic",
                "freshness_ts": "x",
            }
        )

    def test_gap_detected(self):
        dates = pd.date_range("2026-07-01", periods=10).tolist()
        dates = dates[:5] + [d + pd.Timedelta(days=10) for d in dates[5:]]
        issues = detect_issues(
            self._frame(dates, range(10)), "X", QC, as_of=dates[-1].tz_localize(UTC)
        )
        assert any(i.issue_type == "gap" for i in issues)
        assert all(i.intervention == "none_raised" for i in issues)

    def test_outlier_detected(self):
        dates = pd.date_range("2026-01-01", periods=100)
        values = [100.0 + (i % 3) * 0.1 for i in range(100)]
        values[50] = 5000.0
        issues = detect_issues(
            self._frame(dates, values), "X", QC, as_of=dates[-1].tz_localize(UTC)
        )
        assert any(i.issue_type == "outlier" for i in issues)

    def test_stale_feed_detected(self):
        dates = pd.date_range("2026-01-01", periods=30)
        issues = detect_issues(
            self._frame(dates, range(30)),
            "X",
            QC,
            as_of=(dates[-1] + pd.Timedelta(days=30)).tz_localize(UTC),
        )
        assert any(i.issue_type == "stale_feed" for i in issues)

    def test_clean_series_has_no_issues(self):
        dates = pd.date_range("2026-07-01", periods=60)
        values = [100 + 0.1 * i for i in range(60)]
        issues = detect_issues(
            self._frame(dates, values), "X", QC, as_of=dates[-1].tz_localize(UTC)
        )
        assert issues == []
