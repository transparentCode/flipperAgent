"""Strict, duplicate-key-safe SR v2 structural configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ..contracts import SR_V2_CONFIG_VERSION
from ..domain.identity import canonical_hash
from ..kernels.registry import KERNEL_CATALOG, KernelSpec
from .schema import (
    MAX_EXPIRY,
    TIMEFRAME_DURATIONS,
    SRV2ConfigError,
    bounded_decimal,
    bounded_int,
    duration,
    positive_int,
    require_exact_keys,
    require_mapping,
    validate_ladder,
)


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: yaml.Loader, node: yaml.Node, deep: bool = False) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise SRV2ConfigError("YAML configuration keys must be strings")
        if key in mapping:
            raise SRV2ConfigError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True, slots=True, kw_only=True)
class KernelConfig:
    """One catalog-owned kernel with explicit per-timeframe settings."""

    spec: KernelSpec
    timeframes: Mapping[str, Mapping[str, Any]]
    ladder: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.spec, KernelSpec):
            raise TypeError("kernel spec must be KernelSpec")
        expected = validate_ladder(tuple(self.ladder), "kernel ladder")
        values = {timeframe: MappingProxyType(dict(parameters)) for timeframe, parameters in self.timeframes.items()}
        if set(values) != set(expected):
            raise ValueError("kernel config must cover the exact resolved ladder")
        object.__setattr__(self, "ladder", expected)
        object.__setattr__(self, "timeframes", MappingProxyType(values))

    @property
    def identifier(self) -> str:
        return self.spec.identifier

    @property
    def kernel_id(self) -> str:
        return self.spec.kernel_id

    @property
    def kernel_version(self) -> str:
        return self.spec.version

    def parameters_for(self, timeframe: str) -> Mapping[str, Any]:
        try:
            return self.timeframes[timeframe]
        except KeyError as exc:
            raise SRV2ConfigError(f"kernel has no timeframe configuration: {timeframe}") from exc

    def enabled_for(self, timeframe: str) -> bool:
        return bool(self.parameters_for(timeframe)["enabled"])


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedSRV2Config:
    version: int
    ladder: tuple[str, ...]
    trigger_timeframe: str
    trigger_duration: timedelta
    kernels: tuple[KernelConfig, ...]
    break_buffer_atr: Decimal
    break_confirmation_bars: int
    expiry: timedelta
    max_active_lineages: int
    max_terminal_tombstones: int
    catalog_fingerprint: str
    config_fingerprint: str

    def __post_init__(self) -> None:
        if self.version != SR_V2_CONFIG_VERSION:
            raise ValueError("unsupported SR v2 config version")
        ladder = validate_ladder(tuple(self.ladder), "resolved SR v2 ladder")
        if self.trigger_timeframe not in ladder:
            raise ValueError("trigger timeframe must be configured in the ladder")
        if self.trigger_timeframe != ladder[-1]:
            raise ValueError("trigger timeframe must be the finest configured timeframe")
        if self.trigger_duration != TIMEFRAME_DURATIONS[self.trigger_timeframe]:
            raise ValueError("trigger duration must derive from trigger timeframe")
        if any(TIMEFRAME_DURATIONS[item] % self.trigger_duration != timedelta(0) for item in ladder):
            raise ValueError("source timeframe durations must be integral multiples of trigger duration")
        object.__setattr__(self, "ladder", ladder)
        kernels = tuple(self.kernels)
        if not kernels:
            raise ValueError("at least one kernel must be selected")
        if any(not isinstance(kernel, KernelConfig) for kernel in kernels):
            raise TypeError("resolved kernels must contain KernelConfig values")
        identifiers = tuple(kernel.identifier for kernel in kernels)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("resolved kernels must have unique identifiers")
        object.__setattr__(self, "kernels", kernels)
        if not isinstance(self.break_buffer_atr, Decimal) or not self.break_buffer_atr.is_finite() or self.break_buffer_atr <= 0:
            raise ValueError("break_buffer_atr must be a finite positive Decimal")
        if not isinstance(self.break_confirmation_bars, int) or isinstance(self.break_confirmation_bars, bool) or self.break_confirmation_bars <= 0:
            raise ValueError("break_confirmation_bars must be a positive integer")
        if not isinstance(self.expiry, timedelta) or self.expiry <= timedelta(0):
            raise ValueError("expiry must be positive")
        for name in ("catalog_fingerprint", "config_fingerprint"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        required = dict(self.history_requirements())
        if any(required[item] <= 0 for item in ladder):
            raise ValueError("every runtime timeframe requires an enabled kernel")

    def history_requirements(self) -> tuple[tuple[str, int], ...]:
        result = {timeframe: 0 for timeframe in self.ladder}
        for kernel in self.kernels:
            for timeframe in self.ladder:
                if kernel.enabled_for(timeframe):
                    result[timeframe] = max(
                        result[timeframe],
                        int(kernel.spec.history_required(kernel.parameters_for(timeframe))),
                    )
        return tuple((timeframe, result[timeframe]) for timeframe in self.ladder)

    def maximum_source_lookback(self) -> timedelta:
        return max(
            (TIMEFRAME_DURATIONS[timeframe] * bars for timeframe, bars in self.history_requirements()),
            default=timedelta(0),
        )

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "version": self.version,
            "runtime": {
                "ladder": self.ladder,
                "trigger_timeframe": self.trigger_timeframe,
                "selected_kernel_order": tuple(kernel.identifier for kernel in self.kernels),
            },
            "kernels": {
                kernel.identifier: {
                    "timeframes": {
                        timeframe: dict(kernel.parameters_for(timeframe)) for timeframe in self.ladder
                    }
                }
                for kernel in self.kernels
            },
            "lifecycle": {
                "break_buffer_atr": self.break_buffer_atr,
                "break_confirmation_bars": self.break_confirmation_bars,
                "expiry": _duration_text(self.expiry),
            },
            "state_bounds": {
                "active_lineages": self.max_active_lineages,
                "terminal_tombstones": self.max_terminal_tombstones,
            },
        }


def _duration_text(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if seconds % 86_400 == 0:
        return f"{seconds // 86_400}d"
    if seconds % 3_600 == 0:
        return f"{seconds // 3_600}h"
    return f"{seconds // 60}m"


def _resolve_kernel(
    identifier: str,
    raw: object,
    ladder: tuple[str, ...],
    spec: KernelSpec,
) -> KernelConfig:
    item = require_mapping(raw, f"kernels.{identifier}")
    require_exact_keys(item, {"timeframes"}, f"kernels.{identifier}")
    timeframe_raw = require_mapping(item["timeframes"], f"kernels.{identifier}.timeframes")
    require_exact_keys(timeframe_raw, set(ladder), f"kernels.{identifier}.timeframes")
    values: dict[str, Mapping[str, Any]] = {}
    for timeframe in ladder:
        values[timeframe] = MappingProxyType(
            dict(spec.parse_parameters(timeframe_raw[timeframe], f"kernels.{identifier}.timeframes.{timeframe}"))
        )
    return KernelConfig(spec=spec, timeframes=values, ladder=ladder)


class SRV2ConfigResolver:
    """Resolve the structural model YAML against the explicit kernel catalog."""

    def __init__(self, raw: Mapping[str, Any], *, kernel_catalog: Mapping[str, KernelSpec] | None = None) -> None:
        self._raw = dict(require_mapping(raw, "config"))
        self._catalog = dict(KERNEL_CATALOG if kernel_catalog is None else kernel_catalog)
        if not self._catalog:
            raise SRV2ConfigError("kernel catalog must not be empty")
        if any(key != spec.identifier for key, spec in self._catalog.items()):
            raise SRV2ConfigError("kernel catalog keys must equal identifiers")

    @classmethod
    def from_yaml(cls, path: str | Path, *, kernel_catalog: Mapping[str, KernelSpec] | None = None) -> SRV2ConfigResolver:
        return cls(load_sr_v2_yaml(path), kernel_catalog=kernel_catalog)

    def resolve(self) -> ResolvedSRV2Config:
        raw = self._raw
        require_exact_keys(raw, {"version", "runtime", "kernels", "lifecycle", "state_bounds"}, "config")
        version = positive_int(raw["version"], "version")
        if version != SR_V2_CONFIG_VERSION:
            raise SRV2ConfigError(f"unsupported config version: {version}")
        runtime = require_mapping(raw["runtime"], "runtime")
        require_exact_keys(runtime, {"ladder", "trigger_timeframe"}, "runtime")
        ladder = validate_ladder(runtime["ladder"])
        trigger = runtime["trigger_timeframe"]
        if not isinstance(trigger, str) or trigger not in ladder:
            raise SRV2ConfigError("runtime.trigger_timeframe must be configured in the ladder")
        if trigger != ladder[-1]:
            raise SRV2ConfigError("runtime.trigger_timeframe must be the finest configured timeframe")
        trigger_duration = TIMEFRAME_DURATIONS[trigger]
        if any(TIMEFRAME_DURATIONS[item] % trigger_duration != timedelta(0) for item in ladder):
            raise SRV2ConfigError("runtime source durations must be integral multiples of trigger duration")

        kernels_raw = require_mapping(raw["kernels"], "kernels")
        if not kernels_raw:
            raise SRV2ConfigError("kernels must select at least one catalog identifier")
        unknown = sorted(set(kernels_raw) - set(self._catalog))
        if unknown:
            raise SRV2ConfigError(f"kernels contains unknown catalog identifiers: {', '.join(unknown)}")
        # Preserve the explicit model YAML order for deterministic downstream
        # evidence/reporting while keeping the catalog fingerprint order
        # independent of mapping construction.
        identifiers = tuple(kernels_raw)
        kernels = tuple(_resolve_kernel(identifier, kernels_raw[identifier], ladder, self._catalog[identifier]) for identifier in identifiers)
        if any(not any(kernel.enabled_for(timeframe) for kernel in kernels) for timeframe in ladder):
            raise SRV2ConfigError("at least one kernel must be enabled for every timeframe")

        lifecycle = require_mapping(raw["lifecycle"], "lifecycle")
        require_exact_keys(lifecycle, {"break_buffer_atr", "break_confirmation_bars", "expiry"}, "lifecycle")
        break_buffer = bounded_decimal(lifecycle["break_buffer_atr"], "lifecycle.break_buffer_atr", maximum=20)
        confirmation = bounded_int(lifecycle["break_confirmation_bars"], "lifecycle.break_confirmation_bars", minimum=1, maximum=16)
        expiry = duration(lifecycle["expiry"], "lifecycle.expiry")
        if expiry % trigger_duration != timedelta(0):
            raise SRV2ConfigError("lifecycle.expiry must align to the resolved trigger duration")
        if expiry > MAX_EXPIRY:
            raise SRV2ConfigError("lifecycle.expiry exceeds 730d")

        bounds = require_mapping(raw["state_bounds"], "state_bounds")
        require_exact_keys(bounds, {"active_lineages", "terminal_tombstones"}, "state_bounds")
        max_active = bounded_int(bounds["active_lineages"], "state_bounds.active_lineages", minimum=1, maximum=4096)
        max_terminal = bounded_int(bounds["terminal_tombstones"], "state_bounds.terminal_tombstones", minimum=1, maximum=8192)
        selected_specs = tuple(self._catalog[identifier] for identifier in identifiers)
        catalog_fingerprint = canonical_hash(
            tuple(
                {
                    "identifier": spec.identifier,
                    "replacement_policy": spec.replacement_policy,
                    "max_candidates": spec.max_candidates,
                    "max_evidence_rows": spec.max_evidence_rows,
                    "max_evidence_bytes": spec.max_evidence_bytes,
                }
                for spec in sorted(selected_specs, key=lambda item: item.identifier)
            )
        )
        resolved = ResolvedSRV2Config(
            version=version,
            ladder=ladder,
            trigger_timeframe=trigger,
            trigger_duration=trigger_duration,
            kernels=kernels,
            break_buffer_atr=break_buffer,
            break_confirmation_bars=confirmation,
            expiry=expiry,
            max_active_lineages=max_active,
            max_terminal_tombstones=max_terminal,
            catalog_fingerprint=catalog_fingerprint,
            config_fingerprint="pending",
        )
        object.__setattr__(resolved, "config_fingerprint", canonical_hash({"model": resolved.to_mapping(), "catalog_fingerprint": catalog_fingerprint}))
        return resolved


def load_sr_v2_yaml(path: str | Path) -> Mapping[str, Any]:
    try:
        value = yaml.load(Path(path).read_bytes(), Loader=_UniqueLoader)
    except SRV2ConfigError:
        raise
    except Exception as exc:
        raise SRV2ConfigError(f"invalid YAML: {path}") from exc
    if not isinstance(value, Mapping):
        raise SRV2ConfigError("SR v2 YAML root must be a mapping")
    return value


__all__ = ["KernelConfig", "ResolvedSRV2Config", "SRV2ConfigError", "SRV2ConfigResolver", "load_sr_v2_yaml"]
