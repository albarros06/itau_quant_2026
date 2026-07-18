from __future__ import annotations

import pytest

from energy_research.common import seed as seed_mod
from energy_research.datastore.repository import Repository, StaleDataError
from energy_research.generation.llm_client import ThesisLLMClient
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all
from tests.conftest import build_config


class TestSeedDiscipline:
    def test_rng_before_set_seed_is_an_error(self):
        seed_mod._rng = None  # simulate a fresh process
        with pytest.raises(RuntimeError, match="set_seed"):
            seed_mod.get_rng()

    def test_auto_generated_seed_is_recorded_on_the_cycle(self, tmp_path):
        from energy_research.config.settings import ReproducibilityConfig

        config = build_config(tmp_path, reproducibility=ReproducibilityConfig(seed=None))
        ingest_all(config)
        result = run_cycle(config)
        repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
        try:
            cycle = repo.get_cycle(result.cycle_id)
        finally:
            repo.close()
        assert cycle["seed"] == result.seed
        assert cycle["config_snapshot"]["screening"]["multiplicity_method"]


class TestEdgeCases:
    def test_cycle_refuses_before_any_ingestion(self, tmp_path):
        config = build_config(tmp_path)
        with pytest.raises(StaleDataError, match="no ingested series"):
            run_cycle(config)

    def test_no_theses_proposed_yields_report_with_stated_reason(self, tmp_path, monkeypatch):
        config = build_config(tmp_path)
        ingest_all(config)
        monkeypatch.setattr(ThesisLLMClient, "propose", lambda self, **kwargs: [])
        result = run_cycle(config)
        assert result.promoted_thesis_ids == []
        text = result.report_path.read_text()
        assert "No theses were proposed" in text
        assert "generation produced no candidate theses" in text
        repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
        try:
            assert repo.get_cycle(result.cycle_id)["status"] == "completed"
        finally:
            repo.close()

    def test_failed_cycle_is_marked_failed(self, tmp_path, monkeypatch):
        config = build_config(tmp_path)
        ingest_all(config)
        monkeypatch.setattr(
            ThesisLLMClient,
            "propose",
            lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError("provider exploded")),
        )
        with pytest.raises(RuntimeError, match="provider exploded"):
            run_cycle(config)
        repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
        try:
            cycles = repo._conn.execute("SELECT status FROM research_cycles").fetchall()
        finally:
            repo.close()
        assert [row["status"] for row in cycles] == ["failed"]


class TestSplitAllocations:
    def test_splits_are_contiguous_and_disjoint(self, tmp_path):
        config = build_config(tmp_path)
        ingest_all(config)
        result = run_cycle(config)
        repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
        try:
            disc = repo.get_allocation(result.cycle_id, "discovery")
            ref = repo.get_allocation(result.cycle_id, "refinement")
            final = repo.get_allocation(result.cycle_id, "final_evaluation")
        finally:
            repo.close()
        assert disc["date_range_end"] < ref["date_range_start"]
        assert ref["date_range_end"] < final["date_range_start"]
        assert disc["date_range_start"] < disc["date_range_end"]
        assert final["date_range_start"] < final["date_range_end"]
