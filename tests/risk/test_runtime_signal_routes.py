from __future__ import annotations

from dataclasses import dataclass

import pytest

from apps.risk_app.main import _discover_runtime_asset_map


@dataclass
class _Manifest:
    symbol: str
    enabled: bool
    desired_state: str


class _Config:
    def __init__(self, routes):
        self._routes = routes

    def get(self, key: str, default=None):
        if key == "risk.runtime.signal_routes":
            return self._routes
        return default


class _Store:
    def __init__(self, manifests):
        self._manifests = manifests

    async def list_assets(self):
        return self._manifests


@pytest.mark.asyncio
async def test_discover_runtime_asset_map_uses_configured_routes_and_manifest_liveness() -> (
    None
):
    asset_map, listener_assets = await _discover_runtime_asset_map(
        _Config(["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"]),
        _Store(
            [
                _Manifest("BTCUSDT", True, "LIVE"),
                _Manifest("ETHUSDT", False, "LIVE"),
            ]
        ),
    )

    assert asset_map == {"BTCUSDT": ["1h", "4h"]}
    assert listener_assets == {"BTCUSDT", "ETHUSDT"}


@pytest.mark.asyncio
async def test_discover_runtime_asset_map_rejects_malformed_routes() -> None:
    with pytest.raises(ValueError):
        await _discover_runtime_asset_map(
            _Config(["BTCUSDT:1h", "BTCUSDT:1h"]),
            _Store([]),
        )
