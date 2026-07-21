"""Strict layered configuration resolution for the trendline-family model."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, fields
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..domain.validation import ContractValidationError
from .contracts import CandidateConfig, EventsConfig, InteractionConfig, LifecycleConfig, MatchingConfig, MTFConfig, ModelConfig, RailsConfig, RankingConfig, RepositoryConfig, ResolvedTrendlineFamilyConfig, RuntimeConfig, TrendlineFamilyConfig
from .field_policy import ConfigScope, FIELD_POLICIES, validate_field_scope
from .loader import load_trendline_family_config


_SECTIONS = {"model": ModelConfig, "candidate": CandidateConfig, "matching": MatchingConfig, "lifecycle": LifecycleConfig,
             "interaction": InteractionConfig, "events": EventsConfig, "rails": RailsConfig, "mtf": MTFConfig, "ranking": RankingConfig, "repository": RepositoryConfig, "runtime": RuntimeConfig}
_ROOT_KEYS = {"profile_id", "profile_version", "version", "model", "defaults", "timeframes", "assets"}


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass(frozen=True)
class TrendlineConfigScope:
    """Explicit resolution scope. Empty values are invalid, None means global."""

    asset: str | None = None
    timeframe: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("asset", self.asset), ("timeframe", self.timeframe)):
            if value is not None and (not isinstance(value, str) or not value):
                raise ContractValidationError(f"configuration scope {name} must be a non-empty string or None")


@dataclass(frozen=True)
class TrendlineConfigPatch:
    """Partial validated override; omitted fields use UNSET, never None."""

    values: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        copied = deepcopy(dict(_as_mapping(self.values, path="config_patch")))
        _validate_sections(copied, path="config_patch", scope=ConfigScope.RESEARCH_OVERRIDE)
        for section, fields_map in copied.items():
            if any(value is UNSET or value is None for value in fields_map.values()):
                raise ContractValidationError(
                    f"config_patch.{section} values must be explicit; use omitted fields for UNSET"
                )
        object.__setattr__(self, "values", _freeze_mapping(copied))


def _as_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


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


def _version(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ContractValidationError("config version must be a non-empty scalar")
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError("config version must be finite")
    result = str(value).strip()
    if not result:
        raise ContractValidationError("config version must be non-empty")
    return result


def _validate_sections(
    value: Mapping[str, Any],
    *,
    path: str,
    scope: ConfigScope,
    allow_model: bool = True,
) -> None:
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
        for field_name in mapping:
            validate_field_scope(f"{section}.{field_name}", scope)


def _validate_raw_config(raw: Mapping[str, Any]) -> None:
    unknown = set(raw) - _ROOT_KEYS
    if unknown:
        raise ContractValidationError(f"unknown config root key(s): {sorted(unknown)}")
    if "version" not in raw:
        raise ContractValidationError("config version is required")
    _version(raw["version"])
    if "profile_id" in raw:
        _profile_value(raw["profile_id"], field_name="profile_id")
    if "profile_version" in raw:
        _profile_value(raw["profile_version"], field_name="profile_version")
    if "defaults" in raw:
        _validate_sections(_as_mapping(raw["defaults"], path="defaults"), path="defaults", scope=ConfigScope.GLOBAL, allow_model=False)
    if "model" in raw:
        _validate_sections({"model": raw["model"]}, path="model", scope=ConfigScope.GLOBAL)
    for timeframe, override in _as_mapping(raw.get("timeframes", {}), path="timeframes").items():
        if not timeframe:
            raise ContractValidationError("timeframe override key must not be empty")
        _validate_sections(_as_mapping(override, path=f"timeframes.{timeframe}"), path=f"timeframes.{timeframe}", scope=ConfigScope.TIMEFRAME, allow_model=False)
    for asset, asset_block in _as_mapping(raw.get("assets", {}), path="assets").items():
        if not asset:
            raise ContractValidationError("asset override key must not be empty")
        block = _as_mapping(asset_block, path=f"assets.{asset}")
        unknown_asset_keys = set(block) - {"defaults", "timeframes"}
        if unknown_asset_keys:
            raise ContractValidationError(f"unknown config key(s) at assets.{asset}: {sorted(unknown_asset_keys)}")
        if "defaults" in block:
            _validate_sections(_as_mapping(block["defaults"], path=f"assets.{asset}.defaults"), path=f"assets.{asset}.defaults", scope=ConfigScope.ASSET, allow_model=False)
        for timeframe, override in _as_mapping(block.get("timeframes", {}), path=f"assets.{asset}.timeframes").items():
            if not timeframe:
                raise ContractValidationError("asset timeframe override key must not be empty")
            _validate_sections(_as_mapping(override, path=f"assets.{asset}.timeframes.{timeframe}"), path=f"assets.{asset}.timeframes.{timeframe}", scope=ConfigScope.ASSET_TIMEFRAME, allow_model=False)


def _validate_complete_semantic_profile(raw: Mapping[str, Any]) -> None:
    supplied = set(_field_values({"model": raw.get("model", {})}))
    supplied.update(_field_values(_as_mapping(raw.get("defaults", {}), path="defaults")))
    required = {policy.field for policy in FIELD_POLICIES if policy.semantic}
    missing = required - supplied
    if missing:
        raise ContractValidationError(f"canonical YAML semantic profile is incomplete: {sorted(missing)}")


def _merge_layer(base: dict[str, Any], override: Mapping[str, Any], provenance: dict[str, str], *, source: str) -> None:
    for section, values in override.items():
        for field_name, value in _as_mapping(values, path=section).items():
            base[section][field_name] = value
            provenance[f"{section}.{field_name}"] = source


def _profile_value(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def _field_values(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        f"{section}.{field_name}": field_value
        for section, section_values in value.items()
        for field_name, field_value in _as_mapping(section_values, path=section).items()
    }


def _merge_equal_specificity_scopes(
    base: dict[str, Any],
    *,
    asset: str,
    timeframe: str,
    asset_override: Mapping[str, Any],
    timeframe_override: Mapping[str, Any],
    pair_override: Mapping[str, Any],
    provenance: dict[str, str],
) -> None:
    """Merge one-dimensional scopes without hidden asset-over-timeframe ordering."""

    asset_fields = _field_values(asset_override)
    timeframe_fields = _field_values(timeframe_override)
    pair_fields = _field_values(pair_override)
    for field_name in sorted(set(asset_fields) | set(timeframe_fields)):
        asset_value = asset_fields.get(field_name, UNSET)
        timeframe_value = timeframe_fields.get(field_name, UNSET)
        if asset_value is UNSET:
            section, name = field_name.split(".", 1)
            base[section][name] = timeframe_value
            provenance[field_name] = f"timeframe:{timeframe}"
            continue
        if timeframe_value is UNSET:
            section, name = field_name.split(".", 1)
            base[section][name] = asset_value
            provenance[field_name] = f"asset:{asset}"
            continue
        if asset_value == timeframe_value:
            section, name = field_name.split(".", 1)
            base[section][name] = asset_value
            provenance[field_name] = f"asset_timeframe_agree:{asset}:{timeframe}"
            continue
        if field_name not in pair_fields:
            raise ContractValidationError(
                f"equal-specificity configuration conflict for {field_name}; "
                "asset and timeframe values differ without an asset_timeframe override"
            )
    _merge_layer(
        base,
        pair_override,
        provenance,
        source=f"asset_timeframe:{asset}:{timeframe}",
    )


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

    def __init__(self, raw_config: Mapping[str, Any], *, require_complete: bool = False) -> None:
        self._raw_config = deepcopy(dict(_as_mapping(raw_config, path="config")))
        _validate_raw_config(self._raw_config)
        if require_complete:
            _validate_complete_semantic_profile(self._raw_config)

    @classmethod
    def from_path(cls, path: str | Path) -> "TrendlineFamilyConfigResolver":
        config_path = Path(path)
        canonical_path = Path("configs/trendline_family.yaml")
        return cls(
            load_trendline_family_config(config_path),
            require_complete=config_path.resolve() == canonical_path.resolve(),
        )

    def resolve(
        self,
        *,
        asset: str,
        timeframe: str,
        runtime_override: Mapping[str, Any] | None = None,
        invocation_override: TrendlineConfigPatch | Mapping[str, Any] | None = None,
    ) -> ResolvedTrendlineFamilyConfig:
        if not isinstance(asset, str) or not asset or not isinstance(timeframe, str) or not timeframe:
            raise ContractValidationError("asset and timeframe must be non-empty strings")
        if runtime_override is not None and invocation_override is not None:
            raise ContractValidationError("runtime_override and invocation_override cannot both be supplied")
        base = _fallback_mapping()
        provenance = {f"{section}.{field_name}": "schema_fallback" for section, values in base.items() for field_name in values}
        raw = self._raw_config
        if "model" in raw:
            _merge_layer(base, {"model": raw["model"]}, provenance, source="yaml_model")
        _merge_layer(base, raw.get("defaults", {}), provenance, source="yaml_defaults")
        asset_config = raw.get("assets", {}).get(asset, {})
        _merge_equal_specificity_scopes(
            base,
            asset=asset,
            timeframe=timeframe,
            asset_override=asset_config.get("defaults", {}),
            timeframe_override=raw.get("timeframes", {}).get(timeframe, {}),
            pair_override=asset_config.get("timeframes", {}).get(timeframe, {}),
            provenance=provenance,
        )
        if runtime_override is not None:
            override = _as_mapping(runtime_override, path="runtime_override")
            _validate_sections(override, path="runtime_override", scope=ConfigScope.RESEARCH_OVERRIDE)
            _merge_layer(base, override, provenance, source="runtime_override")
        if invocation_override is not None:
            override = (
                invocation_override.values
                if isinstance(invocation_override, TrendlineConfigPatch)
                else _as_mapping(invocation_override, path="invocation_override")
            )
            _validate_sections(override, path="invocation_override", scope=ConfigScope.RESEARCH_OVERRIDE)
            _merge_layer(base, override, provenance, source="invocation_override")
        return ResolvedTrendlineFamilyConfig.create(
            asset=asset,
            timeframe=timeframe,
            config_version=_version(raw["version"]),
            config=_config_from_mapping(base),
            field_provenance=provenance,
            profile_id=_profile_value(raw.get("profile_id", "legacy_v1"), field_name="profile_id"),
            profile_version=_profile_value(
                raw.get("profile_version", _version(raw["version"])),
                field_name="profile_version",
            ),
        )
