"""Startup config validator — cross-checks asset/timeframe consistency across YAML files."""

from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__)


def validate_config_alignment(config_mgr: ConfigManager) -> list[str]:
    """Cross-check models, features, risk, execution, and ingestion configs.

    Returns a list of warning strings for any mismatches found.
    Logs each warning. Does NOT raise — callers decide whether to fail.
    """
    warnings: list[str] = []

    # --- Source of truth: models.yaml ---
    models = config_mgr.get("models", {})
    models_assets = models.get("assets", {})
    model_pairs: set[tuple[str, str]] = set()
    model_asset_set: set[str] = set()

    for asset, cfg in models_assets.items():
        if asset == "default" or not isinstance(cfg, dict):
            continue
        model_asset_set.add(asset)
        tfs = cfg.get("timeframes", {})
        for tf in tfs:
            if tf != "default":
                model_pairs.add((asset, tf))

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

    # --- ingestion (base.yaml) ---
    ingestion = config_mgr.get("ingestion", {})
    target_list = set(ingestion.get("assets", {}).get("target_list", []))
    publish_tfs = ingestion.get("assets", {}).get("publish_timeframes", {})

    for asset in target_list:
        if asset not in model_asset_set:
            w = f"ingestion target_list includes {asset} but no models exist for it"
            warnings.append(w)

    for asset in model_asset_set:
        if asset not in target_list:
            w = f"models.yaml defines {asset} but ingestion target_list does not include it"
            warnings.append(w)

    for asset, tfs_list in publish_tfs.items():
        for tf in tfs_list:
            if (asset, tf) not in model_pairs:
                w = f"ingestion publishes {asset}:{tf} but no model consumes it"
                warnings.append(w)

    for asset, tf in model_pairs:
        pub_tfs = publish_tfs.get(asset, [])
        if tf not in pub_tfs:
            w = f"models.yaml defines {asset}:{tf} but ingestion does not publish this timeframe"
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
