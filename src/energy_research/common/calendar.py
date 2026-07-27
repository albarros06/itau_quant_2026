"""Brazilian business-day calendar helper for cross-instrument panel alignment.

BACEN series (FX, interest rate) only print on business days; ONS series print
every calendar day. Aligning a mixed panel to this calendar (rather than raw
calendar days) means weekends/national holidays are excluded from the join
entirely instead of being counted as cross-instrument misalignment holes.
"""

from __future__ import annotations

import holidays
import pandas as pd


def br_business_days(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Weekdays in [start, end] that are not Brazilian national holidays."""
    br_holidays = holidays.Brazil(years=range(start.year, end.year + 1))
    holiday_dates = pd.to_datetime(list(br_holidays.keys()))
    all_days = pd.bdate_range(start, end)
    return all_days[~all_days.isin(holiday_dates)]
