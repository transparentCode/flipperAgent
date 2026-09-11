from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_ALERTS


def create_alert_config_manager(
    config_manager: ConfigManager | None = None,
) -> ConfigManager:
    manager = config_manager or ConfigManager()
    register_file = getattr(manager, "register_file", None)
    if callable(register_file):
        register_file(CONFIG_FILE_ALERTS)
    return manager


@dataclass(frozen=True)
class AlertAppSettings:
    consumer_group: str = "alert_app_group"
    consumer_name_prefix: str = "alert_worker"
    poll_block_ms: int = 1000
    idle_sleep_seconds: float = 5.0
    lifecycle_stream: str = "asset:lifecycle"
    execution_failure_prefix: str = "execution:failures:"
    dedupe_ttl_seconds: int = 900
    renotify_seconds: int = 1800
    open_state_ttl_seconds: int = 7 * 24 * 60 * 60
    hot_summary_ttl_seconds: int = 120

    @classmethod
    def from_config(
        cls,
        config_manager: ConfigManager | None = None,
    ) -> AlertAppSettings:
        manager = create_alert_config_manager(config_manager)
        runtime = manager.get("alerts.runtime", {}) or {}
        streams = manager.get("alerts.streams", {}) or {}
        incidents = manager.get("alerts.incidents", {}) or {}
        return cls(
            consumer_group=str(runtime.get("consumer_group", cls.consumer_group)),
            consumer_name_prefix=str(
                runtime.get("consumer_name_prefix", cls.consumer_name_prefix),
            ),
            poll_block_ms=int(runtime.get("poll_block_ms", cls.poll_block_ms)),
            idle_sleep_seconds=float(
                runtime.get("idle_sleep_seconds", cls.idle_sleep_seconds),
            ),
            lifecycle_stream=str(streams.get("lifecycle", cls.lifecycle_stream)),
            execution_failure_prefix=str(
                streams.get(
                    "execution_failure_prefix",
                    cls.execution_failure_prefix,
                ),
            ),
            dedupe_ttl_seconds=int(
                incidents.get("dedupe_ttl_seconds", cls.dedupe_ttl_seconds),
            ),
            renotify_seconds=int(
                incidents.get("renotify_seconds", cls.renotify_seconds),
            ),
            open_state_ttl_seconds=int(
                incidents.get(
                    "open_state_ttl_seconds",
                    cls.open_state_ttl_seconds,
                ),
            ),
            hot_summary_ttl_seconds=int(
                incidents.get(
                    "hot_summary_ttl_seconds",
                    cls.hot_summary_ttl_seconds,
                ),
            ),
        )


def route_configs_from_config(
    config_manager: ConfigManager | None = None,
) -> dict[str, dict[str, Any]]:
    manager = create_alert_config_manager(config_manager)
    routes = manager.get("alerts.routes", {}) or {}
    resolved: dict[str, dict[str, Any]] = {}
    for name, config in routes.items():
        if not isinstance(config, dict):
            continue
        route = dict(config)
        _hydrate_route_secret(route, "bot_token")
        _hydrate_route_secret(route, "chat_id")
        _hydrate_route_secret(route, "thread_id")
        if (
            str(route.get("transport", "")).strip().lower() == "telegram"
            and (
                not str(route.get("bot_token", "")).strip()
                or not str(route.get("chat_id", "")).strip()
            )
        ):
            route["enabled"] = False
        resolved[str(name)] = route
    return resolved


def _hydrate_route_secret(route: dict[str, Any], field_name: str) -> None:
    direct_value = route.get(field_name)
    if direct_value not in (None, ""):
        return
    env_name = str(route.get(f"{field_name}_env", "")).strip()
    if not env_name:
        return
    env_value = os.getenv(env_name)
    if env_value not in (None, ""):
        route[field_name] = env_value
