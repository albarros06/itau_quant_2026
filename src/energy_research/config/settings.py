"""Pipeline configuration models (Constitution Principle VI).

Every market-, provider-, and threshold-specific value lives here as validated
configuration. Models use ``extra="forbid"`` so an unknown or misspelled key —
including any attempt to bolt on a "disable multiplicity" switch — is a visible
validation error, never a silently ignored fallback (spec Edge Case:
"Conflicting or unavailable configuration").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DataCategory = Literal["spot", "forward_curve", "hydrology", "interest_rate", "fx"]
ContextCategory = Literal["news", "hydrology_outlook", "macro_regime"]
SplitType = Literal["discovery", "refinement", "final_evaluation"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstrumentConfig(StrictModel):
    key: str
    category: DataCategory
    description: str = ""


ConnectorKind = Literal["python_module", "declarative"]


class MarketProviderEntry(StrictModel):
    provider_id: str
    categories: list[DataCategory] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)
    # "python_module" (default) preserves today's exact behavior: a module named
    # after provider_id under ingestion/providers/. "declarative" routes to the
    # one shared, config-driven connector instead (002 ops_agent, FR-016;
    # data-model.md "Registry extension") — no per-vendor code either way.
    connector_kind: ConnectorKind = "python_module"


class ContextProviderEntry(StrictModel):
    provider_id: str
    categories: list[ContextCategory] = Field(min_length=1)
    options: dict[str, Any] = Field(default_factory=dict)
    connector_kind: ConnectorKind = "python_module"


class ProvidersConfig(StrictModel):
    market_data: list[MarketProviderEntry] = Field(min_length=1)
    qualitative_context: list[ContextProviderEntry] = Field(default_factory=list)


class DatastoreConfig(StrictModel):
    db_path: Path = Path("data/research.sqlite")
    lake_dir: Path = Path("data/lake")
    reports_dir: Path = Path("data/reports")


class DataQualityConfig(StrictModel):
    freshness_tolerance_days: float = Field(gt=0)
    max_gap_days: int = Field(default=7, gt=0)
    outlier_zscore_threshold: float = Field(default=8.0, gt=0)


class SplitsConfig(StrictModel):
    discovery_fraction: float = Field(gt=0, lt=1)
    refinement_fraction: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _leaves_room_for_final_evaluation(self) -> SplitsConfig:
        if self.discovery_fraction + self.refinement_fraction >= 0.95:
            raise ValueError(
                "discovery_fraction + refinement_fraction must leave at least 5% of the "
                "history for the final_evaluation split"
            )
        return self


class ScreeningConfig(StrictModel):
    """Statistical screening standard (FR-016) with mandatory multiplicity control.

    ``multiplicity_method`` is a closed enum of real correction methods. There is no
    "none"/"off" member and ``extra="forbid"`` rejects any additional disable flag, so
    multiplicity control cannot be configured away (FR-030, SC-011).
    """

    method: Literal["block_bootstrap"] = "block_bootstrap"
    n_bootstrap: int = Field(default=400, ge=100)
    block_size: int = Field(default=10, ge=2)
    alpha: float = Field(default=0.10, gt=0, lt=1)
    multiplicity_method: Literal["benjamini_hochberg", "bonferroni"] = "benjamini_hochberg"


class BacktestingConfig(StrictModel):
    transaction_cost_bps: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    financing_annual_rate: float = Field(ge=0)
    underperform_net_return_threshold: float = 0.0
    promotion_net_return_threshold: float = 0.0


class RefinementConfig(StrictModel):
    max_refinement_depth_per_lineage: int = Field(ge=0)
    max_lineages_per_run: int = Field(ge=1)


class GenerationConfig(StrictModel):
    backend: Literal["deterministic_stub", "anthropic", "gemini"] = "deterministic_stub"
    model: str = "claude-opus-4-8"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_theses_per_cycle: int = Field(default=5, ge=1)


class ReproducibilityConfig(StrictModel):
    seed: int | None = None


class PipelineConfig(StrictModel):
    """Fully resolved run configuration; snapshotted verbatim onto each ResearchCycle."""

    providers_file: Path | None = None
    providers: ProvidersConfig
    datastore: DatastoreConfig = DatastoreConfig()
    instrument_universe: list[InstrumentConfig] = Field(min_length=1)
    data_quality: DataQualityConfig
    splits: SplitsConfig
    screening: ScreeningConfig
    backtesting: BacktestingConfig
    refinement: RefinementConfig
    generation: GenerationConfig = GenerationConfig()
    reproducibility: ReproducibilityConfig = ReproducibilityConfig()

    @property
    def universe_keys(self) -> list[str]:
        return [i.key for i in self.instrument_universe]

    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable snapshot persisted on the ResearchCycle (FR-029)."""
        return self.model_dump(mode="json")


def load_config(path: str | Path) -> PipelineConfig:
    """Load and validate a config file, merging the referenced providers file.

    Missing or invalid configuration raises a visible error (pydantic
    ``ValidationError`` / ``FileNotFoundError``); there are no hidden defaults for
    required sections (Constitution Principle VII).
    """
    path = Path(path)
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} did not parse to a mapping")
    if "providers" not in raw:
        providers_file = raw.get("providers_file")
        if providers_file is None:
            raise ValueError(f"config file {path} defines neither 'providers' nor 'providers_file'")
        providers_path = (path.parent / providers_file).resolve()
        raw["providers"] = yaml.safe_load(providers_path.read_text())
        raw["providers_file"] = providers_path
    return PipelineConfig.model_validate(raw)


def config_from_snapshot(snapshot: dict[str, Any]) -> PipelineConfig:
    """Rehydrate the exact configuration recorded on a ResearchCycle (FR-028/FR-029)."""
    return PipelineConfig.model_validate(snapshot)
