"""US4 code-free audit (spec.md User Story 4 Scenario 1, SC-008): from the report
artifact alone, trace one promoted and one rejected thesis end to end —
rationale → evidence → verdict → performance."""

from __future__ import annotations

import pytest

from energy_research.datastore.repository import Repository
from energy_research.orchestration.cycle import run_cycle
from energy_research.orchestration.ingest import ingest_all


@pytest.fixture
def report_artifact(pipeline_config):
    ingest_all(pipeline_config)
    result = run_cycle(pipeline_config)
    repo = Repository(pipeline_config.datastore.db_path, pipeline_config.datastore.lake_dir)
    statuses = {t["thesis_id"]: t["status"] for t in repo.theses_for_cycle(result.cycle_id)}
    repo.close()
    return result.report_path.read_text(), result, statuses


def _section(text: str, thesis_id: str) -> str:
    parts = text.split(f"## Thesis `{thesis_id}`")
    assert len(parts) > 1, f"report has no section for thesis {thesis_id}"
    return parts[1].split("\n## ")[0]


def test_promoted_thesis_traceable_from_artifact_alone(report_artifact):
    text, result, _ = report_artifact
    assert result.promoted_thesis_ids
    section = _section(text, result.promoted_thesis_ids[0])
    # rationale → evidence → verdict → performance, all inline, no code needed
    assert "**Rationale**:" in section
    assert "**Hypothesis**:" in section
    assert "**Screening** [PASS]" in section and "adjusted threshold" in section
    assert "**Refinement backtest**: net" in section
    assert "**Final evaluation**" in section and "gross" in section
    assert "financing" in section, "performance must show the full cost breakdown"
    assert "**Final status**: promoted" in section
    assert "**Evaluation ledger**" in section and "spent by" in section


def test_rejected_thesis_traceable_from_artifact_alone(report_artifact):
    text, _, statuses = report_artifact
    rejected_id = next(tid for tid, s in statuses.items() if s == "screened_rejected")
    section = _section(text, rejected_id)
    assert "**Rationale**:" in section
    assert "**Screening** [FAIL]" in section
    assert "p-value" in section and "adjusted threshold" in section, (
        "the reviewer must see the exact statistic/threshold comparison"
    )
    assert "**Final status**: screened_rejected" in section


def test_artifact_is_self_contained_for_every_thesis(report_artifact):
    text, _, statuses = report_artifact
    for thesis_id, status in statuses.items():
        section = _section(text, thesis_id)
        assert "**Final status**:" in section and status in section
