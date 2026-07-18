"""Parquet data-lake helpers, partitioned by category / instrument / provider.

Every stored frame carries ``provenance`` and ``freshness_ts`` columns so the
real/synthetic label and as-of time travel with the data itself, not alongside it
(Constitution Principle IV).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {"date", "value", "provenance", "freshness_ts"}


def storage_ref(category: str, instrument_key: str, provider_id: str) -> str:
    """Relative lake path for one series (the DataSeries.storage_ref value)."""
    return f"{category}/{instrument_key}/{provider_id}.parquet"


def write_series(
    lake_dir: Path, category: str, instrument_key: str, provider_id: str, frame: pd.DataFrame
) -> str:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(
            f"refusing to write series {category}/{instrument_key}: missing required "
            f"columns {sorted(missing)} (provenance/freshness must travel with the data)"
        )
    ref = storage_ref(category, instrument_key, provider_id)
    path = Path(lake_dir) / ref
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = frame.sort_values("date").reset_index(drop=True)
    frame.to_parquet(path, index=False)
    return ref


def read_series(lake_dir: Path, ref: str) -> pd.DataFrame:
    path = Path(lake_dir) / ref
    if not path.exists():
        raise FileNotFoundError(f"data lake has no series at {path}")
    return pd.read_parquet(path)
