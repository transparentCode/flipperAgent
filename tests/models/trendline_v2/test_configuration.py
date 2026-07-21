from __future__ import annotations

from pathlib import Path

import pytest

from libs.models.trendline_v2.configuration import (
    FieldClassification,
    field_policies,
    load_trendline_v2_config,
    resolve_trendline_v2_config,
)
from libs.models.trendline_v2.configuration.derived import derive_timeframe_duration_seconds
from libs.models.trendline_v2.domain.validation import ContractValidationError


CONFIG_PATH = Path(__file__).parents[3] / "configs" / "trendline_v2.yaml"


def _raw() -> dict:
    return {
        "model": {
            "name": "trendline_v2",
            "version": "foundation_v1",
            "schema_version": 1,
        }
    }


def test_canonical_yaml_is_complete_and_provenance_is_total() -> None:
    config = load_trendline_v2_config(CONFIG_PATH)
    assert config.model_name == "trendline_v2"
    assert set(config.provenance) == {
        "model.name",
        "model.version",
        "model.schema_version",
    }
    assert "runtime" not in config.to_dict()
    assert config.semantic_hash == config.configuration_fingerprint


def test_runtime_placeholder_fields_are_rejected() -> None:
    raw = _raw()
    raw["runtime"] = {"backend": "python", "debug": False}
    with pytest.raises(ContractValidationError):
        resolve_trendline_v2_config(raw)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["model"].pop("version"),
        lambda value: value["model"].update({"schema_version": True}),
        lambda value: value.update({"candidate": {"lookback": 10}}),
        lambda value: value["model"].update({"name": 1}),
    ],
)
def test_config_rejects_incomplete_unknown_and_incompatible_fields(mutator) -> None:
    raw = _raw()
    mutator(raw)
    with pytest.raises(ContractValidationError):
        resolve_trendline_v2_config(raw)


def test_field_policy_classification_is_unique_and_runtime_is_not_owned() -> None:
    policies = field_policies()
    assert len({policy.name for policy in policies}) == len(policies)
    assert all(isinstance(policy.classification, FieldClassification) for policy in policies)
    assert {policy.name for policy in policies} == {
        "model.name",
        "model.version",
        "model.schema_version",
    }


def test_derived_timeframe_requires_explicit_valid_input() -> None:
    assert derive_timeframe_duration_seconds("4h") == 14_400
    assert derive_timeframe_duration_seconds("90m") == 5_400
    with pytest.raises(ContractValidationError):
        derive_timeframe_duration_seconds("4")
