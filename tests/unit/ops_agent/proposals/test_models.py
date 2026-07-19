from __future__ import annotations

import pytest
from pydantic import ValidationError

from ops_agent.proposals.models import (
    DataSourceDescriptor,
    EndpointSpec,
    OnboardingLimitation,
    ProvisioningDraft,
)


def test_provisioning_draft_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ProvisioningDraft.model_validate(
            {"provider_id": "x", "rationale": "why", "unexpected_field": 1}
        )


def test_provisioning_draft_requires_a_non_empty_rationale():
    with pytest.raises(ValidationError):
        ProvisioningDraft.model_validate({"provider_id": "x", "rationale": ""})


def test_data_source_descriptor_requires_at_least_one_endpoint():
    with pytest.raises(ValidationError):
        DataSourceDescriptor.model_validate(
            {
                "provider_id": "vendor",
                "credential": {"env_var_name": "X", "purpose": "market_data"},
                "base_url": "https://example.test",
                "endpoints": [],
            }
        )


def test_data_source_descriptor_accepts_a_minimal_valid_shape():
    descriptor = DataSourceDescriptor.model_validate(
        {
            "provider_id": "vendor",
            "credential": {"env_var_name": "X", "purpose": "market_data"},
            "base_url": "https://example.test",
            "endpoints": [
                {
                    "category": "spot",
                    "path_template": "/v1/{instrument_key}",
                    "field_mapping": {"instrument_key": "id"},
                }
            ],
        }
    )
    assert descriptor.connector_kind == "declarative"
    assert descriptor.pagination.mode == "none"
    assert isinstance(descriptor.endpoints[0], EndpointSpec)


def test_onboarding_limitation_requires_a_reason():
    with pytest.raises(ValidationError):
        OnboardingLimitation.model_validate(
            {"provider_id": "x", "reason": "", "unsupported_aspect": "auth"}
        )
