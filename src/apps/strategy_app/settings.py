from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS

KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"
_TIMEFRAME_TOKEN = re.compile(r"^[0-9]+[smhdw]$")


def parse_relinquished_routes(value: object) -> tuple[str, ...]:
    """Normalize and validate route-scoped legacy authority exclusions."""

    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise TypeError("strategy.runtime.relinquished_routes must be a list")
    routes: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip() or raw != raw.strip():
            raise ValueError("relinquished routes must be non-empty strings")
        if raw.count(":") != 1:
            raise ValueError(f"invalid relinquished route: {raw!r}")
        asset, route = raw.split(":", 1)
        if not asset or any(not (char.isalnum() or char in "_-") for char in asset):
            raise ValueError(f"invalid relinquished route asset: {raw!r}")
        if route.count("@") > 1:
            raise ValueError(f"invalid relinquished route: {raw!r}")
        if "@" in route:
            decision_timeframe, trigger_timeframe = route.split("@", 1)
            if not decision_timeframe or not trigger_timeframe:
                raise ValueError(f"invalid relinquished route: {raw!r}")
            if decision_timeframe == trigger_timeframe:
                raise ValueError(f"redundant projected route: {raw!r}")
        else:
            decision_timeframe = route
            trigger_timeframe = None
        if not _TIMEFRAME_TOKEN.fullmatch(decision_timeframe) or (
            trigger_timeframe is not None
            and not _TIMEFRAME_TOKEN.fullmatch(trigger_timeframe)
        ):
            raise ValueError(f"invalid relinquished route timeframe: {raw!r}")
        canonical = f"{asset.upper()}:{decision_timeframe}"
        if trigger_timeframe is not None:
            canonical += f"@{trigger_timeframe}"
        if canonical in routes:
            raise ValueError(f"duplicate relinquished route: {canonical}")
        routes.append(canonical)
    return tuple(sorted(routes))


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
    relinquished_routes: tuple[str, ...] = ()
    signal_authority_enforced: bool = False

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | None = None,
    ) -> StrategyWorkerSettings:
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
            relinquished_routes=parse_relinquished_routes(
                manager.get("strategy.runtime.relinquished_routes", ())
            ),
            signal_authority_enforced=bool(
                manager.get(
                    "strategy.runtime.signal_authority_enforced",
                    cls.signal_authority_enforced,
                )
            ),
        )
