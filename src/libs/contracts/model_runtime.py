"""Shared contracts for model-declared runtime semantics."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from libs.common.constants import CONFIG_FILE_MODELS


TriggerMode = Literal["on_bar_close", "every_bar_close", "on_base_bar_close"]
PriorityClass = Literal["low", "normal", "high"]


class ModelRuntimeSpec(BaseModel):
    """Semantic runtime requirements declared for a model."""

    decision_timeframe: str = Field(..., description="Timeframe at which the model decides.")
    base_timeframe: str = Field(default="1m", description="Canonical lower timeframe backing the model.")
    trigger_mode: TriggerMode = Field(
        default="on_bar_close",
        description="When the evaluation should trigger relative to transport cadence.",
    )
    required_context_profiles: list[str] = Field(
        default_factory=list,
        description="Shared context profiles the model expects from signal_app.",
    )
    required_fields: list[str] = Field(
        default_factory=list,
        description="Additional context field requirements beyond model meta declarations.",
    )
    warmup_bars: int = Field(default=0, ge=0, description="Minimum bars required before the model is warm.")
    stateful: bool = Field(default=False, description="Whether the model keeps runtime state between evaluations.")
    priority_class: PriorityClass = Field(
        default="normal",
        description="Relative scheduling priority once runtime routing is introduced.",
    )


class ResolvedModelRuntimeSpec(ModelRuntimeSpec):
    """Runtime spec resolved for one concrete model/asset/timeframe binding."""

    model_name: str = Field(..., description="Registered model name.")
    asset: str = Field(..., description="Asset symbol resolved from config.")
    config_timeframe: str = Field(..., description="Configured strategy timeframe node.")


def resolve_model_runtime_spec(
    *,
    asset: str,
    timeframe: str,
    model_name: str,
    model_cfg: dict[str, Any],
    fallback_warmup_bars: int = 0,
) -> ResolvedModelRuntimeSpec:
    """Resolve one concrete runtime spec from a model config node."""

    runtime_cfg = model_cfg.get("runtime", {}) if isinstance(model_cfg, dict) else {}
    required_fields = runtime_cfg.get("required_fields", []) or []
    required_context_profiles = runtime_cfg.get("required_context_profiles", []) or []

    return ResolvedModelRuntimeSpec.model_validate(
        {
            "model_name": model_name,
            "asset": asset,
            "config_timeframe": timeframe,
            "decision_timeframe": str(runtime_cfg.get("decision_timeframe", timeframe)),
            "base_timeframe": str(runtime_cfg.get("base_timeframe", "1m")),
            "trigger_mode": runtime_cfg.get("trigger_mode", "on_bar_close"),
            "required_context_profiles": [str(item) for item in required_context_profiles],
            "required_fields": [str(item) for item in required_fields],
            "warmup_bars": int(runtime_cfg.get("warmup_bars", fallback_warmup_bars)),
            "stateful": bool(runtime_cfg.get("stateful", False)),
            "priority_class": runtime_cfg.get("priority_class", "normal"),
        }
    )


def derive_trigger_timeframe(runtime_spec: ModelRuntimeSpec) -> str:
    if runtime_spec.trigger_mode == "on_base_bar_close":
        return str(runtime_spec.base_timeframe).strip() or "1m"
    return str(runtime_spec.decision_timeframe).strip()


def collect_runtime_trigger_timeframes(
    config_manager: Any,
    *,
    asset: str,
    roots: tuple[str, ...] = ("models", "scoring_models", "strategy_models"),
) -> list[str]:
    """Collect unique trigger lanes required by enabled model runtime specs for one asset."""
    ordered: list[str] = []
    for runtime_spec in iter_enabled_runtime_specs(
        config_manager,
        asset=asset,
        roots=roots,
    ):
        validate_supported_runtime_spec(
            runtime_spec,
            allow_decision_projection=True,
        )
        trigger_timeframe = derive_trigger_timeframe(runtime_spec)
        if trigger_timeframe and trigger_timeframe not in ordered:
            ordered.append(trigger_timeframe)
    return ordered


def iter_enabled_runtime_specs(
    config_manager: Any,
    *,
    asset: str,
    roots: tuple[str, ...] = ("models", "scoring_models", "strategy_models"),
    fallback_warmup_bars: int = 0,
) -> list[ResolvedModelRuntimeSpec]:
    """Resolve enabled model runtime specs for one asset across config roots."""

    register_file = getattr(config_manager, "register_file", None)
    if callable(register_file):
        register_file(CONFIG_FILE_MODELS)

    normalized_asset = str(asset).upper().strip()
    specs: list[ResolvedModelRuntimeSpec] = []
    candidate_timeframes = _collect_candidate_timeframes(
        config_manager,
        asset=normalized_asset,
        roots=roots,
    )

    for root_key in roots:
        for configured_timeframe in candidate_timeframes:
            timeframe_cfg = _resolve_asset_timeframe_node(
                config_manager,
                root_key=root_key,
                asset=normalized_asset,
                timeframe=configured_timeframe,
            )
            for model_name, model_cfg in timeframe_cfg.items():
                if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                    continue
                specs.append(
                    resolve_model_runtime_spec(
                        asset=normalized_asset,
                        timeframe=str(configured_timeframe).strip(),
                        model_name=str(model_name),
                        model_cfg=model_cfg,
                        fallback_warmup_bars=fallback_warmup_bars,
                    )
                )

    return specs


def _collect_candidate_timeframes(
    config_manager: Any,
    *,
    asset: str,
    roots: tuple[str, ...],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    for root_key in roots:
        root = config_manager.get(root_key, {})
        assets = root.get("assets", {}) if isinstance(root, dict) else {}
        for asset_key in (asset, "default"):
            asset_cfg = assets.get(asset_key, {})
            if not isinstance(asset_cfg, dict):
                continue
            timeframes = asset_cfg.get("timeframes", {})
            if not isinstance(timeframes, dict):
                continue
            for timeframe in timeframes:
                normalized = str(timeframe).strip()
                if normalized == "default" or not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                ordered.append(normalized)

    return ordered


def _resolve_asset_timeframe_node(
    config_manager: Any,
    *,
    root_key: str,
    asset: str,
    timeframe: str,
) -> dict[str, Any]:
    root = config_manager.get(root_key, {})
    assets = root.get("assets", {}) if isinstance(root, dict) else {}

    asset_node = assets.get(asset, {})
    default_asset_node = assets.get("default", {})

    def _timeframe_node(node: Any, key: str) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        timeframes = node.get("timeframes", {})
        if not isinstance(timeframes, dict):
            return {}
        timeframe_node = timeframes.get(key, {})
        return timeframe_node if isinstance(timeframe_node, dict) else {}

    merged: dict[str, Any] = {}
    for node in (
        _timeframe_node(default_asset_node, "default"),
        _timeframe_node(default_asset_node, timeframe),
        _timeframe_node(asset_node, "default"),
        _timeframe_node(asset_node, timeframe),
    ):
        merged.update(node)
    return merged


def requires_decision_projection(runtime_spec: ModelRuntimeSpec) -> bool:
    return (
        runtime_spec.trigger_mode == "on_base_bar_close"
        and str(runtime_spec.decision_timeframe).strip() != str(runtime_spec.base_timeframe).strip()
    )


def validate_supported_runtime_spec(
    runtime_spec: ModelRuntimeSpec,
    *,
    allow_decision_projection: bool = False,
) -> None:
    if requires_decision_projection(runtime_spec) and not allow_decision_projection:
        raise ValueError(
            "Unsupported runtime spec: trigger_mode='on_base_bar_close' with "
            f"decision_timeframe={runtime_spec.decision_timeframe!r} and "
            f"base_timeframe={runtime_spec.base_timeframe!r} requires a decision-view "
            "projection path that is not implemented yet."
        )


__all__ = [
    "ModelRuntimeSpec",
    "ResolvedModelRuntimeSpec",
    "TriggerMode",
    "PriorityClass",
    "collect_runtime_trigger_timeframes",
    "derive_trigger_timeframe",
    "iter_enabled_runtime_specs",
    "requires_decision_projection",
    "resolve_model_runtime_spec",
    "validate_supported_runtime_spec",
]
