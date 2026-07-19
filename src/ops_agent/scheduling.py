"""What's due now? (data-model.md ``OperatingSchedule``/``OperatingScheduleState``).

Each cadence kind — ``cycle``, ``market_refresh``, ``qualitative_poll`` — is tracked
independently via its own ``operating_schedule_state`` row, so ``tick`` can trigger
each on its own schedule (FR-006/007). "Is X due" is computed purely from elapsed
wall-clock time against the last-fired timestamp; a tick where nothing is due does
no work (Edge Case: idempotent no-op tick).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from ops_agent.config import OperatingSchedule

ScheduleKind = Literal["cycle", "market_refresh", "qualitative_poll"]

_CADENCE_ATTR: dict[str, str] = {
    "cycle": "cycle_cadence_hours",
    "market_refresh": "market_refresh_cadence_hours",
    "qualitative_poll": "qualitative_poll_cadence_hours",
}


def is_due(
    kind: ScheduleKind,
    config: OperatingSchedule,
    state: dict | None,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    cadence_hours = getattr(config, _CADENCE_ATTR[kind])
    if state is None or state.get("last_fired_at") is None:
        return True
    last_fired = datetime.fromisoformat(state["last_fired_at"])
    if last_fired.tzinfo is None:
        last_fired = last_fired.replace(tzinfo=UTC)
    elapsed_hours = (now - last_fired).total_seconds() / 3600
    return elapsed_hours >= cadence_hours
