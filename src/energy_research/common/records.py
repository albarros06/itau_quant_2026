"""Shared value types passed between layers.

These live in ``common`` (not in any pipeline layer) so that, e.g., ``cleaning`` can
produce them and ``datastore`` can persist them without either layer importing the
other (contracts/architecture-boundaries.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass(frozen=True)
class QualityIssue:
    """One detected data-quality issue and what (if anything) was done about it."""

    issue_type: str  # gap | outlier | stale_feed | schema_mismatch | misconfiguration
    intervention: str  # none_raised | gap_fill | correction | fallback | rejected
    detail: str


@dataclass
class CleanedSeries:
    """Normalized output of the cleaning layer for one market-data series."""

    category: str
    instrument_key: str
    provider_id: str
    provenance: str  # 'real' | 'synthetic' — always explicit, never inferred
    freshness_ts: datetime
    frame: pd.DataFrame  # columns: date, value, provenance, freshness_ts
    issues: list[QualityIssue] = field(default_factory=list)


@dataclass(frozen=True)
class ContextDoc:
    """Normalized qualitative-context document (news / hydrology outlook / macro regime)."""

    provider_id: str
    category: str
    source: str
    doc_ts: datetime
    text: str
    provenance: str
