from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import inspect
from pathlib import Path

import pytest

from libs.models.trendline_v2.configuration import (
    BodyValidationPolicy,
    ConfirmedExtremaPairConfig,
    FieldClassification,
    HistoryHorizon,
    PairEnumerationOrder,
    PlateauPolicy,
    provider_field_policies,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.discovery import (
    ConfirmedExtremaPairEvidence,
    ExtremaKind,
    ProviderInput,
    ProviderRequest,
)
from libs.models.trendline_v2.domain.validation import ContractValidationError


UTC = timezone.utc


def _provider_config(**changes) -> ConfirmedExtremaPairConfig:
    values = {
        "provider_name": "confirmed_extrema_pair",
        "provider_version": "v1",
        "plateau_policy": PlateauPolicy.LEFTMOST_STRICT_LEFT_NONSTRICT_RIGHT_V1,
        "history_horizon": HistoryHorizon.LOOKBACK_DURATION_SECONDS_V1,
        "lookback_duration_seconds": 86_400.0,
        "left_confirmation_bars": 2,
        "right_confirmation_bars": 2,
        "min_extrema_per_role": 2,
        "body_validation_policy": BodyValidationPolicy.EXACT_SIDE_V1,
        "pair_enumeration_order": PairEnumerationOrder.CHRONOLOGICAL_V1,
        "candidate_order_version": "candidate_order_v1",
        "structural_validation_version": "exact_side_v1",
        "max_hypotheses": 100,
        "max_output_candidates": 20,
        "provider_evidence_schema_version": "v1",
    }
    values.update(changes)
    return ConfirmedExtremaPairConfig(**values)


def _foundation_config():
    return resolve_trendline_v2_config(
        {
            "model": {
                "name": "trendline_v2",
                "version": "foundation_v1",
                "schema_version": 1,
            }
        }
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
        "coordinate_system_version": "elapsed_utc_seconds_v1",
        "plateau_policy_version": "leftmost_strict_left_nonstrict_right_v1",
        "schema_version": "v1",
    }
    values.update(changes)
    return ConfirmedExtremaPairEvidence(**values)


def test_provider_config_has_no_python_defaults() -> None:
    parameters = inspect.signature(ConfirmedExtremaPairConfig).parameters
    assert parameters
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters.values())


def test_provider_field_policy_is_complete_unique_and_yaml_inactive() -> None:
    policies = provider_field_policies()
    names = {policy.name for policy in policies}
    assert len(names) == len(policies)
    assert names == {
        "provider.name",
        "provider.version",
        "provider.plateau_policy",
        "provider.history_horizon",
        "provider.lookback_duration_seconds",
        "provider.left_confirmation_bars",
        "provider.right_confirmation_bars",
        "provider.min_extrema_per_role",
        "provider.body_validation_policy",
        "provider.pair_enumeration_order",
        "provider.candidate_order_version",
        "provider.structural_validation_version",
        "provider.max_hypotheses",
        "provider.max_output_candidates",
        "provider.provider_evidence_schema_version",
    }
    assert all(not policy.yaml_participation for policy in policies)
    assert all(policy.hash_participation for policy in policies)
    assert {
        policy.classification for policy in policies
    } >= {FieldClassification.INVARIANT, FieldClassification.UNRESOLVED}


def test_unresolved_provider_fields_cannot_enter_canonical_yaml() -> None:
    raw = {
        "model": {
            "name": "trendline_v2",
            "version": "foundation_v1",
            "schema_version": 1,
        },
        "provider": _provider_config().to_dict(),
    }
    with pytest.raises(ContractValidationError):
        resolve_trendline_v2_config(raw)


def test_provider_config_identity_changes_for_semantic_values_and_schema() -> None:
    config = _provider_config()
    assert replace(config, max_hypotheses=101).semantic_hash != config.semantic_hash
    assert (
        replace(config, max_output_candidates=21).semantic_hash
        != config.semantic_hash
    )
    assert (
        replace(config, provider_evidence_schema_version="v2").provider_contract_identity
        != config.provider_contract_identity
    )


def test_provider_config_rejects_unknown_or_invalid_semantics() -> None:
    with pytest.raises(ContractValidationError):
        _provider_config(lookback_duration_seconds=0)
    with pytest.raises(ContractValidationError):
        _provider_config(max_hypotheses=True)
    with pytest.raises(ContractValidationError):
        _provider_config(body_validation_policy="raw_price_v1")
    with pytest.raises(ContractValidationError):
        _provider_config(plateau_policy="future_aware")


def test_request_requires_typed_provider_config_and_binds_identity() -> None:
    request = ProviderRequest(
        input_data=_input(),
        config=_foundation_config(),
        provider_config=_provider_config(),
    )
    changed = ProviderRequest(
        input_data=request.input_data,
        config=request.config,
        provider_config=replace(request.provider_config, max_hypotheses=101),
    )
    assert changed.provider_config_identity != request.provider_config_identity
    assert changed.config_identity != request.config_identity
    assert changed.request_identity != request.request_identity
    with pytest.raises(ContractValidationError):
        ProviderRequest(
            input_data=_input(),
            config=_foundation_config(),
            provider_config={},
        )


def test_evidence_round_trips_and_is_immutable() -> None:
    evidence = _evidence()
    assert ConfirmedExtremaPairEvidence.from_dict(evidence.to_dict()) == evidence
    evidence.validate_against(_input())
    assert isinstance(evidence.anchor_source_positions, tuple)
    with pytest.raises((AttributeError, TypeError)):
        evidence.anchor_source_positions = (0, 1)


@pytest.mark.parametrize(
    "changes",
    [
        {"anchor_source_positions": (-1, 2)},
        {"anchor_source_positions": (2, 1)},
        {"confirmation_positions": (1, 1)},
        {"confirmation_positions": (0, 3)},
        {"body_violation_count": -1},
        {"coordinate_system_version": "bar_index_v1"},
        {"plateau_policy_version": "future_aware"},
        {"schema_version": "v2"},
    ],
)
def test_evidence_rejects_malformed_values(changes) -> None:
    with pytest.raises(ContractValidationError):
        _evidence(**changes)


def test_evidence_rejects_future_confirmation_positions() -> None:
    evidence = _evidence(confirmation_positions=(1, 4))
    with pytest.raises(ContractValidationError, match="future"):
        evidence.validate_against(_input())


def test_evidence_id_rejects_rebound_payload() -> None:
    payload = _evidence().to_dict()
    payload["validated_intermediate_count"] = 2
    with pytest.raises(ContractValidationError, match="ID"):
        ConfirmedExtremaPairEvidence.from_dict(payload)


def test_provider_algorithm_and_viewer_scopes_are_absent() -> None:
    package_root = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_v2"
    assert not (package_root / "discovery" / "providers").exists()
    assert not (package_root / "discovery" / "kernels").exists()
    assert not (package_root / "viewer").exists()
