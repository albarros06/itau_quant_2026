"""US1 end-to-end: run-cycle against the labeled sample dataset (spec.md User
Story 1, Acceptance Scenarios 1–5)."""

from __future__ import annotations

import pytest
import yaml

from energy_research.cli import main as cli_main
from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all


@pytest.fixture
def completed_cycle(pipeline_config):
    ingest_all(pipeline_config)
    result = run_cycle(pipeline_config)
    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    yield pipeline_config, result, repo
    repo.close()


def test_scenario_1_theses_with_rationale_and_testable_hypothesis(completed_cycle):
    _, result, repo = completed_cycle
    theses = repo.theses_for_cycle(result.cycle_id)
    assert len(theses) >= 1, "cycle must propose candidate theses with no manual input"
    for thesis in theses:
        if thesis["status"] == "invalid_schema":
            continue
        assert len(thesis["rationale"]) >= 20
        hyp = thesis["hypothesis"]
        assert hyp["instruments"] and hyp["direction"] and hyp["testable_claim"]


def test_scenario_2_every_thesis_has_verdict_and_specific_reason(completed_cycle):
    _, result, repo = completed_cycle
    for thesis in repo.theses_for_cycle(result.cycle_id):
        screening = repo.screening_result_for(thesis["thesis_id"])
        if thesis["status"] == "invalid_schema":
            assert thesis["status_reason"], "invalid draft must carry a specific reason"
            continue
        assert screening is not None, (
            f"thesis {thesis['thesis_id']} was dropped without a screening verdict"
        )
        assert screening["verdict"] in ("pass", "fail")
        assert screening["reason"].strip()
        assert screening["multiplicity_method"]
        assert screening["adjusted_threshold"] > 0


def test_scenario_3_failed_screening_is_never_backtested(completed_cycle):
    _, result, repo = completed_cycle
    rejected = repo.theses_for_cycle(result.cycle_id, status="screened_rejected")
    assert rejected, "sample dataset should produce at least one screened-out thesis"
    for thesis in rejected:
        assert repo.backtest_results_for(thesis["thesis_id"]) == []


def test_scenario_4_backtests_are_net_of_all_three_cost_components(completed_cycle):
    _, result, repo = completed_cycle
    any_backtest = False
    for thesis in repo.theses_for_cycle(result.cycle_id):
        for bt in repo.backtest_results_for(thesis["thesis_id"]):
            any_backtest = True
            assert bt["transaction_costs"] is not None
            assert bt["slippage"] is not None
            assert bt["financing_carry"] is not None
            assert bt["net_return"] == pytest.approx(
                bt["gross_return"]
                - bt["transaction_costs"]
                - bt["slippage"]
                - bt["financing_carry"]
            )
    assert any_backtest, "at least one screening survivor should be backtested"


def test_scenario_5_report_explains_outcomes_without_reading_code(completed_cycle):
    _, result, repo = completed_cycle
    report_text = result.report_path.read_text()
    theses = repo.theses_for_cycle(result.cycle_id)
    for thesis in theses:
        assert thesis["thesis_id"] in report_text
        assert thesis["status"] in report_text
    # Verdict reasoning and cost breakdowns are stated inline.
    assert "adjusted threshold" in report_text
    assert "Final status" in report_text
    assert "SYNTHETIC" in report_text, "sample-data results must be unmistakably labeled synthetic"
    # And a shortlist exists end to end (the sample dataset embeds a real drift).
    assert result.promoted_thesis_ids, "expected at least one promoted thesis"


def test_scenario_6_unconditional_path_matches_pre003_accounting(completed_cycle):
    """SC-006/FR-012: the stub emits unconditional theses; every screened/backtested
    result must carry the pre-003 always-in accounting exactly — full window in
    market, one entry, one closing exit — proving condition=None is byte-for-byte
    the old path."""
    _, result, repo = completed_cycle
    saw_screening = saw_backtest = False
    for thesis in repo.theses_for_cycle(result.cycle_id):
        if thesis["status"] == "invalid_schema":
            continue
        assert thesis["hypothesis"].get("condition") is None
        screening = repo.screening_result_for(thesis["thesis_id"])
        if screening and screening["other_metrics"]:
            act = screening["other_metrics"]
            assert act["in_market_days"] == act["total_days"]
            assert act["entries"] == 1 and act["exits"] == 1
            saw_screening = True
        for bt in repo.backtest_results_for(thesis["thesis_id"]):
            om = bt["other_metrics"]
            assert om["in_market_days"] == om["total_days"]
            assert om["entries"] == 1 and om["exits"] == 1
            saw_backtest = True
    assert saw_screening and saw_backtest


def test_cli_run_cycle_end_to_end(tmp_path, pipeline_config):
    """The actual `research-pipeline` CLI wires trigger → report with no manual step."""
    config_path = tmp_path / "config.yaml"
    payload = pipeline_config.model_dump(mode="json")
    payload.pop("providers_file")
    config_path.write_text(yaml.safe_dump(payload))

    assert cli_main(["--config", str(config_path), "ingest"]) == 0
    assert cli_main(["--config", str(config_path), "run-cycle"]) == 0
    reports = list(pipeline_config.datastore.reports_dir.glob("*.md"))
    assert reports, "run-cycle must emit a report artifact"
