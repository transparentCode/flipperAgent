from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import inspect
from pathlib import Path

import pytest

from libs.models.trendline_v2.configuration import (
    BODY_VALIDATION_POLICY,
    COORDINATE_SYSTEM,
    EVIDENCE_SCHEMA_VERSION,
    HISTORY_POLICY,
    PAIR_ORDER,
    PLATEAU_POLICY,
    PROVIDER_NAME,
    PROVIDER_VERSION,
    ConfirmedExtremaPairConfig,
    FieldClassification,
    provider_field_policies,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import ProviderInput, ProviderRequest
from libs.models.trendline_v2.discovery.provider_evidence import (
    ConfirmedExtremaPairEvidence,
    ExtremaKind,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc


def _provider_config(**changes) -> ConfirmedExtremaPairConfig:
    values = {
        "lookback_duration_seconds": 86_400.0,
        "left_confirmation_bars": 2,
        "right_confirmation_bars": 2,
        "min_extrema_per_role": 2,
        "max_hypotheses": 100,
        "max_output_candidates": 20,
    }
    values.update(changes)
    return ConfirmedExtremaPairConfig(**values)


def _foundation_config():
    return resolve_trendline_v2_config(
        {"model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1}}
    )


def _input() -> ProviderInput:
    timestamps = tuple(
        int(datetime(2024, 1, 1, hour, tzinfo=UTC).timestamp() * 1_000_000_000)
        for hour in range(4)
    )
    return ProviderInput(
        asset="BTCUSDT",
        timeframe="4h",
        observed_at=datetime(2024, 1, 2, tzinfo=UTC),
        confirmed_through=datetime(2024, 1, 1, 3, tzinfo=UTC),
        timestamps=timestamps,
        open=(100.0, 101.0, 102.0, 103.0),
        high=(101.0, 102.0, 103.0, 104.0),
        low=(99.0, 100.0, 101.0, 102.0),
        close=(100.5, 101.5, 102.5, 103.5),
        volume=(10.0, 11.0, 12.0, 13.0),
    )


def _evidence(**changes) -> ConfirmedExtremaPairEvidence:
    values = {
        "candidate_id": "0" * 64,
        "extrema_kind": ExtremaKind.LOW,
        "anchor_source_positions": (0, 2),
        "confirmation_positions": (1, 3),
        "validated_intermediate_count": 1,
        "body_violation_count": 0,
    }
    values.update(changes)
    return ConfirmedExtremaPairEvidence(**values)


def test_provider_config_has_only_active_fields_without_defaults() -> None:
    parameters = inspect.signature(ConfirmedExtremaPairConfig).parameters
    assert tuple(parameters) == (
        "lookback_duration_seconds",
        "left_confirmation_bars",
        "right_confirmation_bars",
        "min_extrema_per_role",
        "max_hypotheses",
        "max_output_candidates",
    )
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters.values())


def test_provider_v1_semantics_are_code_owned_and_hashed() -> None:
    config = _provider_config()
    assert config.provider_name == PROVIDER_NAME == "confirmed_extrema_pair"
    assert config.provider_version == PROVIDER_VERSION == "v1"
    assert config.provider_evidence_schema_version == EVIDENCE_SCHEMA_VERSION == "v1"
    assert config.semantic_payload["provider"] == {
        "name": PROVIDER_NAME,
        "version": PROVIDER_VERSION,
        "plateau_policy": PLATEAU_POLICY,
        "history_policy": HISTORY_POLICY,
        "body_validation_policy": BODY_VALIDATION_POLICY,
        "pair_order": PAIR_ORDER,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "coordinate_system": COORDINATE_SYSTEM,
    }
    assert config.to_dict()["semantic_hash"] == config.semantic_hash


def test_provider_field_policy_contains_only_active_unresolved_fields() -> None:
    policies = provider_field_policies()
    assert tuple(policy.name for policy in policies) == (
        "provider.lookback_duration_seconds",
        "provider.left_confirmation_bars",
        "provider.right_confirmation_bars",
        "provider.min_extrema_per_role",
        "provider.max_hypotheses",
        "provider.max_output_candidates",
    )
    assert all(policy.classification is FieldClassification.UNRESOLVED for policy in policies)
    assert all(not policy.yaml_participation and policy.hash_participation for policy in policies)


def test_provider_config_identity_changes_for_each_active_value() -> None:
    config = _provider_config()
    for field_name, replacement in (
        ("lookback_duration_seconds", 43_200.0),
        ("left_confirmation_bars", 3),
        ("right_confirmation_bars", 3),
        ("min_extrema_per_role", 3),
        ("max_hypotheses", 101),
        ("max_output_candidates", 21),
    ):
        assert replace(config, **{field_name: replacement}).semantic_hash != config.semantic_hash


@pytest.mark.parametrize(
    "changes",
    [
        {"lookback_duration_seconds": 0},
        {"left_confirmation_bars": True},
        {"right_confirmation_bars": 0},
        {"min_extrema_per_role": 1},
        {"max_hypotheses": 0},
        {"max_output_candidates": 0},
    ],
)
def test_provider_config_rejects_invalid_active_values(changes) -> None:
    with pytest.raises(ContractValidationError):
        _provider_config(**changes)


def test_provider_config_stays_outside_canonical_yaml() -> None:
    raw = {
        "model": {"name": "trendline_v2", "version": "foundation_v1", "schema_version": 1},
        "provider": _provider_config().to_dict(),
    }
    with pytest.raises(ContractValidationError):
        resolve_trendline_v2_config(raw)


def test_request_binds_typed_provider_config_identity() -> None:
    request = ProviderRequest(
        input_data=_input(), config=_foundation_config(), provider_config=_provider_config()
    )
    changed = ProviderRequest(
        input_data=request.input_data,
        config=request.config,
        provider_config=replace(request.provider_config, max_hypotheses=101),
    )
    assert changed.provider_config_identity != request.provider_config_identity
    assert changed.request_identity != request.request_identity


def test_evidence_accepts_only_dynamic_values_and_serializes_fixed_semantics() -> None:
    evidence = _evidence()
    assert ConfirmedExtremaPairEvidence.from_dict(evidence.to_dict()) == evidence
    assert evidence.coordinate_system_version == COORDINATE_SYSTEM
    assert evidence.plateau_policy_version == PLATEAU_POLICY
    assert evidence.schema_version == EVIDENCE_SCHEMA_VERSION
    assert "coordinate_system_version" not in inspect.signature(ConfirmedExtremaPairEvidence).parameters
    evidence.validate_against(_input())


@pytest.mark.parametrize(
    "changes",
    [
        {"anchor_source_positions": (-1, 2)},
        {"anchor_source_positions": (2, 1)},
        {"confirmation_positions": (1, 1)},
        {"confirmation_positions": (0, 3)},
        {"body_violation_count": -1},
    ],
)
def test_evidence_rejects_malformed_dynamic_values(changes) -> None:
    with pytest.raises(ContractValidationError):
        _evidence(**changes)


def test_evidence_rejects_rebound_fixed_semantics_or_id() -> None:
    payload = _evidence().to_dict()
    payload["schema_version"] = "v2"
    with pytest.raises(ContractValidationError, match="fixed semantics"):
        ConfirmedExtremaPairEvidence.from_dict(payload)
    payload = _evidence().to_dict()
    payload["validated_intermediate_count"] = 2
    with pytest.raises(ContractValidationError, match="ID"):
        ConfirmedExtremaPairEvidence.from_dict(payload)


def test_no_provider_framework_or_viewer_exists() -> None:
    package_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    assert not (package_root / "discovery" / "providers").exists()
    assert not (package_root / "discovery" / "kernels").exists()
    assert not (package_root / "viewer").exists()
