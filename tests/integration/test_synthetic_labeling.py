"""US2 synthetic labeling (FR-007, spec US2 Scenario 5): provenance=synthetic set
during cleaning is clearly labeled end to end — datastore, report entries, and the
rendered artifact — with no path by which a synthetic result reads as real."""

from __future__ import annotations

from energy_research.datastore import lake
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all


def test_synthetic_provenance_survives_to_the_report(pipeline_config):
    ingest_all(pipeline_config)
    result = run_cycle(pipeline_config)

    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        # 1. Datastore rows and the Parquet frames themselves carry the label.
        rows = repo.series_rows()
        assert rows and all(r["provenance"] == "synthetic" for r in rows)
        for row in rows:
            frame = lake.read_series(pipeline_config.datastore.lake_dir, row["storage_ref"])
            assert (frame["provenance"] == "synthetic").all()

        # 2. Context documents are labeled too.
        assert all(d["provenance"] == "synthetic" for d in repo.context_documents())

        # 3. Every report entry names its synthetic inputs...
        report = repo.get_report(result.cycle_id)
        entries = [e for e in report["thesis_entries"] if "thesis_id" in e]
        assert entries
        for entry in entries:
            instruments = entry["hypothesis"].get("instruments", [])
            if instruments:
                assert entry["synthetic_inputs"] == sorted(instruments), (
                    "every synthetic input series must be surfaced on the entry"
                )
    finally:
        repo.close()

    # 4. ...and the human-readable artifact is unmistakable about it, including
    #    for promoted results (no synthetic result presented as real).
    text = result.report_path.read_text()
    assert text.count("SYNTHETIC DATA") >= len(entries) - text.count("failed schema validation")
    for thesis_id in result.promoted_thesis_ids:
        section = text.split(f"## Thesis `{thesis_id}`")[1].split("## ")[0]
        assert "SYNTHETIC" in section
