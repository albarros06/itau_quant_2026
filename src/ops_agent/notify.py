"""Notification sink (research.md §8): shortlists, escalations, budget exhaustion.

A single ``notify(event)`` call writes a structured JSONL line (durable,
greppable) and a human-readable log line, for every completed-cycle shortlist
(FR-009), remediation escalation (FR-008), budget exhaustion (FR-022), and
vendor/credential failure (Edge Cases). ``NotificationSink`` is a small interface
so a future channel (email, Slack) is a new implementation, not a rewrite — only
the file+log sink ships with this feature.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from energy_research.common.logging import get_logger

log = get_logger("ops_agent.notify")


class NotificationSink(Protocol):
    def send(self, event: dict[str, Any]) -> None: ...


class FileNotificationSink:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, event: dict[str, Any]) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), **event}
        with self._path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        log.info("notification %s", record)


def build_sink(sink: str, path: str | Path) -> NotificationSink:
    if sink == "file":
        return FileNotificationSink(path)
    raise ValueError(f"unknown notification sink {sink!r}")
