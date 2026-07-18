"""Fail-closed ATR-input configuration resolution shared by SR research."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain import ContractValidationError
from libs.models.sr.domain.identity import deterministic_hash


_HASH_RE = re.compile(r"[0-9a-f]{64}")
_INPUT_ROOT_KEYS = {"version", "defaults", "timeframes", "assets"}
_INPUT_PATHS = ("atr.method", "atr.period", "atr.seed")
_INPUT_ATR_KEYS = {"method", "period", "seed"}


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _input_string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _input_integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _unknown(value: Mapping[str, Any], allowed: set[str], *, path: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ContractValidationError(
            f"unknown key(s) at {path}: {sorted(unknown, key=str)}"
        )


@dataclass(frozen=True)
class ResolvedInputConfig:
    """Resolved causal ATR-input configuration and field provenance."""

    version: str
    asset: str
    timeframe: str
    atr_method: str
    atr_period: int
    atr_seed: str
    field_provenance: tuple[tuple[str, str], ...]
    resolved_input_hash: str

    def __post_init__(self) -> None:
        if _string(self.version, field_name="version") != "1":
            raise ContractValidationError(
                f"unsupported input config version: {self.version!r}"
            )
        object.__setattr__(self, "asset", _string(self.asset, field_name="asset"))
        object.__setattr__(
            self,
            "timeframe",
            _string(self.timeframe, field_name="timeframe"),
        )
        if _string(self.atr_method, field_name="atr_method") != "wilder_rma":
            raise ContractValidationError("atr_method must be exactly 'wilder_rma'")
        object.__setattr__(
            self,
            "atr_period",
            _integer(self.atr_period, field_name="atr_period", minimum=1),
        )
        if _string(self.atr_seed, field_name="atr_seed") != "sma":
            raise ContractValidationError("atr_seed must be exactly 'sma'")
        if type(self.field_provenance) is not tuple:
            raise ContractValidationError("field_provenance must be exactly a tuple")
        entries = []
        for index, entry in enumerate(self.field_provenance):
            if type(entry) is not tuple or len(entry) != 2:
                raise ContractValidationError(
                    f"field_provenance[{index}] must be a pair tuple"
                )
            entries.append(
                (
                    _string(entry[0], field_name=f"field_provenance[{index}].path"),
                    _string(entry[1], field_name=f"field_provenance[{index}].source"),
                )
            )
        if tuple(path for path, _ in entries) != _INPUT_PATHS:
            raise ContractValidationError(
                "field_provenance must contain exactly the ATR input paths"
            )
        allowed_sources = {
            "defaults",
            f"timeframe:{self.timeframe}",
            f"asset_timeframe:{self.asset}:{self.timeframe}",
        }
        if any(source not in allowed_sources for _, source in entries):
            raise ContractValidationError("invalid input field provenance source")
        object.__setattr__(self, "field_provenance", tuple(entries))
        expected_hash = deterministic_hash(self.hash_payload())
        if _hash(self.resolved_input_hash, field_name="resolved_input_hash") != expected_hash:
            raise ContractValidationError("resolved_input_hash does not match content")

    def hash_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "atr_method": self.atr_method,
            "atr_period": self.atr_period,
            "atr_seed": self.atr_seed,
            "field_provenance": [list(pair) for pair in self.field_provenance],
        }

    @classmethod
    def create(
        cls,
        *,
        version: str,
        asset: str,
        timeframe: str,
        atr_method: str,
        atr_period: int,
        atr_seed: str,
        field_provenance: tuple[tuple[str, str], ...],
    ) -> ResolvedInputConfig:
        payload = {
            "version": version,
            "asset": asset,
            "timeframe": timeframe,
            "atr_method": atr_method,
            "atr_period": atr_period,
            "atr_seed": atr_seed,
            "field_provenance": [list(pair) for pair in field_provenance],
        }
        return cls(
            version=version,
            asset=asset,
            timeframe=timeframe,
            atr_method=atr_method,
            atr_period=atr_period,
            atr_seed=atr_seed,
            field_provenance=field_provenance,
            resolved_input_hash=deterministic_hash(payload),
        )


def _parse_atr(
    value: Any,
    *,
    path: str,
    partial: bool,
    defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mapping = _mapping(value, path=path)
    _unknown(mapping, _INPUT_ATR_KEYS, path=path)
    if not partial:
        missing = _INPUT_ATR_KEYS - set(mapping)
        if missing:
            raise ContractValidationError(
                f"missing key(s) at {path}: {sorted(missing, key=str)}"
            )
        candidate = dict(mapping)
    else:
        if defaults is None:
            raise ContractValidationError("input defaults required for partial ATR override")
        candidate = dict(defaults)
        candidate.update(mapping)
    method = _input_string(candidate.get("method"), path=f"{path}.method")
    if method != "wilder_rma":
        raise ContractValidationError(f"{path}.method must be exactly 'wilder_rma'")
    period = _input_integer(candidate.get("period"), path=f"{path}.period", minimum=1)
    seed = _input_string(candidate.get("seed"), path=f"{path}.seed")
    if seed != "sma":
        raise ContractValidationError(f"{path}.seed must be exactly 'sma'")
    return {"method": method, "period": period, "seed": seed}


def _validate_input_document(raw: Any) -> Mapping[str, Any]:
    root = _mapping(raw, path="input config")
    _unknown(root, _INPUT_ROOT_KEYS, path="input config")
    if set(root) != _INPUT_ROOT_KEYS:
        raise ContractValidationError("input config requires version/defaults/timeframes/assets")
    if _input_string(root["version"], path="version") != "1":
        raise ContractValidationError(f"unsupported input config version: {root['version']!r}")
    defaults = _mapping(root["defaults"], path="defaults")
    _unknown(defaults, {"atr"}, path="defaults")
    if set(defaults) != {"atr"}:
        raise ContractValidationError("defaults.atr is required")
    _parse_atr(defaults["atr"], path="defaults.atr", partial=False)

    timeframes = _mapping(root["timeframes"], path="timeframes")
    for timeframe, override in timeframes.items():
        _input_string(timeframe, path="timeframe override key")
        section = _mapping(override, path=f"timeframes.{timeframe}")
        _unknown(section, {"atr"}, path=f"timeframes.{timeframe}")
        if not section:
            raise ContractValidationError(f"timeframes.{timeframe} must not be empty")
        if "atr" in section:
            _parse_atr(
                section["atr"],
                path=f"timeframes.{timeframe}.atr",
                partial=True,
                defaults=_mapping(defaults["atr"], path="defaults.atr"),
            )

    assets = _mapping(root["assets"], path="assets")
    for asset, block in assets.items():
        _input_string(asset, path="asset override key")
        asset_mapping = _mapping(block, path=f"assets.{asset}")
        _unknown(asset_mapping, {"timeframes"}, path=f"assets.{asset}")
        if set(asset_mapping) != {"timeframes"}:
            raise ContractValidationError(
                f"assets.{asset} must contain exact asset/timeframe overrides"
            )
        asset_timeframes = _mapping(
            asset_mapping["timeframes"],
            path=f"assets.{asset}.timeframes",
        )
        if not asset_timeframes:
            raise ContractValidationError(f"assets.{asset}.timeframes must not be empty")
        for timeframe, override in asset_timeframes.items():
            _input_string(timeframe, path=f"assets.{asset}.timeframe key")
            section = _mapping(
                override,
                path=f"assets.{asset}.timeframes.{timeframe}",
            )
            _unknown(
                section,
                {"atr"},
                path=f"assets.{asset}.timeframes.{timeframe}",
            )
            if not section:
                raise ContractValidationError(
                    f"assets.{asset}.timeframes.{timeframe} must not be empty"
                )
            if "atr" in section:
                _parse_atr(
                    section["atr"],
                    path=f"assets.{asset}.timeframes.{timeframe}.atr",
                    partial=True,
                    defaults=_mapping(defaults["atr"], path="defaults.atr"),
                )
    return root


def resolve_input_config(
    raw_config: Mapping[str, Any],
    *,
    asset: str,
    timeframe: str,
) -> ResolvedInputConfig:
    """Resolve input ATR config through exactly three YAML layers."""

    root = _validate_input_document(raw_config)
    asset = _input_string(asset, path="asset")
    timeframe = _input_string(timeframe, path="timeframe")
    defaults = _mapping(root["defaults"], path="defaults")
    values = _parse_atr(defaults["atr"], path="defaults.atr", partial=False)
    provenance = {path: "defaults" for path in _INPUT_PATHS}

    timeframe_overrides = _mapping(root["timeframes"], path="timeframes")
    if timeframe in timeframe_overrides:
        section = _mapping(
            timeframe_overrides[timeframe],
            path=f"timeframes.{timeframe}",
        )
        if "atr" in section:
            override = _mapping(section["atr"], path=f"timeframes.{timeframe}.atr")
            values.update(override)
            for field_name in override:
                provenance[f"atr.{field_name}"] = f"timeframe:{timeframe}"

    assets = _mapping(root["assets"], path="assets")
    asset_block = assets.get(asset)
    if asset_block is not None:
        asset_timeframes = _mapping(
            _mapping(asset_block, path=f"assets.{asset}")["timeframes"],
            path=f"assets.{asset}.timeframes",
        )
        if timeframe in asset_timeframes:
            section = _mapping(
                asset_timeframes[timeframe],
                path=f"assets.{asset}.timeframes.{timeframe}",
            )
            if "atr" in section:
                override = _mapping(
                    section["atr"],
                    path=f"assets.{asset}.timeframes.{timeframe}.atr",
                )
                values.update(override)
                for field_name in override:
                    provenance[f"atr.{field_name}"] = (
                        f"asset_timeframe:{asset}:{timeframe}"
                    )

    return ResolvedInputConfig.create(
        version=root["version"],
        asset=asset,
        timeframe=timeframe,
        atr_method=values["method"],
        atr_period=values["period"],
        atr_seed=values["seed"],
        field_provenance=tuple((path, provenance[path]) for path in _INPUT_PATHS),
    )


def load_and_resolve_input_config(
    path: str | Path,
    *,
    asset: str,
    timeframe: str,
) -> ResolvedInputConfig:
    return resolve_input_config(load_sr_config(path), asset=asset, timeframe=timeframe)


__all__ = [
    "ResolvedInputConfig",
    "load_and_resolve_input_config",
    "resolve_input_config",
]
