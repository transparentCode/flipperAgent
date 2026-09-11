"""Small shared helpers for canonical downstream signal routes."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_TIMEFRAME_TOKEN = re.compile(r"^[0-9]+[smhdw]$")


def normalize_signal_route(route: str) -> str:
    if not isinstance(route, str) or not route.strip() or route != route.strip():
        raise TypeError("signal route must be non-empty text")
    if route.count(":") != 1:
        raise ValueError("signal route must be ASSET:TIMEFRAME")
    asset, timeframe = route.split(":", 1)
    if not asset or asset != asset.upper():
        raise ValueError("signal route asset must be canonical uppercase text")
    if any(not (char.isalnum() or char in "_-") for char in asset):
        raise ValueError("signal route asset contains unsupported characters")
    if not timeframe or not _TIMEFRAME_TOKEN.fullmatch(timeframe):
        raise ValueError("signal route timeframe is malformed")
    return f"{asset}:{timeframe}"


def parse_signal_routes(
    value: object,
    *,
    setting_name: str = "risk.runtime.signal_routes",
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{setting_name} must be a list")
    routes: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise TypeError(f"{setting_name} entries must be strings")
        normalized = normalize_signal_route(raw)
        if normalized in seen:
            raise ValueError(f"duplicate {setting_name} entry: {normalized}")
        seen.add(normalized)
        routes.append(normalized)
    return tuple(routes)


def asset_map_from_routes(routes: Sequence[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for route in routes:
        asset, timeframe = normalize_signal_route(route).split(":", 1)
        timeframes = result.setdefault(asset, [])
        if timeframe not in timeframes:
            timeframes.append(timeframe)
    return result


def assets_from_routes(routes: Sequence[str]) -> list[str]:
    assets: list[str] = []
    seen: set[str] = set()
    for route in routes:
        asset, _timeframe = normalize_signal_route(route).split(":", 1)
        if asset not in seen:
            seen.add(asset)
            assets.append(asset)
    return assets


def decision_authoritative_routes_from_config(
    decision_assets: Mapping[str, object],
) -> tuple[str, ...]:
    routes: list[str] = []
    for asset in decision_assets.values():
        lanes = getattr(asset, "lanes", {})
        if not isinstance(lanes, Mapping):
            continue
        for lane in lanes.values():
            authority = getattr(lane, "authority", None)
            if authority != "authoritative":
                continue
            route = normalize_signal_route(
                f"{asset.decision_asset}:{lane.decision_timeframe}"
            )
            if route not in routes:
                routes.append(route)
    return tuple(routes)
