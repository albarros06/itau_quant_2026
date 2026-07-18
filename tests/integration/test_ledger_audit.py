"""US4 ledger audit (spec.md User Story 4 Scenario 3, SC-005): for any thesis, an
auditor can confirm via ledger.status() that its lineage's final-evaluation period
was consumed at most once — and refusals are durably recorded."""

from __future__ import annotations

import pytest

from energy_research.backtesting.service import BacktestingService
from energy_research.datastore.ledger import EvaluationLedger
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all


@pytest.fixture
def audited_cycle(pipeline_config):
    ingest_all(pipeline_config)
    result = run_cycle(pipeline_config)
    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    ledger = EvaluationLedger(pipeline_config.datastore.db_path)
    yield pipeline_config, result, repo, ledger
    repo.close()


def test_every_lineage_spent_at_most_once_and_consistently(audited_cycle):
    _, result, repo, ledger = audited_cycle
    lineage_ids = {t["lineage_id"] for t in repo.theses_for_cycle(result.cycle_id)}
    assert lineage_ids
    for lineage_id in lineage_ids:
        status = ledger.status(lineage_id)
        final_results = [
            bt
            for t in repo.theses_for_lineage(lineage_id)
            for bt in repo.backtest_results_for(t["thesis_id"], split_type="final_evaluation")
        ]
        # Cross-entity invariant 2: at most one final-evaluation result, and it
        # belongs to exactly the thesis the ledger says spent the entitlement.
        assert len(final_results) <= 1
        if status.spent:
            assert len(final_results) <= 1
            if final_results:
                assert final_results[0]["thesis_id"] == status.spent_by_thesis_id
        else:
            assert final_results == []


def test_post_hoc_reuse_attempt_is_refused_and_recorded(audited_cycle):
    config, result, repo, ledger = audited_cycle
    spent_thesis_id = result.promoted_thesis_ids[0]
    thesis = repo.get_thesis(spent_thesis_id)
    backtesting = BacktestingService(repo, ledger, config)

    outcome = backtesting.run_final_evaluation(spent_thesis_id)
    assert outcome == "refused"
    # Still exactly one final-evaluation result...
    final_results = repo.backtest_results_for(spent_thesis_id, split_type="final_evaluation")
    assert len(final_results) == 1
    # ...and the refusal is durable and auditable, never a silent no-op.
    refusals = ledger.refusals(thesis["lineage_id"])
    assert refusals and spent_thesis_id in refusals[-1]["detail"]
    assert repo.ledger_refusal_rows(result.cycle_id)
