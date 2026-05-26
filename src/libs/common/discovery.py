"""Shared asset/timeframe discovery from config."""

from __future__ import annotations
from libs.common.config import ConfigManager


def discover_pairs(config_mgr: ConfigManager) -> list[tuple[str, str]]:
    """Return (asset, timeframe) pairs from models.yaml (excluding 'default')."""
    models_config = config_mgr.get("models", {})
    assets_config = models_config.get("assets", {})
    pairs: list[tuple[str, str]] = []
    for asset, asset_cfg in assets_config.items():
        if asset == "default":
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get("timeframes", {})
        for tf in tfs:
            if tf == "default":
                continue
            pairs.append((asset, tf))
    return pairs


def discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Return list of asset symbols from models.yaml (excluding 'default')."""
    models_config = config_mgr.get("models", {})
    assets_config = models_config.get("assets", {})
    return [
        asset for asset, cfg in assets_config.items()
        if asset != "default" and isinstance(cfg, dict)
    ]


def discover_asset_timeframes(config_mgr: ConfigManager) -> dict[str, list[str]]:
    """Return {asset: [timeframes]} dict from models.yaml (excluding 'default')."""
    models_config = config_mgr.get("models", {})
    assets_config = models_config.get("assets", {})
    result: dict[str, list[str]] = {}
    for asset, asset_cfg in assets_config.items():
        if asset == "default" or not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get("timeframes", {})
        tf_list = [tf for tf in tfs if tf != "default"]
        if tf_list:
            result[asset] = tf_list
    return result
