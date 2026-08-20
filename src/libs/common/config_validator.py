"""Startup config validator — cross-checks asset/timeframe consistency across YAML files."""

from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__)


def validate_config_alignment(config_mgr: ConfigManager) -> list[str]:
    """Cross-check model consumers, features, runtime bindings, risk, and execution.

    Returns a list of warning strings for any mismatches found.
    Logs each warning. Does NOT raise — callers decide whether to fail.
    """
    warnings: list[str] = []

    # --- Source of truth: model configuration ---
    # ``models.yaml`` contains several model roots.  Ingestion no longer defines
    # the model universe or its timeframes; it only supplies market data.
    model_pairs: set[tuple[str, str]] = set()
    model_asset_set: set[str] = set()

    def _has_enabled_model(timeframe_config: object) -> bool:
        if not isinstance(timeframe_config, dict):
            return False
        return any(
            isinstance(model_config, dict) and model_config.get("enabled", True)
            for model_config in timeframe_config.values()
        )

    models_file = config_mgr.get("models", {}) or {}
    for root_name in ("models", "strategy_models", "scoring_models"):
        root = (
            models_file.get(root_name)
            if isinstance(models_file, dict) and root_name in models_file
            else config_mgr.get(root_name, {})
        ) or {}
        if (
            root_name == "models"
            and isinstance(models_file, dict)
            and "assets" in models_file
        ):
            root = models_file
        assets = root.get("assets", {}) if isinstance(root, dict) else {}
        if not isinstance(assets, dict):
            continue
        for asset, cfg in assets.items():
            if asset == "default" or not isinstance(cfg, dict):
                continue
            timeframes = cfg.get("timeframes", {})
            if not isinstance(timeframes, dict):
                continue
            active_asset = False
            for timeframe, timeframe_config in timeframes.items():
                if timeframe == "default" or not _has_enabled_model(timeframe_config):
                    continue
                active_asset = True
                model_pairs.add((asset, timeframe))
            if active_asset:
                model_asset_set.add(asset)

    # --- features.yaml ---
    features = config_mgr.get("features", {})
    features_assets = features.get("assets", {})
    for asset, cfg in features_assets.items():
        if asset == "default" or not isinstance(cfg, dict):
            continue
        tfs = cfg.get("timeframes", {})
        for tf in tfs:
            if tf == "default":
                continue
            if (asset, tf) not in model_pairs:
                w = f"features.yaml defines {asset}:{tf} but no model exists for it"
                warnings.append(w)

    # Check models that have no explicit features (only get defaults)
    for asset, tf in model_pairs:
        has_explicit = (
            asset in features_assets
            and isinstance(features_assets[asset], dict)
            and tf in features_assets[asset].get("timeframes", {})
        )
        if not has_explicit:
            w = f"models.yaml defines {asset}:{tf} but features.yaml has no explicit features (using defaults)"
            warnings.append(w)

    # --- risk.yaml ---
    risk = config_mgr.get("risk", {})
    risk_assets = risk.get("assets", {})
    for asset in risk_assets:
        if asset == "default":
            continue
        if asset not in model_asset_set:
            w = f"risk.yaml defines per-asset config for {asset} but no models exist"
            warnings.append(w)

    # --- execution.yaml ---
    execution = config_mgr.get("execution", {})
    exec_assets = execution.get("assets", {})
    for asset in exec_assets:
        if asset == "default":
            continue
        if asset not in model_asset_set:
            w = f"execution.yaml defines per-asset config for {asset} but no models exist"
            warnings.append(w)

    # Log all warnings
    if warnings:
        logger.warning(f"Config alignment check found {len(warnings)} issue(s):")
        for w in warnings:
            logger.warning(f"  - {w}")
    else:
        logger.info("Config alignment check passed — all configs consistent")

    return warnings
