"""Fail-closed resolution for the explicit foundation schema."""

from __future__ import annotations

from typing import Any, Mapping

from ..domain.validation import ContractValidationError
from .contracts import ResolvedTrendlineV2Config

_MODEL_KEYS = frozenset({"name", "version", "schema_version"})
_ROOT_KEYS = frozenset({"model"})


def _mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{field_name} must be a string-keyed mapping")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, field_name: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(set(value) - expected)
        raise ContractValidationError(f"{field_name} keys mismatch; missing={missing}, extra={extra}")


def resolve_trendline_v2_config(raw: Mapping[str, Any]) -> ResolvedTrendlineV2Config:
    root = _mapping(raw, field_name="trendline_v2 config")
    _exact_keys(root, _ROOT_KEYS, field_name="trendline_v2 config")
    model = _mapping(root["model"], field_name="model")
    _exact_keys(model, _MODEL_KEYS, field_name="model")
    if not isinstance(model["name"], str) or not model["name"]:
        raise ContractValidationError("model.name must be a non-empty string")
    if not isinstance(model["version"], str) or not model["version"]:
        raise ContractValidationError("model.version must be a non-empty string")
    if isinstance(model["schema_version"], bool) or not isinstance(model["schema_version"], int):
        raise ContractValidationError("model.schema_version must be an integer")
    return ResolvedTrendlineV2Config(
        model_name=model["name"],
        model_version=model["version"],
        schema_version=model["schema_version"],
        provenance={key: "canonical_yaml" for key in (
            "model.name", "model.version", "model.schema_version"
        )},
    )


__all__ = ["resolve_trendline_v2_config"]
