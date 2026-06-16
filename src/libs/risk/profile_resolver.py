"""Helpers for resolving layered risk profiles onto the base risk config."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def resolve_risk_config(
    risk_config: dict[str, Any],
    *,
    asset: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Return an effective risk config with asset/model layering.

    Merge order:
    1. base ``risk_config``
    2. ``assets.default`` if present
    3. ``assets.{asset}`` if present
    4. ``model_profiles.default`` if present
    5. ``model_profiles.{model_name}`` if present
    6. ``assets.default.model_profiles.default`` if present
    7. ``assets.default.model_profiles.{model_name}`` if present
    8. ``assets.{asset}.model_profiles.default`` if present
    9. ``assets.{asset}.model_profiles.{model_name}`` if present

    Profiles support a compact override form:
    - ``limits`` → merged into ``global_limits``
    - ``position_sizing.strategy`` → ``position_sizing.default_strategy``
    - ``stop_loss.method`` → ``stop_loss.default_method``
    - ``take_profit.method`` → ``take_profit.default_method``
    - ``mtf.conflict_resolution`` → ``mtf.default_conflict_resolution``
    """
    resolved = deepcopy(risk_config)
    resolved.pop("model_profiles", None)
    resolved.pop("assets", None)

    assets = risk_config.get("assets", {})
    if not isinstance(assets, dict):
        assets = {}
    normalized_asset = str(asset).upper().strip() if asset else None
    default_asset_profile = _normalize_profile(_strip_nested_profiles(assets.get("default", {})))
    specific_asset_config = assets.get(normalized_asset, {}) if normalized_asset else {}
    specific_asset_profile = _normalize_profile(_strip_nested_profiles(specific_asset_config))

    resolved = _deep_merge(resolved, default_asset_profile)
    resolved = _deep_merge(resolved, specific_asset_profile)

    profiles = risk_config.get("model_profiles", {})
    if isinstance(profiles, dict):
        default_profile = _normalize_profile(profiles.get("default", {}))
        resolved = _deep_merge(resolved, default_profile)

        if model_name:
            model_profile = _normalize_profile(profiles.get(str(model_name), {}))
            resolved = _deep_merge(resolved, model_profile)

    for asset_profile in (
        _extract_asset_model_profile(assets.get("default", {}), model_name=model_name, key="default"),
        _extract_asset_model_profile(assets.get("default", {}), model_name=model_name),
        _extract_asset_model_profile(specific_asset_config, model_name=model_name, key="default"),
        _extract_asset_model_profile(specific_asset_config, model_name=model_name),
    ):
        resolved = _deep_merge(resolved, asset_profile)

    return resolved


def resolve_risk_config_for_model(
    risk_config: dict[str, Any],
    model_name: str | None,
    *,
    asset: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible wrapper for model-aware resolution."""
    return resolve_risk_config(risk_config, asset=asset, model_name=model_name)


def _normalize_profile(profile: object) -> dict[str, Any]:
    if not isinstance(profile, dict) or not profile:
        return {}

    normalized = deepcopy(profile)

    limits = normalized.pop("limits", None)
    if isinstance(limits, dict):
        normalized["global_limits"] = _deep_merge(
            normalized.get("global_limits", {}),
            limits,
        )

    position_sizing = normalized.get("position_sizing")
    if isinstance(position_sizing, dict):
        strategy = position_sizing.get("strategy")
        if strategy:
            position_sizing.setdefault("default_strategy", strategy)

    stop_loss = normalized.get("stop_loss")
    if isinstance(stop_loss, dict):
        method = stop_loss.get("method")
        if method:
            stop_loss.setdefault("default_method", method)

    take_profit = normalized.get("take_profit")
    if isinstance(take_profit, dict):
        method = take_profit.get("method")
        if method:
            take_profit.setdefault("default_method", method)

    mtf = normalized.get("mtf")
    if isinstance(mtf, dict):
        conflict_resolution = mtf.get("conflict_resolution")
        if conflict_resolution:
            mtf.setdefault("default_conflict_resolution", conflict_resolution)

    return normalized


def _extract_asset_model_profile(
    asset_profile: object,
    *,
    model_name: str | None,
    key: str | None = None,
) -> dict[str, Any]:
    if not isinstance(asset_profile, dict):
        return {}
    model_profiles = asset_profile.get("model_profiles", {})
    if not isinstance(model_profiles, dict):
        return {}
    lookup_key = key if key is not None else str(model_name) if model_name else None
    if not lookup_key:
        return {}
    return _normalize_profile(model_profiles.get(lookup_key, {}))


def _strip_nested_profiles(profile: object) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    stripped = deepcopy(profile)
    stripped.pop("model_profiles", None)
    return stripped


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    if not override:
        return deepcopy(base)

    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged
