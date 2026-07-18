"""US3 bounded critique-and-improve loop (spec.md User Story 3, Scenarios 1–4)."""

from __future__ import annotations

import pytest

from energy_research.config.settings import RefinementConfig
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all
from tests.conftest import build_config

MAX_DEPTH = 2
MAX_LINEAGES = 3


@pytest.fixture
def looped_cycle(tmp_path):
    config = build_config(
        tmp_path,
        refinement=RefinementConfig(
            max_refinement_depth_per_lineage=MAX_DEPTH,
            max_lineages_per_run=MAX_LINEAGES,
        ),
    )
    ingest_all(config)
    result = run_cycle(config)
    repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
    yield config, result, repo
    repo.close()


def _rejected(repo, cycle_id):
    return [
        t
        for t in repo.theses_for_cycle(cycle_id)
        if t["status"] in ("screened_rejected", "rejected_underperform")
    ]


def test_scenario_1_rejected_theses_get_specific_critiques(looped_cycle):
    _, result, repo = looped_cycle
    rejected = _rejected(repo, result.cycle_id)
    assert rejected, "sample dataset should reject at least one thesis"
    critiqued = [t for t in rejected if repo.critiques_for(t["thesis_id"])]
    assert critiqued, "at least one rejected thesis must be critiqued"
    for thesis in critiqued:
        for critique in repo.critiques_for(thesis["thesis_id"]):
            assert critique["weaknesses"], "critique must list weaknesses"
            for weakness in critique["weaknesses"]:
                assert len(weakness) > 20, "weaknesses must be specific, not generic"
            assert len(critique["suggested_direction"]) >= 10


def test_scenario_2_critiques_inform_improved_variants(looped_cycle):
    _, result, repo = looped_cycle
    theses = repo.theses_for_cycle(result.cycle_id)
    variants = [t for t in theses if t["parent_thesis_id"] is not None]
    assert variants, "the loop must generate improved/alternative variants"
    for variant in variants:
        parent = repo.get_thesis(variant["parent_thesis_id"])
        assert variant["lineage_id"] == parent["lineage_id"], (
            "variants stay in the parent's lineage"
        )
        assert variant["iteration_index"] == parent["iteration_index"] + 1
        critiques = repo.critiques_for(parent["thesis_id"])
        assert critiques, "a variant must be preceded by a critique of its parent"
        assert critiques[-1]["feeds_iteration_index"] == variant["iteration_index"]


def test_scenario_3_loop_terminates_at_configured_limits(looped_cycle):
    _, result, repo = looped_cycle
    theses = repo.theses_for_cycle(result.cycle_id)
    lineage_ids = {t["lineage_id"] for t in theses}
    # Per-run cap on lineages launched.
    assert len(lineage_ids) <= MAX_LINEAGES
    # Per-lineage refinement-depth cap: at most 1 + MAX_DEPTH variants per lineage.
    for lineage_id in lineage_ids:
        variants = repo.theses_for_lineage(lineage_id)
        assert len(variants) <= 1 + MAX_DEPTH
        assert max(v["iteration_index"] for v in variants) <= MAX_DEPTH
        assert repo.get_lineage(lineage_id)["refinement_depth"] <= MAX_DEPTH
    # Whole-run bound: the loop terminated (SC-007).
    assert len(theses) <= MAX_LINEAGES * (1 + MAX_DEPTH)


def test_scenario_4_report_covers_every_iteration(looped_cycle):
    _, result, repo = looped_cycle
    report = repo.get_report(result.cycle_id)
    reported_ids = {e["thesis_id"] for e in report["thesis_entries"] if "thesis_id" in e}
    all_ids = {t["thesis_id"] for t in repo.theses_for_cycle(result.cycle_id)}
    assert reported_ids == all_ids, (
        "report must include theses from every iteration, not only the final one"
    )
