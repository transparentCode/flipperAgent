"""Fail-closed YAML schemas for the SR-V1.5 baseline trial."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.config.resolver import SRConfigResolver
from libs.models.sr.domain.contracts import ContractValidationError

from .contracts import (
    BASELINE_SYMBOL,
    BASELINE_TIMEFRAME,
    BASELINE_VENUE,
    ResolvedInputConfig,
    TrialSpec,
    ViewerConfig,
)


_INPUT_ROOT_KEYS = {"version", "defaults", "timeframes", "assets"}
_INPUT_PATHS = ("atr.method", "atr.period", "atr.seed")
_INPUT_ATR_KEYS = {"method", "period", "seed"}
_TRIAL_ROOT_KEYS = {"version", "trial", "viewer"}
_TRIAL_KEYS = {
    "trial_name",
    "venue",
    "symbol",
    "timeframe",
    "requested_since",
    "requested_until",
    "adapter_limit",
    "gap_policy",
    "sr_config_path",
    "input_config_path",
    "output_root",
}
_VIEWER_KEYS = {
    "library",
    "library_version",
    "attribution_logo",
    "live_zone_extent",
    "show_terminal_by_default",
    "show_events_by_default",
    "background_color",
    "text_color",
    "grid_color",
    "support_border_color",
    "support_fill_color",
    "resistance_border_color",
    "resistance_fill_color",
    "pending_border_color",
    "terminal_opacity",
    "zone_line_width",
}


def _mapping(value: Any, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise ContractValidationError(f"{path} must be a mapping with string keys")
    return value


def _string(value: Any, *, path: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or type(value) is not int or value < minimum:
        raise ContractValidationError(f"{path} must be an integer >= {minimum}")
    return value


def _unknown(value: Mapping[str, Any], allowed: set[str], *, path: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise ContractValidationError(
            f"unknown key(s) at {path}: {sorted(unknown, key=str)}"
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
    method = _string(candidate.get("method"), path=f"{path}.method")
    if method != "wilder_rma":
        raise ContractValidationError(f"{path}.method must be exactly 'wilder_rma'")
    period = _integer(candidate.get("period"), path=f"{path}.period", minimum=1)
    seed = _string(candidate.get("seed"), path=f"{path}.seed")
    if seed != "sma":
        raise ContractValidationError(f"{path}.seed must be exactly 'sma'")
    return {"method": method, "period": period, "seed": seed}


def _validate_input_document(raw: Any) -> Mapping[str, Any]:
    root = _mapping(raw, path="input config")
    _unknown(root, _INPUT_ROOT_KEYS, path="input config")
    if set(root) != _INPUT_ROOT_KEYS:
        raise ContractValidationError("input config requires version/defaults/timeframes/assets")
    if _string(root["version"], path="version") != "1":
        raise ContractValidationError(f"unsupported input config version: {root['version']!r}")
    defaults = _mapping(root["defaults"], path="defaults")
    _unknown(defaults, {"atr"}, path="defaults")
    if set(defaults) != {"atr"}:
        raise ContractValidationError("defaults.atr is required")
    _parse_atr(defaults["atr"], path="defaults.atr", partial=False)

    timeframes = _mapping(root["timeframes"], path="timeframes")
    for timeframe, override in timeframes.items():
        _string(timeframe, path="timeframe override key")
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
        _string(asset, path="asset override key")
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
            _string(timeframe, path=f"assets.{asset}.timeframe key")
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
    asset = _string(asset, path="asset")
    timeframe = _string(timeframe, path="timeframe")
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
                    provenance[f"atr.{field_name}"] = f"asset_timeframe:{asset}:{timeframe}"

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


def _parse_utc(value: Any, *, path: str) -> datetime:
    value = _string(value, path=path)
    if not value.endswith("Z"):
        raise ContractValidationError(f"{path} must use strict UTC Z notation")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractValidationError(f"{path} must be an ISO-8601 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractValidationError(f"{path} must be UTC")
    return parsed.astimezone(timezone.utc)


def _viewer_config(raw: Any) -> ViewerConfig:
    value = _mapping(raw, path="viewer")
    _unknown(value, _VIEWER_KEYS, path="viewer")
    if set(value) != _VIEWER_KEYS:
        raise ContractValidationError("viewer config is incomplete")
    return ViewerConfig(**dict(value))


def parse_trial_config(raw_config: Mapping[str, Any]) -> TrialSpec:
    root = _mapping(raw_config, path="trial config")
    _unknown(root, _TRIAL_ROOT_KEYS, path="trial config")
    if set(root) != _TRIAL_ROOT_KEYS:
        raise ContractValidationError("trial config requires version/trial/viewer")
    if _string(root["version"], path="version") != "1":
        raise ContractValidationError(f"unsupported trial config version: {root['version']!r}")
    trial = _mapping(root["trial"], path="trial")
    _unknown(trial, _TRIAL_KEYS, path="trial")
    if set(trial) != _TRIAL_KEYS:
        raise ContractValidationError("trial config is incomplete")
    candidate = dict(trial)
    if candidate["venue"] != BASELINE_VENUE:
        raise ContractValidationError("trial.venue must be binance_usdm")
    if candidate["symbol"] != BASELINE_SYMBOL:
        raise ContractValidationError("trial.symbol must be TAOUSDT")
    if candidate["timeframe"] != BASELINE_TIMEFRAME:
        raise ContractValidationError("trial.timeframe must be 1d")
    return TrialSpec(
        version=root["version"],
        trial_name=candidate["trial_name"],
        venue=candidate["venue"],
        symbol=candidate["symbol"],
        timeframe=candidate["timeframe"],
        requested_since=_parse_utc(candidate["requested_since"], path="trial.requested_since"),
        requested_until=_parse_utc(candidate["requested_until"], path="trial.requested_until"),
        adapter_limit=candidate["adapter_limit"],
        gap_policy=candidate["gap_policy"],
        sr_config_path=candidate["sr_config_path"],
        input_config_path=candidate["input_config_path"],
        output_root=candidate["output_root"],
        viewer=_viewer_config(root["viewer"]),
    )


def load_trial_config(path: str | Path) -> TrialSpec:
    return parse_trial_config(load_sr_config(path))


def load_resolved_sr_config(
    path: str | Path,
    *,
    asset: str,
    timeframe: str,
) -> ResolvedSRConfig:
    return SRConfigResolver(load_sr_config(path)).resolve(
        asset=asset,
        timeframe=timeframe,
    )


__all__ = [
    "load_and_resolve_input_config",
    "load_resolved_sr_config",
    "load_trial_config",
    "parse_trial_config",
    "resolve_input_config",
]
