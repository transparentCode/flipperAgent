from __future__ import annotations

import pytest

from apps.risk_app.main import _discover_runtime_asset_map
from libs.common.asset_manifest import AssetManifest
from libs.common.config import ConfigManager


class _ManifestStore:
    def __init__(self, manifests: list[AssetManifest]) -> None:
        self.manifests = manifests

    async def list_assets(self) -> list[AssetManifest]:
        return list(self.manifests)


def _config_manager() -> ConfigManager:
    ConfigManager.reset_singleton()
    manager = ConfigManager()
    manager._state = {
        "models": {
            "assets": {
                "BTCUSDT": {"timeframes": {"1h": {}}},
                "ETHUSDT": {"timeframes": {"4h": {}}},
            }
        }
    }
    return manager


@pytest.mark.asyncio
async def test_partial_manifests_gate_risk_workers_without_inventing_assets() -> None:
    manager = _config_manager()
    try:
        asset_map, listener_assets = await _discover_runtime_asset_map(
            manager,
            _ManifestStore(
                [
                    AssetManifest(
                        symbol="BTCUSDT",
                        enabled=True,
                        desired_state="LIVE",
                        updated_at=1.0,
                    )
                ]
            ),
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert asset_map == {"BTCUSDT": ["1h"], "ETHUSDT": ["4h"]}
    assert listener_assets == {"BTCUSDT", "ETHUSDT"}


@pytest.mark.asyncio
async def test_stopped_manifest_suppresses_configured_risk_worker_only() -> None:
    manager = _config_manager()
    try:
        asset_map, listener_assets = await _discover_runtime_asset_map(
            manager,
            _ManifestStore(
                [
                    AssetManifest(
                        symbol="BTCUSDT",
                        enabled=False,
                        desired_state="STOPPED",
                        updated_at=1.0,
                    )
                ]
            ),
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()

    assert asset_map == {"ETHUSDT": ["4h"]}
    assert listener_assets == {"BTCUSDT", "ETHUSDT"}
