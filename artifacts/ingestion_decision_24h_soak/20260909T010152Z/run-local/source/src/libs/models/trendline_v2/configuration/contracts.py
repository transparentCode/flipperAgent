"""Immutable resolved configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..domain.identity import deterministic_hash
from ..domain.validation import ContractValidationError, require_string


@dataclass(frozen=True, slots=True)
class ResolvedTrendlineV2Config:
    model_name: str
    model_version: str
    schema_version: int
    provenance: Mapping[str, str]

    def __post_init__(self) -> None:
        model_name = require_string(self.model_name, field_name="model.name")
        model_version = require_string(self.model_version, field_name="model.version")
        if model_name != "trendline_v2":
            raise ContractValidationError("model.name must be trendline_v2")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise ContractValidationError("model.schema_version must be an integer")
        if self.schema_version != 1:
            raise ContractValidationError("unsupported model.schema_version")
        provenance = dict(self.provenance)
        expected = {"model.name", "model.version", "model.schema_version"}
        if set(provenance) != expected or any(not isinstance(value, str) or not value for value in provenance.values()):
            raise ContractValidationError("configuration provenance must cover every field exactly")
        object.__setattr__(self, "model_name", model_name)
        object.__setattr__(self, "model_version", model_version)
        object.__setattr__(self, "provenance", MappingProxyType(provenance))

    @property
    def semantic_payload(self) -> dict[str, Any]:
        return {
            "model": {
                "name": self.model_name,
                "version": self.model_version,
                "schema_version": self.schema_version,
            }
        }

    @property
    def semantic_hash(self) -> str:
        return deterministic_hash("trendline_v2_configuration", self.semantic_payload)

    @property
    def configuration_fingerprint(self) -> str:
        return self.semantic_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": {
                "name": self.model_name,
                "version": self.model_version,
                "schema_version": self.schema_version,
            },
            "provenance": dict(self.provenance),
            "semantic_hash": self.semantic_hash,
        }


__all__ = ["ResolvedTrendlineV2Config"]
