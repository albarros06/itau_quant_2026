"""Provider-agnostic connector protocols (contracts/data-connector.md, Principle I).

Connectors return raw-but-normalized shapes: provider quirks (auth, pagination,
units, field naming) are resolved before ``fetch_*`` returns. Connectors do NOT
clean data — that is the cleaning layer's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawObservation:
    """One provider-native observation, already in canonical shape."""

    category: str
    instrument_key: str
    ts: datetime
    value: float
    provenance: str  # 'real' | 'synthetic' — declared by the connector, never inferred


@dataclass(frozen=True)
class RawContextDoc:
    """One qualitative-context document, already in canonical shape."""

    category: str  # news | hydrology_outlook | macro_regime | ...
    source: str
    ts: datetime
    text: str
    provenance: str


@dataclass(frozen=True)
class ConnectorHealth:
    ok: bool
    detail: str = ""


@runtime_checkable
class MarketDataConnector(Protocol):
    provider_id: str

    def fetch_series(
        self, category: str, instrument_key: str, since: datetime | None = None
    ) -> list[RawObservation]: ...

    def health_check(self) -> ConnectorHealth: ...


@runtime_checkable
class QualitativeContextConnector(Protocol):
    provider_id: str

    def fetch_context(
        self, category: str, since: datetime | None = None
    ) -> list[RawContextDoc]: ...

    def health_check(self) -> ConnectorHealth: ...
