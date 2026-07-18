"""Contract test: multiplicity control is mandatory and non-disableable
(FR-030, SC-011, spec Clarification Q4)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from energy_research.config.settings import ScreeningConfig
from energy_research.screening import multiplicity


class TestConfigSchemaCannotDisableMultiplicity:
    def test_rejects_none_as_method(self):
        for value in ("none", "off", "disabled", ""):
            with pytest.raises(ValidationError):
                ScreeningConfig(multiplicity_method=value)

    def test_rejects_extra_disable_flags(self):
        with pytest.raises(ValidationError):
            ScreeningConfig(disable_multiplicity=True)
        with pytest.raises(ValidationError):
            ScreeningConfig(multiplicity_enabled=False)

    def test_default_is_an_active_method(self):
        assert ScreeningConfig().multiplicity_method == "benjamini_hochberg"

    def test_apply_refuses_unknown_method(self):
        with pytest.raises(ValueError, match="multiplicity control is mandatory"):
            multiplicity.apply("none", [0.01], alpha=0.1)


class TestScreeningAlwaysAppliesAdjustedThreshold:
    """The service never applies an unadjusted per-thesis threshold: for a family
    of m > 1 theses, the recorded bar is strictly below the raw alpha unless the
    whole family clears BH at its top rank."""

    def _run_screening(self, tmp_path, alpha=0.10):
        from energy_research.orchestration.cycle import run_cycle
        from energy_research.orchestration.ingest import ingest_all
        from tests.conftest import build_config

        config = build_config(tmp_path, screening=ScreeningConfig(n_bootstrap=200, alpha=alpha))
        ingest_all(config)
        result = run_cycle(config)
        from energy_research.datastore.repository import Repository

        repo = Repository(config.datastore.db_path, config.datastore.lake_dir)
        try:
            rows = []
            for thesis in repo.theses_for_cycle(result.cycle_id):
                screening = repo.screening_result_for(thesis["thesis_id"])
                if screening is not None:
                    rows.append(screening)
        finally:
            repo.close()
        return rows, alpha

    def test_every_result_records_an_adjusted_threshold(self, tmp_path):
        rows, alpha = self._run_screening(tmp_path)
        assert len(rows) > 1, "need a multi-thesis family to exercise multiplicity"
        for row in rows:
            assert row["multiplicity_method"] == "benjamini_hochberg"
            # Family-corrected bar: at or below alpha, never an uncorrected
            # per-thesis alpha and never absent.
            assert 0 < row["adjusted_threshold"] <= alpha
            assert f"{row['multiplicity_method']}-adjusted" in row["reason"]

    def test_pass_verdicts_respect_the_adjusted_bar(self, tmp_path):
        rows, _ = self._run_screening(tmp_path)
        for row in rows:
            if row["verdict"] == "pass":
                assert row["p_value"] <= row["adjusted_threshold"]
            else:
                assert row["p_value"] > row["adjusted_threshold"]
