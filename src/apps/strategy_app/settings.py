from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS

KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"


def create_strategy_config_manager(
    config_manager: ConfigManager | None = None,
) -> ConfigManager:
    manager = config_manager or ConfigManager()
    manager.register_file(CONFIG_FILE_MODELS)
    manager.register_file(CONFIG_FILE_FEATURES)
    return manager


def resolve_asset_timeframe_node(
    config_manager: ConfigManager,
    root_key: str,
    asset: str,
    timeframe: str,
) -> dict[str, Any]:
    config = config_manager.get(root_key, {})
    assets_config = config.get(KEY_ASSETS, {})

    asset_node = assets_config.get(asset, {})
    default_asset_node = assets_config.get(KEY_DEFAULT, {})

    tf_node = asset_node.get(KEY_TIMEFRAMES, {}).get(timeframe, {})
    asset_default_tf = asset_node.get(KEY_TIMEFRAMES, {}).get(KEY_DEFAULT, {})
    default_tf_node = default_asset_node.get(KEY_TIMEFRAMES, {}).get(timeframe, {})
    default_default_tf = default_asset_node.get(KEY_TIMEFRAMES, {}).get(KEY_DEFAULT, {})

    merged: dict[str, Any] = {}
    for node in (default_default_tf, default_tf_node, asset_default_tf, tf_node):
        if isinstance(node, dict):
            merged.update(node)
    return merged


@dataclass(frozen=True)
class StrategyWorkerSettings:
    consumer_group: str = "strategy_app_group"
    consumer_name_prefix: str = "strategy_worker"
    batch_size: int = 10
    block_ms: int = 1000
    signal_stream_maxlen: int = 1000
    signal_stream_approximate: bool = True
    blender_enabled: bool = False
    blender_config: dict[str, Any] | None = None

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | None = None,
    ) -> "StrategyWorkerSettings":
        manager = create_strategy_config_manager(config_manager)
        blender_cfg = manager.get("blender", {}) or {}
        return cls(
            consumer_group=str(
                manager.get("strategy.runtime.consumer_group", cls.consumer_group),
            ),
            consumer_name_prefix=str(
                manager.get(
                    "strategy.runtime.consumer_name_prefix",
                    cls.consumer_name_prefix,
                ),
            ),
            batch_size=int(manager.get("strategy.runtime.batch_size", cls.batch_size)),
            block_ms=int(manager.get("strategy.runtime.block_ms", cls.block_ms)),
            signal_stream_maxlen=int(
                manager.get(
                    "strategy.runtime.signal_stream_maxlen",
                    cls.signal_stream_maxlen,
                ),
            ),
            signal_stream_approximate=bool(
                manager.get(
                    "strategy.runtime.signal_stream_approximate",
                    cls.signal_stream_approximate,
                ),
            ),
            blender_enabled=bool(blender_cfg.get("enabled", cls.blender_enabled)),
            blender_config=blender_cfg if blender_cfg else None,
        )
