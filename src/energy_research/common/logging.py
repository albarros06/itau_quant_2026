"""Structured, fail-loud logging (Constitution Principle VII).

All warnings/errors about data quality, refusals, and misconfiguration flow through
here so they are visible on the console and greppable in captured output. The
durable record is the datastore (DataQualityRecord / refusal rows); this module is
the *visible* half of "raise a visible error or warning".
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_configured = False


def configure(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root = logging.getLogger("energy_research")
    root.addHandler(handler)
    root.setLevel(level)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(f"energy_research.{name}")


def kv(**fields: object) -> str:
    """Render key=value pairs for structured log lines."""
    return " ".join(f"{k}={v!r}" for k, v in fields.items())
