"""Ingestion orchestration: connectors → cleaning → datastore persistence.

Orchestration is the only layer allowed to sequence ingestion, cleaning, and the
datastore. Provider identity comes exclusively from the config-keyed registry —
no concrete provider is imported here (Principle I).
"""

from __future__ import annotations

from dataclasses import replace

from energy_research.cleaning.pipeline import clean_series
from energy_research.common.logging import get_logger, kv
from energy_research.common.records import ContextDoc, QualityIssue
from energy_research.config.settings import PipelineConfig
from energy_research.datastore.repository import Repository
from energy_research.ingestion import registry

log = get_logger("orchestration.ingest")


def ingest_all(config: PipelineConfig, repo: Repository | None = None) -> dict:
    """Fetch, clean, quality-check, and persist all configured providers' data."""
    owns_repo = repo is None
    repo = repo or Repository(
        config.datastore.db_path,
        config.datastore.lake_dir,
        config.data_quality.max_cross_series_gap_days,
    )
    summary = {"series": 0, "context_docs": 0, "quality_issues": 0}
    instruments_by_category: dict[str, list[str]] = {}
    for inst in config.instrument_universe:
        instruments_by_category.setdefault(inst.category, []).append(inst.key)

    try:
        for entry, connector in zip(
            config.providers.market_data, registry.market_connectors(config).values(), strict=True
        ):
            health = connector.health_check()
            if not health.ok:
                raise RuntimeError(
                    f"provider {entry.provider_id!r} failed health check: "
                    f"{health.detail} — refusing to ingest (Principle VII)"
                )
            for category in entry.categories:
                for key in instruments_by_category.get(category, []):
                    raw = connector.fetch_series(category, key)
                    if not raw:
                        repo.record_quality_issue(
                            f"{category}:{key}:{entry.provider_id}",
                            QualityIssue(
                                issue_type="misconfiguration",
                                intervention="none_raised",
                                detail=f"provider {entry.provider_id} returned no "
                                f"observations for {key}",
                            ),
                        )
                        summary["quality_issues"] += 1
                        continue
                    cleaned = replace(
                        clean_series(raw, config.data_quality), provider_id=entry.provider_id
                    )
                    repo.store_cleaned_series(cleaned)
                    summary["series"] += 1
                    summary["quality_issues"] += len(cleaned.issues)

        for entry, connector in zip(
            config.providers.qualitative_context,
            registry.context_connectors(config).values(),
            strict=True,
        ):
            health = connector.health_check()
            if not health.ok:
                raise RuntimeError(
                    f"context provider {entry.provider_id!r} failed health check: {health.detail}"
                )
            docs: list[ContextDoc] = []
            for category in entry.categories:
                for raw_doc in connector.fetch_context(category):
                    docs.append(
                        ContextDoc(
                            provider_id=entry.provider_id,
                            category=raw_doc.category,
                            source=raw_doc.source,
                            doc_ts=raw_doc.ts,
                            text=raw_doc.text,
                            provenance=raw_doc.provenance,
                        )
                    )
            summary["context_docs"] += repo.store_context_docs(docs)

        log.info("ingestion complete %s", kv(**summary))
        return summary
    finally:
        if owns_repo:
            repo.close()
