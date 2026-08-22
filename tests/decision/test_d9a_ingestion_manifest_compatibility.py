from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.decision_app.composition import build_production_composition
from apps.decision_app.features.planning import compile_feature_plan
from apps.decision_app.planning.planner import compile_decision_plan
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import load_decision_config
from apps.ingestion_app.services.asset_lifecycle import AssetLifecycleService
from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager


class _ManifestValkey:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, *, mapping: dict[str, str]) -> int:
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def delete(self, key: str) -> int:
        self.hashes.pop(key, None)
        return 1


@pytest.fixture(autouse=True)
def isolated_config_manager():
    ConfigManager.reset_singleton()
    yield
    ConfigManager.reset_singleton()


@pytest.mark.asyncio
async def test_real_ingestion_manifests_activate_decision_runtime_assets() -> None:
    manager = ConfigManager()
    try:
        ingestion_config = load_ingestion_settings(manager)
        decision_config = load_decision_config(manager)
        ingestion_service = AssetLifecycleService()
        manifest_store = AssetManifestStore(_ManifestValkey())

        for config_asset, runtime_asset in (
            ("BTC", "BTCUSDT"),
            ("ETH", "ETHUSDT"),
        ):
            manifest, timeframe_manifests = ingestion_service.build_manifests(
                ingestion_config.assets[config_asset],
                ingestion_config,
            )
            assert manifest.symbol == runtime_asset
            assert {item.symbol for item in timeframe_manifests} == {runtime_asset}
            await manifest_store.sync_manifest(manifest, timeframe_manifests)

        assert {asset.manifest_asset for asset in decision_config.active_assets} == {
            "BTC",
            "ETH",
        }
        assert {asset.decision_asset for asset in decision_config.active_assets} == {
            "BTCUSDT",
            "ETHUSDT",
        }
        assert await manifest_store.read_asset("BTC") is None
        assert await manifest_store.read_asset("ETH") is None

        composition = build_production_composition(decision_config)
        decision_plan = compile_decision_plan(
            composition.plugin_catalog,
            decision_config.lane_specs(),
        )
        feature_plans = {
            lane.lane_id: compile_feature_plan(
                lane,
                composition.feature_catalog,
                composition.feature_policy,
                decision_config.timeframe_grid,
            )
            for lane in decision_plan.lanes
        }
        coordinator = DecisionStartupCoordinator(
            decision_config=decision_config,
            plugin_catalog=composition.plugin_catalog,
            feature_catalog=composition.feature_catalog,
            feature_policy=composition.feature_policy,
            data_policy=composition.data_policy,
            source_catalog=composition.data_source_catalog,
            runtime_plugin_catalog=composition.runtime_plugin_catalog,
            history_repository=SimpleNamespace(fetch_bars=lambda *_args, **_kwargs: ()),
            manifest_store=manifest_store,
            policy_catalog=composition.policy_catalog,
            data_resolver=composition.data_resolver,
            checkpoint_repository=None,
        )

        active_assets = await coordinator._active_manifest_assets(
            decision_plan,
            feature_plans,
        )

        assert active_assets == {"BTCUSDT", "ETHUSDT"}
    finally:
        manager.shutdown()
