"""Contract test: evaluation ledger atomicity (contracts/evaluation-ledger-contract.md).

Asserts spend() is atomic and enforces spend-once-per-lineage under repeated and
concurrent attempts, and that refusals are durably recorded, never silent.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from energy_research.datastore.ledger import EvaluationLedger, SpendOutcome
from energy_research.datastore.repository import Repository


@pytest.fixture
def ledger(tmp_path):
    repo = Repository(tmp_path / "test.sqlite", tmp_path / "lake")
    cycle_id = repo.create_cycle({}, seed=1, max_refinement_depth=1, max_lineages=1)
    lineage_id = repo.create_lineage(cycle_id, root_thesis_id="th_root")
    repo.close()
    led = EvaluationLedger(tmp_path / "test.sqlite")
    led.create(lineage_id)
    return led, lineage_id


def test_first_spend_granted_second_refused(ledger):
    led, lineage_id = ledger
    assert led.spend(lineage_id, "th_a") == SpendOutcome.GRANTED
    assert led.spend(lineage_id, "th_b") == SpendOutcome.REFUSED

    status = led.status(lineage_id)
    assert status.spent is True
    assert status.spent_by_thesis_id == "th_a"
    assert status.spent_at is not None


def test_refusal_is_recorded_not_silent(ledger):
    led, lineage_id = ledger
    led.spend(lineage_id, "th_a")
    led.spend(lineage_id, "th_b")
    led.spend(lineage_id, "th_c")

    refusals = led.refusals(lineage_id)
    assert len(refusals) == 2
    attempted = {r["attempted_thesis_id"] for r in refusals}
    assert attempted == {"th_b", "th_c"}
    for r in refusals:
        assert "already spent" in r["detail"]


def test_spend_by_same_thesis_twice_is_still_refused(ledger):
    """Spend-once means once, even for the thesis that spent it."""
    led, lineage_id = ledger
    assert led.spend(lineage_id, "th_a") == SpendOutcome.GRANTED
    assert led.spend(lineage_id, "th_a") == SpendOutcome.REFUSED


def test_concurrent_spends_grant_exactly_one(ledger):
    led, lineage_id = ledger
    attempts = 16
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda i: led.spend(lineage_id, f"th_{i}"), range(attempts)))

    granted = [o for o in outcomes if o == SpendOutcome.GRANTED]
    refused = [o for o in outcomes if o == SpendOutcome.REFUSED]
    assert len(granted) == 1, "exactly one concurrent spend must win"
    assert len(refused) == attempts - 1
    assert len(led.refusals(lineage_id)) == attempts - 1


def test_spend_on_unknown_lineage_is_an_error(ledger):
    led, _ = ledger
    with pytest.raises(LookupError, match="no evaluation ledger row"):
        led.spend("lin_missing", "th_x")
