from __future__ import annotations

from typing import Any

from apps.alert_app.contracts import NormalizedAlertEvent
from apps.alert_app.settings import create_alert_config_manager, route_configs_from_config


def resolve_routes_for_event(
    event: NormalizedAlertEvent,
    *,
    config_manager: Any | None = None,
) -> list[str]:
    manager = create_alert_config_manager(config_manager)
    policies = manager.get("alerts.policies", {}) or {}
    configured_routes = route_configs_from_config(manager)

    policy_keys = [
        event.event_type.value,
        event.source_app.value,
        event.source_app.value.removesuffix("_app"),
        "default",
    ]

    resolved: list[str] = []
    for key in policy_keys:
        policy = policies.get(key)
        if not isinstance(policy, dict):
            continue
        for route_name in policy.get("routes", []):
            normalized = str(route_name)
            route_cfg = configured_routes.get(normalized)
            if not route_cfg or not bool(route_cfg.get("enabled", True)):
                continue
            if normalized not in resolved:
                resolved.append(normalized)
    return resolved
