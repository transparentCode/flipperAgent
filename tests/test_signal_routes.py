from __future__ import annotations

import pytest

from apps.decision_app.settings import load_decision_config
from libs.common.config import ConfigManager
from libs.common.signal_routes import (
    asset_map_from_routes,
    assets_from_routes,
    decision_authoritative_routes_from_config,
    normalize_signal_route,
    parse_signal_routes,
)


def test_normalize_signal_route_requires_canonical_asset_and_timeframe() -> None:
    assert normalize_signal_route("BTCUSDT:1h") == "BTCUSDT:1h"

    with pytest.raises(ValueError):
        normalize_signal_route("btcusdt:1h")
    with pytest.raises(ValueError):
        normalize_signal_route("BTCUSDT:bad")
    with pytest.raises(TypeError):
        normalize_signal_route(" BTCUSDT:1h ")


def test_parse_signal_routes_rejects_non_lists_and_duplicates() -> None:
    with pytest.raises(TypeError):
        parse_signal_routes("BTCUSDT:1h")
    with pytest.raises(TypeError):
        parse_signal_routes([1])
    with pytest.raises(ValueError):
        parse_signal_routes(["BTCUSDT:1h", "BTCUSDT:1h"])


def test_route_helpers_build_asset_maps_and_assets_in_declared_order() -> None:
    routes = parse_signal_routes(["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"])
    assert asset_map_from_routes(routes) == {
        "BTCUSDT": ["1h", "4h"],
        "ETHUSDT": ["4h"],
    }
    assert assets_from_routes(routes) == ["BTCUSDT", "ETHUSDT"]


def test_production_decision_and_risk_routes_match_exact_final_set() -> None:
    manager = ConfigManager(config_dir=".")
    try:
        decision = load_decision_config(manager)
        decision_routes = decision_authoritative_routes_from_config(decision.assets)
        manager.register_file("configs/risk.yaml")
        risk_routes = parse_signal_routes(manager.get("risk.runtime.signal_routes", ()))
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert decision_routes == ("BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h")
    assert risk_routes == decision_routes
