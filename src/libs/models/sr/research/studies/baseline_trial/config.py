"""Fail-closed YAML schemas for the SR-V1.5 baseline trial."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from libs.models.sr.adapters.yaml_config import load_sr_config
from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.config.input_resolution import (
    ResolvedInputConfig as ResolvedInputConfig,  # noqa: F401
    load_and_resolve_input_config,
    resolve_input_config,
)
from libs.models.sr.research.config.resolution import load_resolved_sr_config

from .contracts import (
    BASELINE_SYMBOL,
    BASELINE_TIMEFRAME,
    BASELINE_VENUE,
    TrialSpec,
    ViewerConfig,
)


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


__all__ = [
    "load_and_resolve_input_config",
    "load_resolved_sr_config",
    "load_trial_config",
    "parse_trial_config",
    "resolve_input_config",
]
