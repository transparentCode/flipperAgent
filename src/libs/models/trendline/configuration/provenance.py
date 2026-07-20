"""Deterministic configuration provenance for run and research manifests."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ContractValidationError
from .contracts import ResolvedTrendlineFamilyConfig


@dataclass(frozen=True)
class ConfigSource:
    """One deterministic configuration source applied during resolution."""

    source_id: str
    scope: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ContractValidationError("configuration source_id must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope:
            raise ContractValidationError("configuration source scope must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"source_id": self.source_id, "scope": self.scope}


def configuration_manifest(config: ResolvedTrendlineFamilyConfig) -> Mapping[str, Any]:
    """Return complete reproducibility metadata without changing domain IDs."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("configuration manifest requires ResolvedTrendlineFamilyConfig")
    values = config.to_dict()
    provenance = dict(config.field_provenance)
    payload = {
        "profile_id": config.profile_id,
        "profile_version": config.profile_version,
        "asset": config.asset,
        "timeframe": config.timeframe,
        "model_version": config.model_version,
        "config_version": config.config_version,
        "resolved_values": values,
        "field_provenance": provenance,
        "applied_sources": tuple(source.to_dict() for source in configuration_sources(config)),
        "resolved_config_hash": config.resolved_config_hash,
        "mtf_config_hash": config.mtf_config_hash,
    }
    return _freeze_mapping({**payload, "configuration_fingerprint": config.configuration_fingerprint})


def configuration_sources(config: ResolvedTrendlineFamilyConfig) -> tuple[ConfigSource, ...]:
    """Collapse field-level provenance into deterministic applied source records."""

    if not isinstance(config, ResolvedTrendlineFamilyConfig):
        raise ContractValidationError("configuration sources require ResolvedTrendlineFamilyConfig")
    return tuple(
        ConfigSource(source_id=source, scope=source)
        for source in sorted(set(config.field_provenance.values()))
    )


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            frozen[key] = _freeze_mapping(item)
        elif isinstance(item, list):
            frozen[key] = tuple(item)
        else:
            frozen[key] = item
    return MappingProxyType(frozen)


__all__ = ["ConfigSource", "configuration_manifest", "configuration_sources"]
