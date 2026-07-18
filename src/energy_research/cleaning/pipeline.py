"""Cleaning layer: normalize raw connector output into CleanedSeries records.

Consumes ``RawObservation`` lists from the ingestion layer and produces
``CleanedSeries`` value objects (common.records) for the caller (orchestration/CLI)
to persist through the datastore's write API — this layer never imports datastore
(contracts/architecture-boundaries.md).

Provenance is carried through from the connector, never inferred; freshness is
stamped from the newest observation (FR-006). Quality checks are integrated here
(quality_checks.py): every detected issue is surfaced loudly and recorded, and
nothing is silently interpolated (FR-004, FR-005).
"""

from __future__ import annotations

import pandas as pd

from energy_research.common.logging import get_logger, kv
from energy_research.common.records import CleanedSeries, QualityIssue
from energy_research.config.settings import DataQualityConfig
from energy_research.ingestion.connector import RawObservation

log = get_logger("cleaning.pipeline")


def clean_series(
    raw: list[RawObservation], quality_config: DataQualityConfig | None = None
) -> CleanedSeries:
    """Normalize one series' raw observations: sort, dedupe, frame, stamp freshness."""
    if not raw:
        raise ValueError("cannot clean an empty observation list")
    category = raw[0].category
    instrument_key = raw[0].instrument_key
    provenances = {o.provenance for o in raw}
    if provenances - {"real", "synthetic"}:
        raise ValueError(
            f"series {instrument_key}: observations carry unknown provenance "
            f"{provenances} — provenance must be explicit (Principle IV)"
        )
    provenance = "synthetic" if "synthetic" in provenances else "real"

    def _naive(ts: object) -> pd.Timestamp:
        stamp = pd.Timestamp(ts)
        return stamp.tz_convert(None) if stamp.tzinfo is not None else stamp

    frame = pd.DataFrame(
        {
            "date": [_naive(o.ts) for o in raw],
            "value": [o.value for o in raw],
        }
    )
    frame = frame.sort_values("date").drop_duplicates(subset="date", keep="last")
    frame = frame.reset_index(drop=True)
    freshness_ts = max(o.ts for o in raw)
    frame["provenance"] = provenance
    frame["freshness_ts"] = freshness_ts.isoformat()

    issues: list[QualityIssue] = []
    if quality_config is not None:
        from energy_research.cleaning.quality_checks import detect_issues

        issues = detect_issues(frame, instrument_key, quality_config)
        for issue in issues:
            log.warning(
                "cleaning detected issue %s",
                kv(instrument=instrument_key, issue_type=issue.issue_type, detail=issue.detail),
            )

    return CleanedSeries(
        category=category,
        instrument_key=instrument_key,
        provider_id="",  # set by the caller that knows which connector produced it
        provenance=provenance,
        freshness_ts=freshness_ts,
        frame=frame,
        issues=issues,
    )
