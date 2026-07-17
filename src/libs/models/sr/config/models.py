"""Typed, immutable SR configuration groups.

These groups describe the approved parameter surface for future detection,
association, lifecycle, and runtime behavior.  No market logic is implemented.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import math
import re
from types import MappingProxyType
from typing import Any, Mapping

from libs.models.sr.domain.identity import ContractValidationError, deterministic_hash


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        return 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class DetectionConfig:
    """Future detection parameters.  Values are placeholders, not optimized."""

    pivot_span_bars: int
    zone_half_width_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pivot_span_bars",
            _integer(
                self.pivot_span_bars,
                field_name="detection.pivot_span_bars",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "zone_half_width_atr",
            _number(
                self.zone_half_width_atr,
                field_name="detection.zone_half_width_atr",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class AssociationConfig:
    """Future association parameters.  Values are placeholders, not optimized."""

    merge_distance_atr: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "merge_distance_atr",
            _number(
                self.merge_distance_atr,
                field_name="association.merge_distance_atr",
                minimum=0.0,
            ),
        )


@dataclass(frozen=True)
class LifecycleConfig:
    """Future lifecycle parameters.  Values are placeholders, not optimized."""

    touch_tolerance_atr: float
    break_buffer_atr: float
    break_confirm_closes: int
    max_age_bars: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "touch_tolerance_atr",
            _number(
                self.touch_tolerance_atr,
                field_name="lifecycle.touch_tolerance_atr",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "break_buffer_atr",
            _number(
                self.break_buffer_atr,
                field_name="lifecycle.break_buffer_atr",
                minimum=0.0,
            ),
        )
        object.__setattr__(
            self,
            "break_confirm_closes",
            _integer(
                self.break_confirm_closes,
                field_name="lifecycle.break_confirm_closes",
                minimum=1,
            ),
        )
        object.__setattr__(
            self,
            "max_age_bars",
            _integer(
                self.max_age_bars,
                field_name="lifecycle.max_age_bars",
                minimum=1,
            ),
        )


@dataclass(frozen=True)
class RuntimeConfig:
    """Runtime limits for the stateful SR consumer."""

    max_active_zones: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_active_zones",
            _integer(
                self.max_active_zones,
                field_name="runtime.max_active_zones",
                minimum=1,
            ),
        )


@dataclass(frozen=True)
class SRConfig:
    """Raw, deeply-frozen, validated SR configuration mapping."""

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
                return {k: _unfreeze(v) for k, v in value.items()}
            if isinstance(value, tuple):
                return [_unfreeze(v) for v in value]
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
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ContractValidationError(
            f"{path} must be a mapping with string keys"
        )
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
    allowed = set(_SECTIONS)
    unknown = set(value) - allowed
    if unknown:
        raise ContractValidationError(
            f"unknown config section(s) at {path}: {sorted(unknown, key=str)}"
        )
    for section, section_value in value.items():
        section_value = _validated_mapping(
            section_value, path=f"{path}.{section}"
        )
        section_fields = {f.name for f in fields(_SECTIONS[section])}
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

    timeframes = _validated_mapping(
        raw.get("timeframes", {}), path="timeframes"
    )
    for timeframe, override in timeframes.items():
        _string(timeframe, field_name="timeframe override key")
        override = _validated_mapping(
            override, path=f"timeframes.{timeframe}"
        )
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
        asset_block = _validated_mapping(
            asset_block, path=f"assets.{asset}"
        )
        if not asset_block:
            raise ContractValidationError(
                f"asset block '{asset}' must not be empty"
            )
        unknown_asset_keys = set(asset_block) - {"timeframes"}
        if unknown_asset_keys:
            # V1.0 only supports exact asset/timeframe overrides; asset-wide
            # defaults are explicitly not a layer and are rejected.
            raise ContractValidationError(
                "unknown config key(s) at "
                f"assets.{asset}: {sorted(unknown_asset_keys, key=str)}. "
                "asset-wide defaults are not supported in V1.0"
            )
        asset_timeframes = _validated_mapping(
            asset_block.get("timeframes"),
            path=f"assets.{asset}.timeframes",
        )
        if not asset_timeframes:
            raise ContractValidationError(
                f"asset block '{asset}' timeframes must not be empty"
            )
        for timeframe, override in asset_timeframes.items():
            _string(timeframe, field_name="asset timeframe override key")
            override = _validated_mapping(
                override,
                path=f"assets.{asset}.timeframes.{timeframe}",
            )
            if not override:
                raise ContractValidationError(
                    f"asset timeframe override '{timeframe}' for {asset} must not be empty"
                )
            _validate_sections(
                override,
                path=f"assets.{asset}.timeframes.{timeframe}",
                partial=True,
                global_defaults=defaults,
            )


def _validate_resolved_config_types(
    *,
    detection: Any,
    association: Any,
    lifecycle: Any,
    runtime: Any,
) -> None:
    expected = {
        "detection": DetectionConfig,
        "association": AssociationConfig,
        "lifecycle": LifecycleConfig,
        "runtime": RuntimeConfig,
    }
    actual = {
        "detection": detection,
        "association": association,
        "lifecycle": lifecycle,
        "runtime": runtime,
    }
    for name, config_type in expected.items():
        if type(actual[name]) is not config_type:
            raise ContractValidationError(
                f"{name} must be exactly {config_type.__name__}"
            )


def _normalize_provenance(
    value: Any,
    *,
    asset: str,
    timeframe: str,
) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        entries = tuple(value.items())
    elif isinstance(value, (list, tuple)):
        entries = tuple(value)
    else:
        raise ContractValidationError(
            "field_provenance must contain one entry for each approved parameter"
        )

    if len(entries) != len(_PARAMETER_PATHS):
        raise ContractValidationError(
            "field_provenance must contain exactly "
            f"{len(_PARAMETER_PATHS)} entries"
        )

    normalized: list[tuple[str, str]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            raise ContractValidationError(
                f"field_provenance[{index}] must be a path/source pair"
            )
        path, source = entry
        _string(path, field_name=f"field_provenance[{index}].path")
        _string(source, field_name=f"field_provenance[{index}].source")
        normalized.append((path, source))

    paths = [path for path, _ in normalized]
    if len(set(paths)) != len(paths):
        raise ContractValidationError("field_provenance must not contain duplicate paths")
    expected_paths = set(_PARAMETER_PATHS)
    actual_paths = set(paths)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        unknown = sorted(actual_paths - expected_paths)
        raise ContractValidationError(
            "field_provenance paths must match the approved parameter surface; "
            f"missing={missing}, unknown={unknown}"
        )

    allowed_sources = {
        "defaults",
        f"timeframe:{timeframe}",
        f"asset_timeframe:{asset}:{timeframe}",
    }
    for path, source in normalized:
        if source not in allowed_sources:
            raise ContractValidationError(
                f"invalid provenance source for {path}: {source!r}"
            )
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class ResolvedSRConfig:
    """Fully resolved SR configuration with field-level provenance and hash."""

    version: str
    asset: str
    timeframe: str
    detection: DetectionConfig
    association: AssociationConfig
    lifecycle: LifecycleConfig
    runtime: RuntimeConfig
    field_provenance: tuple[tuple[str, str], ...]
    resolved_config_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "version", _string(self.version, field_name="version")
        )
        if self.version != "1":
            raise ContractValidationError(
                f"unsupported config version: {self.version!r}"
            )
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(
            self, "timeframe", _string(self.timeframe, field_name="timeframe")
        )
        _validate_resolved_config_types(
            detection=self.detection,
            association=self.association,
            lifecycle=self.lifecycle,
            runtime=self.runtime,
        )
        object.__setattr__(
            self,
            "field_provenance",
            _normalize_provenance(
                self.field_provenance,
                asset=self.asset,
                timeframe=self.timeframe,
            ),
        )
        if (
            not isinstance(self.resolved_config_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.resolved_config_hash) is None
        ):
            raise ContractValidationError(
                "resolved_config_hash must be a lowercase SHA-256 hex string"
            )
        expected = deterministic_hash(self._hash_payload())
        if self.resolved_config_hash != expected:
            raise ContractValidationError(
                "resolved_config_hash does not match content"
            )

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "detection": asdict(self.detection),
            "association": asdict(self.association),
            "lifecycle": asdict(self.lifecycle),
            "runtime": asdict(self.runtime),
            "field_provenance": sorted(self.field_provenance),
        }

    @classmethod
    def create(
        cls,
        *,
        version: str,
        asset: str,
        timeframe: str,
        detection: DetectionConfig,
        association: AssociationConfig,
        lifecycle: LifecycleConfig,
        runtime: RuntimeConfig,
        field_provenance: Mapping[str, str],
    ) -> ResolvedSRConfig:
        version = _string(version, field_name="version")
        if version != "1":
            raise ContractValidationError(
                f"unsupported config version: {version!r}"
            )
        asset = _string(asset, field_name="asset")
        timeframe = _string(timeframe, field_name="timeframe")
        _validate_resolved_config_types(
            detection=detection,
            association=association,
            lifecycle=lifecycle,
            runtime=runtime,
        )
        provenance_tuple = _normalize_provenance(
            field_provenance,
            asset=asset,
            timeframe=timeframe,
        )
        payload = {
            "version": version,
            "asset": asset,
            "timeframe": timeframe,
            "detection": asdict(detection),
            "association": asdict(association),
            "lifecycle": asdict(lifecycle),
            "runtime": asdict(runtime),
            "field_provenance": sorted(provenance_tuple),
        }
        return cls(
            version=version,
            asset=asset,
            timeframe=timeframe,
            detection=detection,
            association=association,
            lifecycle=lifecycle,
            runtime=runtime,
            field_provenance=provenance_tuple,
            resolved_config_hash=deterministic_hash(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "detection": asdict(self.detection),
            "association": asdict(self.association),
            "lifecycle": asdict(self.lifecycle),
            "runtime": asdict(self.runtime),
            "field_provenance": dict(self.field_provenance),
            "resolved_config_hash": self.resolved_config_hash,
        }


__all__ = [
    "ContractValidationError",
    "DetectionConfig",
    "AssociationConfig",
    "LifecycleConfig",
    "RuntimeConfig",
    "SRConfig",
    "ResolvedSRConfig",
    "_SECTIONS",
    "_validate_raw_config",
]
