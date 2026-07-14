"""Strict layered configuration resolution for the trendline-family model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields
import math
from pathlib import Path
from typing import Any, Mapping

from .config import CandidateConfig, EventsConfig, InteractionConfig, LifecycleConfig, MatchingConfig, MTFConfig, ModelConfig, RailsConfig, RankingConfig, RepositoryConfig, ResolvedTrendlineFamilyConfig, RuntimeConfig, TrendlineFamilyConfig
from .config_loader import load_trendline_family_config
from .contracts import ContractValidationError


_SECTIONS = {"model": ModelConfig, "candidate": CandidateConfig, "matching": MatchingConfig, "lifecycle": LifecycleConfig,
             "interaction": InteractionConfig, "events": EventsConfig, "rails": RailsConfig, "mtf": MTFConfig, "ranking": RankingConfig, "repository": RepositoryConfig, "runtime": RuntimeConfig}
_ROOT_KEYS = {"version", "model", "defaults", "timeframes", "assets"}


def _as_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _version(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ContractValidationError("config version must be a non-empty scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError("config version must be finite")
    result = str(value).strip()
    if not result:
        raise ContractValidationError("config version must be non-empty")
    return result


def _validate_sections(value: Mapping[str, Any], *, path: str, allow_model: bool = True) -> None:
    allowed = set(_SECTIONS)
    if not allow_model:
        allowed.remove("model")
    unknown = set(value) - allowed
    if unknown:
        raise ContractValidationError(f"unknown config key(s) at {path}: {sorted(unknown)}")
    for section, section_value in value.items():
        mapping = _as_mapping(section_value, path=f"{path}.{section}")
        unknown_fields = set(mapping) - {item.name for item in fields(_SECTIONS[section])}
        if unknown_fields:
            raise ContractValidationError(f"unknown config key(s) at {path}.{section}: {sorted(unknown_fields)}")


def _validate_raw_config(raw: Mapping[str, Any]) -> None:
    unknown = set(raw) - _ROOT_KEYS
    if unknown:
        raise ContractValidationError(f"unknown config root key(s): {sorted(unknown)}")
    if "version" not in raw:
        raise ContractValidationError("config version is required")
    _version(raw["version"])
    if "defaults" in raw:
        _validate_sections(_as_mapping(raw["defaults"], path="defaults"), path="defaults", allow_model=False)
    if "model" in raw:
        _validate_sections({"model": raw["model"]}, path="model")
    for timeframe, override in _as_mapping(raw.get("timeframes", {}), path="timeframes").items():
        if not timeframe:
            raise ContractValidationError("timeframe override key must not be empty")
        _validate_sections(_as_mapping(override, path=f"timeframes.{timeframe}"), path=f"timeframes.{timeframe}", allow_model=False)
    for asset, asset_block in _as_mapping(raw.get("assets", {}), path="assets").items():
        if not asset:
            raise ContractValidationError("asset override key must not be empty")
        block = _as_mapping(asset_block, path=f"assets.{asset}")
        unknown_asset_keys = set(block) - {"defaults", "timeframes"}
        if unknown_asset_keys:
            raise ContractValidationError(f"unknown config key(s) at assets.{asset}: {sorted(unknown_asset_keys)}")
        if "defaults" in block:
            _validate_sections(_as_mapping(block["defaults"], path=f"assets.{asset}.defaults"), path=f"assets.{asset}.defaults", allow_model=False)
        for timeframe, override in _as_mapping(block.get("timeframes", {}), path=f"assets.{asset}.timeframes").items():
            if not timeframe:
                raise ContractValidationError("asset timeframe override key must not be empty")
            _validate_sections(_as_mapping(override, path=f"assets.{asset}.timeframes.{timeframe}"), path=f"assets.{asset}.timeframes.{timeframe}", allow_model=False)


def _merge_layer(base: dict[str, Any], override: Mapping[str, Any], provenance: dict[str, str], *, source: str) -> None:
    for section, values in override.items():
        for field_name, value in _as_mapping(values, path=section).items():
            base[section][field_name] = value
            provenance[f"{section}.{field_name}"] = source


def _fallback_mapping() -> dict[str, Any]:
    config = TrendlineFamilyConfig()
    return {section: asdict(getattr(config, section)) for section in _SECTIONS}


def _config_from_mapping(value: Mapping[str, Any]) -> TrendlineFamilyConfig:
    try:
        return TrendlineFamilyConfig(model=ModelConfig(**value["model"]), candidate=CandidateConfig(**value["candidate"]),
            matching=MatchingConfig(**value["matching"]), lifecycle=LifecycleConfig(**value["lifecycle"]),
            interaction=InteractionConfig(**value["interaction"]), events=EventsConfig(**value["events"]), rails=RailsConfig(**value["rails"]), mtf=MTFConfig(**value["mtf"]), ranking=RankingConfig(**value["ranking"]),
            repository=RepositoryConfig(**value["repository"]), runtime=RuntimeConfig(**value["runtime"]))
    except ContractValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError("invalid resolved trendline-family configuration") from exc


class TrendlineFamilyConfigResolver:
    """Resolve documented fallback-to-runtime-override precedence with strict values."""

    def __init__(self, raw_config: Mapping[str, Any]) -> None:
        self._raw_config = deepcopy(dict(_as_mapping(raw_config, path="config")))
        _validate_raw_config(self._raw_config)

    @classmethod
    def from_path(cls, path: str | Path) -> "TrendlineFamilyConfigResolver":
        return cls(load_trendline_family_config(path))

    def resolve(self, *, asset: str, timeframe: str, runtime_override: Mapping[str, Any] | None = None) -> ResolvedTrendlineFamilyConfig:
        if not isinstance(asset, str) or not asset or not isinstance(timeframe, str) or not timeframe:
            raise ContractValidationError("asset and timeframe must be non-empty strings")
        base = _fallback_mapping()
        provenance = {f"{section}.{field_name}": "schema_fallback" for section, values in base.items() for field_name in values}
        raw = self._raw_config
        if "model" in raw:
            _merge_layer(base, {"model": raw["model"]}, provenance, source="yaml_model")
        _merge_layer(base, raw.get("defaults", {}), provenance, source="yaml_defaults")
        _merge_layer(base, raw.get("timeframes", {}).get(timeframe, {}), provenance, source=f"timeframe:{timeframe}")
        asset_config = raw.get("assets", {}).get(asset, {})
        _merge_layer(base, asset_config.get("defaults", {}), provenance, source=f"asset:{asset}")
        _merge_layer(base, asset_config.get("timeframes", {}).get(timeframe, {}), provenance, source=f"asset_timeframe:{asset}:{timeframe}")
        if runtime_override is not None:
            override = _as_mapping(runtime_override, path="runtime_override")
            _validate_sections(override, path="runtime_override")
            _merge_layer(base, override, provenance, source="runtime_override")
        return ResolvedTrendlineFamilyConfig.create(asset=asset, timeframe=timeframe, config_version=_version(raw["version"]),
            config=_config_from_mapping(base), field_provenance=provenance)
