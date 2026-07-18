"""Strict raw-schema validation for the canonical SR configuration."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import Any, Mapping

from libs.models.sr.domain.errors import ContractValidationError

from .sections import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
    _string,
)


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class SRConfig:
    """Raw, deeply frozen, validated canonical SR configuration mapping."""

    version: str = "1"
    defaults: Mapping[str, Any] = field(default_factory=dict)
    timeframes: Mapping[str, Any] = field(default_factory=dict)
    assets: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "version", _string(self.version, field_name="version"))
        object.__setattr__(self, "defaults", _deep_freeze(self.defaults))
        object.__setattr__(self, "timeframes", _deep_freeze(self.timeframes))
        object.__setattr__(self, "assets", _deep_freeze(self.assets))
        _validate_raw_config(
            {
                "version": self.version,
                "defaults": self.defaults,
                "timeframes": self.timeframes,
                "assets": self.assets,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        def _unfreeze(value: Any) -> Any:
            if isinstance(value, MappingProxyType):
                return {key: _unfreeze(item) for key, item in value.items()}
            if isinstance(value, tuple):
                return [_unfreeze(item) for item in value]
            return value

        return {
            "version": self.version,
            "defaults": _unfreeze(self.defaults),
            "timeframes": _unfreeze(self.timeframes),
            "assets": _unfreeze(self.assets),
        }


_SECTIONS = {
    "detection": DetectionConfig,
    "association": AssociationConfig,
    "lifecycle": LifecycleConfig,
    "runtime": RuntimeConfig,
}
_REQUIRED_SECTIONS = set(_SECTIONS)
_PARAMETER_PATHS = tuple(
    f"{section}.{config_field.name}"
    for section, config_type in _SECTIONS.items()
    for config_field in fields(config_type)
)
_ROOT_KEYS = {"version", "defaults", "timeframes", "assets"}


def _validated_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _validate_section_values(
    value: Mapping[str, Any],
    *,
    section: str,
    path: str,
    partial: bool,
    global_defaults: Mapping[str, Any] | None = None,
) -> None:
    config_type = _SECTIONS[section]
    candidate = dict(value)
    if partial:
        if global_defaults is None:
            raise ContractValidationError(
                "global defaults are required to validate partial overrides"
            )
        section_defaults = _validated_mapping(
            global_defaults.get(section), path=f"defaults.{section}"
        )
        candidate = dict(section_defaults)
        candidate.update(value)
    try:
        config_type(**candidate)
    except ContractValidationError as exc:
        raise ContractValidationError(
            f"invalid config value(s) at {path}.{section}: {exc}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"invalid config value(s) at {path}.{section}"
        ) from exc


def _validate_sections(
    value: Mapping[str, Any],
    *,
    path: str,
    partial: bool = False,
    global_defaults: Mapping[str, Any] | None = None,
) -> None:
    value = _validated_mapping(value, path=path)
    unknown = set(value) - set(_SECTIONS)
    if unknown:
        raise ContractValidationError(
            f"unknown config section(s) at {path}: {sorted(unknown, key=str)}"
        )
    for section, section_value in value.items():
        section_value = _validated_mapping(section_value, path=f"{path}.{section}")
        if partial and not section_value:
            raise ContractValidationError(
                f"partial config section at {path}.{section} must not be empty"
            )
        section_fields = {item.name for item in fields(_SECTIONS[section])}
        if not partial:
            missing = section_fields - set(section_value)
            if missing:
                raise ContractValidationError(
                    "missing required field(s) at "
                    f"{path}.{section}: {sorted(missing, key=str)}"
                )
        unknown_fields = set(section_value) - section_fields
        if unknown_fields:
            raise ContractValidationError(
                "unknown config field(s) at "
                f"{path}.{section}: {sorted(unknown_fields, key=str)}"
            )
        _validate_section_values(
            section_value,
            section=section,
            path=path,
            partial=partial,
            global_defaults=global_defaults,
        )


def _validate_raw_config(raw: Mapping[str, Any]) -> None:
    raw = _validated_mapping(raw, path="config")
    unknown = set(raw) - _ROOT_KEYS
    if unknown:
        raise ContractValidationError(
            f"unknown config root key(s): {sorted(unknown, key=str)}"
        )
    if "version" not in raw:
        raise ContractValidationError("config version is required")
    version = raw["version"]
    _string(version, field_name="config version")
    if version != "1":
        raise ContractValidationError(f"unsupported config version: {version!r}")
    if "defaults" not in raw:
        raise ContractValidationError("defaults are required and must be complete")

    defaults = _validated_mapping(raw["defaults"], path="defaults")
    if not defaults:
        raise ContractValidationError("defaults must not be empty")
    missing_sections = _REQUIRED_SECTIONS - set(defaults)
    if missing_sections:
        raise ContractValidationError(
            "defaults missing required section(s): "
            f"{sorted(missing_sections, key=str)}"
        )
    _validate_sections(defaults, path="defaults")

    timeframes = _validated_mapping(raw.get("timeframes", {}), path="timeframes")
    for timeframe, override in timeframes.items():
        _string(timeframe, field_name="timeframe override key")
        override = _validated_mapping(override, path=f"timeframes.{timeframe}")
        if not override:
            raise ContractValidationError(
                f"timeframe override '{timeframe}' must not be empty"
            )
        _validate_sections(
            override,
            path=f"timeframes.{timeframe}",
            partial=True,
            global_defaults=defaults,
        )

    assets = _validated_mapping(raw.get("assets", {}), path="assets")
    for asset, asset_block in assets.items():
        _string(asset, field_name="asset override key")
        asset_block = _validated_mapping(asset_block, path=f"assets.{asset}")
        if not asset_block:
            raise ContractValidationError(f"asset block '{asset}' must not be empty")
        unknown_asset_keys = set(asset_block) - {"defaults", "timeframes"}
        if unknown_asset_keys:
            raise ContractValidationError(
                "unknown config key(s) at "
                f"assets.{asset}: {sorted(unknown_asset_keys, key=str)}"
            )

        if "defaults" in asset_block:
            asset_defaults = _validated_mapping(
                asset_block["defaults"], path=f"assets.{asset}.defaults"
            )
            if not asset_defaults:
                raise ContractValidationError(
                    f"asset defaults for '{asset}' must not be empty"
                )
            _validate_sections(
                asset_defaults,
                path=f"assets.{asset}.defaults",
                partial=True,
                global_defaults=defaults,
            )

        if "timeframes" in asset_block:
            asset_timeframes = _validated_mapping(
                asset_block["timeframes"], path=f"assets.{asset}.timeframes"
            )
            if not asset_timeframes:
                raise ContractValidationError(
                    f"asset block '{asset}' timeframes must not be empty"
                )
            for timeframe, override in asset_timeframes.items():
                _string(timeframe, field_name="asset timeframe override key")
                override = _validated_mapping(
                    override, path=f"assets.{asset}.timeframes.{timeframe}"
                )
                if not override:
                    raise ContractValidationError(
                        "asset timeframe override "
                        f"'{timeframe}' for {asset} must not be empty"
                    )
                _validate_sections(
                    override,
                    path=f"assets.{asset}.timeframes.{timeframe}",
                    partial=True,
                    global_defaults=defaults,
                )


__all__ = ["SRConfig"]
