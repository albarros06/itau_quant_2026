"""US4 reproducibility (spec.md User Story 4 Scenario 2, SC-009): replaying a
completed cycle from its recorded config snapshot + seed reproduces the same
shortlist and verdicts."""

from __future__ import annotations

import json

from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import replay_cycle, run_cycle
from energy_research.orchestration.ingest import ingest_all


def _outcome_fingerprint(repo: Repository, cycle_id: str) -> list[tuple]:
    """Cycle outcome keyed by hypothesis content (ids differ across replays)."""
    fingerprint = []
    for thesis in repo.theses_for_cycle(cycle_id):
        hyp = thesis["hypothesis"]
        screening = repo.screening_result_for(thesis["thesis_id"])
        fingerprint.append(
            (
                thesis["iteration_index"],
                tuple(hyp.get("instruments", [])),
                hyp.get("direction"),
                thesis["status"],
                None
                if screening is None
                else (
                    screening["verdict"],
                    round(screening["p_value"], 12),
                    round(screening["adjusted_threshold"], 12),
                ),
                tuple(
                    (bt["split_type"], round(bt["net_return"], 12))
                    for bt in repo.backtest_results_for(thesis["thesis_id"])
                ),
            )
        )
    return sorted(fingerprint)


def test_replay_reproduces_shortlist_and_verdicts(pipeline_config):
    ingest_all(pipeline_config)
    original = run_cycle(pipeline_config)
    replayed = replay_cycle(pipeline_config, original.cycle_id)

    assert replayed.cycle_id != original.cycle_id, "replay is a new, auditable cycle"
    assert replayed.seed == original.seed, "replay must reuse the recorded seed"

    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        original_fp = _outcome_fingerprint(repo, original.cycle_id)
        replayed_fp = _outcome_fingerprint(repo, replayed.cycle_id)
    finally:
        repo.close()

    assert original_fp == replayed_fp, (
        "identical config snapshot + seed must yield identical theses, verdicts, "
        "and net-of-cost results"
    )
    assert len(replayed.promoted_thesis_ids) == len(original.promoted_thesis_ids)


def test_pre003_snapshot_without_conditional_screening_still_replays(pipeline_config):
    """SC-006/FR-012/FR-013: a cycle recorded before 003 (its config_snapshot has no
    conditional_screening section) must still replay to its recorded shortlist — the
    new section falls back to defaults and never triggers on the unconditional path."""
    ingest_all(pipeline_config)
    original = run_cycle(pipeline_config)

    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        snapshot = repo.get_cycle(original.cycle_id)["config_snapshot"]
        assert "conditional_screening" in snapshot  # 003 records it...
        snapshot.pop("conditional_screening")  # ...but a pre-003 DB row would not have it
        repo._conn.execute(
            "UPDATE research_cycles SET config_snapshot = ? WHERE cycle_id = ?",
            (json.dumps(snapshot), original.cycle_id),
        )
        repo._conn.commit()
        original_fp = _outcome_fingerprint(repo, original.cycle_id)
    finally:
        repo.close()

    replayed = replay_cycle(pipeline_config, original.cycle_id)

    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    try:
        replayed_fp = _outcome_fingerprint(repo, replayed.cycle_id)
    finally:
        repo.close()
    assert original_fp == replayed_fp
