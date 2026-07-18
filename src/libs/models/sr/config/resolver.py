"""Strict layered configuration resolution for SR-V1.0.

Resolution precedence:
  mandatory defaults
  → timeframe override
  → asset-wide defaults
  → asset/timeframe override

RuntimeConfig values use same YAML precedence as other configuration groups.
No separate call-time ``runtime_override`` layer exists in V1.0.
"""

from __future__ import annotations

from dataclasses import fields
from types import MappingProxyType
from typing import Any, Mapping

from libs.models.sr.domain.errors import ContractValidationError

from .resolved import ResolvedSRConfig
from .schema import SRConfig, _SECTIONS, _validate_raw_config
from .sections import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
    _string,
)


def _deep_freeze_config_source(value: Any) -> Any:
    """Freeze the resolver's view of the source mapping without sorting keys."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {k: _deep_freeze_config_source(v) for k, v in value.items()}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze_config_source(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_deep_freeze_config_source(v) for v in value)
    return value


def _as_mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise ContractValidationError(
            f"{path} must be a mapping with string keys"
        )
    return value


def _merge_layer(
    base: dict[str, Any],
    override: Mapping[str, Any],
    provenance: dict[str, str],
    *,
    source: str,
) -> None:
    for section, values in override.items():
        for field_name, value in _as_mapping(
            values, path=f"{section}"
        ).items():
            base[section][field_name] = value
            provenance[f"{section}.{field_name}"] = source


def _config_from_mapping(
    mapping: Mapping[str, Any],
) -> tuple[DetectionConfig, AssociationConfig, LifecycleConfig, RuntimeConfig]:
    try:
        detection = DetectionConfig(**mapping["detection"])
        association = AssociationConfig(**mapping["association"])
        lifecycle = LifecycleConfig(**mapping["lifecycle"])
        runtime = RuntimeConfig(**mapping["runtime"])
    except ContractValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            "invalid resolved SR configuration"
        ) from exc
    return detection, association, lifecycle, runtime


class SRConfigResolver:
    """Resolve raw SR configuration into a typed, asset/timeframe-specific config."""

    def __init__(self, raw_config: Mapping[str, Any]) -> None:
        self._raw_config = _deep_freeze_config_source(
            _as_mapping(raw_config, path="config")
        )
        _validate_raw_config(self._raw_config)

    @property
    def raw_config(self) -> Mapping[str, Any]:
        return self._raw_config

    @classmethod
    def from_sr_config(cls, config: SRConfig) -> SRConfigResolver:
        return cls(
            {f.name: getattr(config, f.name) for f in fields(SRConfig)}
        )

    def resolve(self, *, asset: str, timeframe: str) -> ResolvedSRConfig:
        asset = _string(asset, field_name="asset")
        timeframe = _string(timeframe, field_name="timeframe")

        raw = self._raw_config
        defaults = _as_mapping(raw.get("defaults", {}), path="defaults")
        if not defaults:
            raise ContractValidationError("defaults are required and must be complete")

        base: dict[str, Any] = {}
        for section, cls_ in _SECTIONS.items():
            section_defaults = _as_mapping(
                defaults.get(section, {}), path=f"defaults.{section}"
            )
            base[section] = dict(section_defaults)

        provenance: dict[str, str] = {
            f"{section}.{field.name}": "defaults"
            for section, cls_ in _SECTIONS.items()
            for field in fields(cls_)
        }

        # Layer 2: timeframe override
        timeframe_overrides = _as_mapping(
            raw.get("timeframes", {}), path="timeframes"
        )
        if timeframe in timeframe_overrides:
            _merge_layer(
                base,
                _as_mapping(
                    timeframe_overrides[timeframe],
                    path=f"timeframes.{timeframe}",
                ),
                provenance,
                source=f"timeframe:{timeframe}",
            )

        # Layer 3: asset-wide defaults
        asset_block = _as_mapping(
            raw.get("assets", {}), path="assets"
        ).get(asset, {})
        if asset_block:
            asset_block = _as_mapping(asset_block, path=f"assets.{asset}")
            asset_defaults = _as_mapping(
                asset_block.get("defaults", {}),
                path=f"assets.{asset}.defaults",
            )
            if asset_defaults:
                _merge_layer(
                    base,
                    asset_defaults,
                    provenance,
                    source=f"asset:{asset}",
                )

            # Layer 4: exact asset/timeframe override
            asset_timeframes = _as_mapping(
                asset_block.get("timeframes", {}),
                path=f"assets.{asset}.timeframes",
            )
            if timeframe in asset_timeframes:
                _merge_layer(
                    base,
                    _as_mapping(
                        asset_timeframes[timeframe],
                        path=f"assets.{asset}.timeframes.{timeframe}",
                    ),
                    provenance,
                    source=f"asset_timeframe:{asset}:{timeframe}",
                )

        detection, association, lifecycle, runtime = _config_from_mapping(base)

        return ResolvedSRConfig.create(
            version=raw["version"],
            asset=asset,
            timeframe=timeframe,
            detection=detection,
            association=association,
            lifecycle=lifecycle,
            runtime=runtime,
            field_provenance=provenance,
        )
