"""Concrete QualitativeContextConnector: file-drop context documents.

Serves news / hydrology-outlook / macro-regime documents from JSON-lines files in
a configured directory (``options.base_dir``), one file per category named
``<category>.jsonl`` with objects ``{"source", "ts", "text"}``. The concrete
vendor feeding the directory is a configuration decision, not fixed here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from energy_research.config.settings import PipelineConfig
from energy_research.ingestion.connector import ConnectorHealth, RawContextDoc


class QualitativeContextProvider:
    provider_id = "qualitative_context_provider"

    def __init__(self, base_dir: Path, provenance: str):
        self._base_dir = Path(base_dir)
        self._provenance = provenance

    def fetch_context(self, category: str, since: datetime | None = None) -> list[RawContextDoc]:
        path = self._base_dir / f"{category}.jsonl"
        if not path.exists():
            return []
        docs: list[RawContextDoc] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            ts = datetime.fromisoformat(payload["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if since is not None and ts <= since:
                continue
            docs.append(
                RawContextDoc(
                    category=category,
                    source=payload.get("source", "file_drop"),
                    ts=ts,
                    text=payload["text"],
                    provenance=self._provenance,
                )
            )
        return docs

    def health_check(self) -> ConnectorHealth:
        if not self._base_dir.is_dir():
            return ConnectorHealth(
                ok=False, detail=f"drop directory {self._base_dir} does not exist"
            )
        return ConnectorHealth(ok=True, detail=f"serving files from {self._base_dir}")


def build_context_connector(options: dict, config: PipelineConfig) -> QualitativeContextProvider:
    provenance = options.get("provenance", "real")
    if provenance not in ("real", "synthetic"):
        raise ValueError(
            f"qualitative_context_provider: provenance must be 'real' or 'synthetic', "
            f"got {provenance!r} (Principle IV)"
        )
    return QualitativeContextProvider(
        base_dir=Path(options.get("base_dir", "data/dropzone/context")),
        provenance=provenance,
    )
