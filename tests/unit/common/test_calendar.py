"""br_business_days: weekends and Brazilian national holidays excluded from the
join calendar used to align business-day-only series against calendar-day series."""

from __future__ import annotations

import pandas as pd

from energy_research.common.calendar import br_business_days


def test_weekends_excluded():
    # 2025-04-05/06 is a Sat/Sun pair.
    days = br_business_days(pd.Timestamp("2025-04-01"), pd.Timestamp("2025-04-10"))
    assert pd.Timestamp("2025-04-05") not in days
    assert pd.Timestamp("2025-04-06") not in days


def test_national_holiday_excluded():
    # 2025-04-21 is Tiradentes' Day, a fixed Brazilian national holiday.
    days = br_business_days(pd.Timestamp("2025-04-18"), pd.Timestamp("2025-04-24"))
    assert pd.Timestamp("2025-04-21") not in days


def test_ordinary_weekday_included():
    # 2025-04-22 is the Tuesday right after Tiradentes' Day, an ordinary weekday.
    days = br_business_days(pd.Timestamp("2025-04-18"), pd.Timestamp("2025-04-24"))
    assert pd.Timestamp("2025-04-22") in days


def test_result_only_contains_weekdays():
    days = br_business_days(pd.Timestamp("2025-01-01"), pd.Timestamp("2025-03-01"))
    assert all(d.weekday() < 5 for d in days)
