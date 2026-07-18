"""Data-quality detection: gaps, outliers, stale feeds, schema mismatches.

Each detected problem becomes a :class:`QualityIssue` that the datastore persists
as a ``DataQualityRecord``. Detection never repairs: ``intervention="none_raised"``
records that the issue was surfaced without a fix — the pipeline never silently
interpolates (Constitution Principle VII, FR-004/FR-005, SC-006).
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from energy_research.common.records import QualityIssue
from energy_research.config.settings import DataQualityConfig


def detect_issues(
    frame: pd.DataFrame,
    instrument_key: str,
    config: DataQualityConfig,
    as_of: datetime | None = None,
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []

    # Schema mismatch: missing columns or non-finite values.
    expected = {"date", "value"}
    missing_cols = expected - set(frame.columns)
    if missing_cols:
        issues.append(
            QualityIssue(
                issue_type="schema_mismatch",
                intervention="rejected",
                detail=f"{instrument_key}: normalized frame missing columns {sorted(missing_cols)}",
            )
        )
        return issues
    bad_values = int((~np.isfinite(frame["value"].to_numpy(dtype=float))).sum())
    if bad_values:
        issues.append(
            QualityIssue(
                issue_type="schema_mismatch",
                intervention="none_raised",
                detail=f"{instrument_key}: {bad_values} non-finite value(s) present; "
                "left in place, not interpolated",
            )
        )

    # Gaps: consecutive observations further apart than max_gap_days.
    dates = pd.to_datetime(frame["date"]).sort_values()
    deltas = dates.diff().dt.days.dropna()
    gaps = deltas[deltas > config.max_gap_days]
    for position, gap_days in gaps.items():
        gap_end = dates.loc[position]
        issues.append(
            QualityIssue(
                issue_type="gap",
                intervention="none_raised",
                detail=f"{instrument_key}: {int(gap_days)}-day gap ending "
                f"{gap_end.date()} exceeds max_gap_days={config.max_gap_days}; "
                "no gap-fill applied",
            )
        )

    # Outliers: |z-score| of daily relative change beyond threshold.
    values = frame.sort_values("date")["value"].astype(float)
    changes = values.pct_change().dropna()
    if len(changes) >= 30 and changes.std(ddof=0) > 0:
        z = (changes - changes.mean()) / changes.std(ddof=0)
        outliers = z[abs(z) > config.outlier_zscore_threshold]
        for score in outliers:
            issues.append(
                QualityIssue(
                    issue_type="outlier",
                    intervention="none_raised",
                    detail=f"{instrument_key}: daily change z-score {score:+.1f} exceeds "
                    f"threshold {config.outlier_zscore_threshold}; value retained, "
                    "not corrected",
                )
            )

    # Stale feed: newest observation older than the freshness tolerance.
    as_of = as_of or datetime.now(UTC)
    newest = pd.Timestamp(dates.iloc[-1])
    if newest.tzinfo is None:
        newest = newest.tz_localize(UTC)
    age_days = (as_of - newest.to_pydatetime()).total_seconds() / 86400
    if age_days > config.freshness_tolerance_days:
        issues.append(
            QualityIssue(
                issue_type="stale_feed",
                intervention="none_raised",
                detail=f"{instrument_key}: newest observation is {age_days:.1f} days old "
                f"(tolerance {config.freshness_tolerance_days} days)",
            )
        )

    return issues
