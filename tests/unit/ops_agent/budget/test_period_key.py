from __future__ import annotations

from datetime import UTC, datetime

from ops_agent.budget import _period_key


def test_hourly_period_key_truncates_to_the_hour():
    now = datetime(2026, 7, 19, 14, 37, 52, tzinfo=UTC)
    assert _period_key("hourly", now) == "2026-07-19T14:00:00"


def test_daily_period_key_truncates_to_the_day():
    now = datetime(2026, 7, 19, 14, 37, 52, tzinfo=UTC)
    assert _period_key("daily", now) == "2026-07-19"


def test_different_hours_within_the_same_day_get_different_hourly_keys():
    a = datetime(2026, 7, 19, 1, 0, tzinfo=UTC)
    b = datetime(2026, 7, 19, 2, 0, tzinfo=UTC)
    assert _period_key("hourly", a) != _period_key("hourly", b)
    assert _period_key("daily", a) == _period_key("daily", b)
