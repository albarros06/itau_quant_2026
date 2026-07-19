from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ops_agent.config import OperatingSchedule
from ops_agent.scheduling import is_due

CONFIG = OperatingSchedule(
    cycle_cadence_hours=24, market_refresh_cadence_hours=6, qualitative_poll_cadence_hours=2
)


def test_none_state_is_always_due():
    assert is_due("cycle", CONFIG, None) is True
    assert is_due("cycle", CONFIG, {"last_fired_at": None}) is True


def test_not_due_before_cadence_elapses():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    state = {"last_fired_at": (now - timedelta(hours=1)).isoformat()}
    assert is_due("market_refresh", CONFIG, state, now=now) is False


def test_due_once_cadence_elapses():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    state = {"last_fired_at": (now - timedelta(hours=6)).isoformat()}
    assert is_due("market_refresh", CONFIG, state, now=now) is True


def test_each_kind_tracked_independently():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    state = {"last_fired_at": (now - timedelta(hours=3)).isoformat()}
    assert is_due("qualitative_poll", CONFIG, state, now=now) is True  # cadence 2h
    assert is_due("market_refresh", CONFIG, state, now=now) is False  # cadence 6h
    assert is_due("cycle", CONFIG, state, now=now) is False  # cadence 24h


def test_naive_last_fired_at_is_treated_as_utc():
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    naive = (now - timedelta(hours=6)).replace(tzinfo=None)
    state = {"last_fired_at": naive.isoformat()}
    assert is_due("market_refresh", CONFIG, state, now=now) is True
