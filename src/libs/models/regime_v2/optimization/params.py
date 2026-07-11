"""Optimization parameter schema for RegimeV2.

This module sits above runtime dotted-key overrides and below any future
Optuna/objective code. Runtime behavior remains unchanged; this only provides a
typed, profile-aware search surface for offline tuning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from libs.contracts.schemas import ParamDef
from libs.models.regime_v2.config import RegimeV2Config, scale_bars, timeframe_scaled_config


ProfileName = Literal["core", "windows", "fusion", "policy", "full"]
ParamType = Literal["float", "int", "categorical"]


@dataclass(frozen=True)
class RegimeV2ParamSpec:
    """One tunable RegimeV2 parameter expressed as a dotted-key override."""

    key: str
    type: ParamType
    low: float | int | None = None
    high: float | int | None = None
    step: float | int | None = None
    choices: tuple[Any, ...] | None = None
    scale_with_timeframe: bool = False
    floor: int = 1
    profiles: tuple[ProfileName, ...] = ("full",)


REGIME_V2_OPTIMIZATION_PROFILES: dict[ProfileName, str] = {
    "core": "Default first-pass search space: key windows plus fusion/policy thresholds.",
    "windows": "Bar-count windows that should scale with timeframe.",
    "fusion": "Regime-label and confidence-fusion thresholds.",
    "policy": "Playbook gating and risk-sizing thresholds.",
    "full": "Union of all curated RegimeV2 tunables exposed here.",
}


REGIME_V2_PARAM_SPECS: tuple[RegimeV2ParamSpec, ...] = (
    RegimeV2ParamSpec(
        key="trend.fast_ema",
        type="int",
        low=8,
        high=40,
        step=2,
        scale_with_timeframe=True,
        floor=5,
        profiles=("core", "windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="trend.slow_ema",
        type="int",
        low=20,
        high=100,
        step=5,
        scale_with_timeframe=True,
        floor=10,
        profiles=("core", "windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="trend.efficiency_lookback",
        type="int",
        low=8,
        high=60,
        step=4,
        scale_with_timeframe=True,
        floor=5,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="trend.persistence_lookback",
        type="int",
        low=4,
        high=36,
        step=2,
        scale_with_timeframe=True,
        floor=4,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="volatility.realized_window",
        type="int",
        low=8,
        high=72,
        step=4,
        scale_with_timeframe=True,
        floor=5,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="volatility.compression_window",
        type="int",
        low=48,
        high=240,
        step=12,
        scale_with_timeframe=True,
        floor=30,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="mean_reversion.center_window",
        type="int",
        low=16,
        high=100,
        step=4,
        scale_with_timeframe=True,
        floor=10,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="mean_reversion.chop_window",
        type="int",
        low=8,
        high=72,
        step=4,
        scale_with_timeframe=True,
        floor=5,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="breaks.range_window",
        type="int",
        low=8,
        high=60,
        step=4,
        scale_with_timeframe=True,
        floor=5,
        profiles=("windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="breaks.breakout_window",
        type="int",
        low=20,
        high=120,
        step=5,
        scale_with_timeframe=True,
        floor=10,
        profiles=("core", "windows", "full"),
    ),
    RegimeV2ParamSpec(
        key="trend.direction_deadzone",
        type="float",
        low=0.05,
        high=0.35,
        step=0.01,
        profiles=("core", "fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.trend_threshold",
        type="float",
        low=0.30,
        high=0.75,
        step=0.01,
        profiles=("core", "fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.mr_threshold",
        type="float",
        low=0.35,
        high=0.80,
        step=0.01,
        profiles=("core", "fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.chop_threshold",
        type="float",
        low=0.45,
        high=0.90,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.break_threshold",
        type="float",
        low=0.45,
        high=0.90,
        step=0.01,
        profiles=("core", "fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.shock_threshold",
        type="float",
        low=0.45,
        high=0.95,
        step=0.01,
        profiles=("core", "fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.transition_breakout_min",
        type="float",
        low=0.20,
        high=0.75,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.trend_chop_max",
        type="float",
        low=0.20,
        high=0.80,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.mr_context_range_min",
        type="float",
        low=0.10,
        high=0.70,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.mr_context_compression_min",
        type="float",
        low=0.40,
        high=0.95,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="fusion.mr_break_risk_max",
        type="float",
        low=0.25,
        high=0.85,
        step=0.01,
        profiles=("fusion", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.min_confidence",
        type="float",
        low=0.10,
        high=0.60,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.high_uncertainty_no_trade",
        type="float",
        low=0.60,
        high=0.95,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.trend_min_strength",
        type="float",
        low=0.25,
        high=0.80,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.trend_max_chop",
        type="float",
        low=0.25,
        high=0.80,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.breakout_min_quality",
        type="float",
        low=0.25,
        high=0.85,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.breakout_max_false_break",
        type="float",
        low=0.20,
        high=0.85,
        step=0.01,
        profiles=("policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.mr_min_score",
        type="float",
        low=0.25,
        high=0.85,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.mr_max_break_risk",
        type="float",
        low=0.20,
        high=0.85,
        step=0.01,
        profiles=("policy", "full"),
    ),
    RegimeV2ParamSpec(
        key="policy.threshold_width",
        type="float",
        low=0.05,
        high=0.35,
        step=0.01,
        profiles=("core", "policy", "full"),
    ),
)


def list_optimization_profiles() -> dict[str, str]:
    """Return supported profile names and short descriptions."""
    return dict(REGIME_V2_OPTIMIZATION_PROFILES)


def get_optimization_param_schema(
    timeframe: str = "1h",
    *,
    profile: ProfileName = "core",
    base_config: RegimeV2Config | None = None,
) -> dict[str, ParamDef]:
    """Return a ParamDef schema keyed by RegimeV2 dotted-key overrides."""
    _validate_profile(profile)
    cfg = base_config or timeframe_scaled_config(timeframe)
    specs = _specs_for_profile(profile)
    return {
        spec.key: ParamDef(
            type=spec.type,
            default=_get_config_value(cfg, spec.key),
            low=_scaled_numeric(spec.low, timeframe, spec, kind="bound") if spec.low is not None else None,
            high=_scaled_numeric(spec.high, timeframe, spec, kind="bound") if spec.high is not None else None,
            step=_scaled_numeric(spec.step, timeframe, spec, kind="step") if spec.step is not None else None,
            choices=list(spec.choices) if spec.choices is not None else None,
        )
        for spec in specs
    }


def extract_profile_defaults(
    timeframe: str = "1h",
    *,
    profile: ProfileName = "core",
    base_config: RegimeV2Config | None = None,
) -> dict[str, Any]:
    """Return runtime defaults for one optimization profile."""
    schema = get_optimization_param_schema(timeframe, profile=profile, base_config=base_config)
    return {key: pdef.default for key, pdef in schema.items()}


def post_process_params(
    params: dict[str, Any],
    *,
    timeframe: str = "1h",
    profile: ProfileName = "core",
) -> dict[str, Any]:
    """Cast raw trial params into runtime-safe override values."""
    schema = get_optimization_param_schema(timeframe, profile=profile)
    _validate_keys(params, schema)
    return {key: _cast_value(value, schema[key]) for key, value in params.items()}


def params_to_overrides(
    params: dict[str, Any],
    *,
    timeframe: str = "1h",
    profile: ProfileName = "core",
) -> dict[str, Any]:
    """Validate and shape optimization params into orchestrator overrides."""
    return post_process_params(params, timeframe=timeframe, profile=profile)


def _validate_profile(profile: str) -> None:
    if profile not in REGIME_V2_OPTIMIZATION_PROFILES:
        choices = ", ".join(sorted(REGIME_V2_OPTIMIZATION_PROFILES))
        raise ValueError(f"Unknown RegimeV2 optimization profile '{profile}'. Expected one of: {choices}")


def _specs_for_profile(profile: ProfileName) -> tuple[RegimeV2ParamSpec, ...]:
    if profile == "full":
        return REGIME_V2_PARAM_SPECS
    return tuple(spec for spec in REGIME_V2_PARAM_SPECS if profile in spec.profiles)


def _get_config_value(cfg: RegimeV2Config, dotted_key: str) -> Any:
    current: Any = cfg
    for part in dotted_key.split("."):
        current = getattr(current, part)
    return current


def _scaled_numeric(
    value: float | int,
    timeframe: str,
    spec: RegimeV2ParamSpec,
    *,
    kind: Literal["bound", "step"],
) -> float | int:
    if not spec.scale_with_timeframe:
        return value
    if spec.type != "int":
        return value
    floor = 1 if kind == "step" else spec.floor
    scaled = scale_bars(int(value), timeframe, floor=floor)
    if spec.step is not None and scaled <= 0:
        return 1
    return scaled


def _validate_keys(params: dict[str, Any], schema: dict[str, ParamDef]) -> None:
    unknown = sorted(set(params) - set(schema))
    if unknown:
        raise KeyError(f"Unknown RegimeV2 optimization params: {unknown}")


def _cast_value(value: Any, pdef: ParamDef) -> Any:
    if pdef.type == "int":
        return int(round(float(value)))
    if pdef.type == "float":
        return float(value)
    if pdef.type == "categorical":
        return value
    return value


__all__ = [
    "ProfileName",
    "REGIME_V2_OPTIMIZATION_PROFILES",
    "REGIME_V2_PARAM_SPECS",
    "RegimeV2ParamSpec",
    "extract_profile_defaults",
    "get_optimization_param_schema",
    "list_optimization_profiles",
    "params_to_overrides",
    "post_process_params",
]
