from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.ingestion_app.asset_registry import (
    IngestionAssetCatalog,
    IngestionAssetRegistryRepository,
    IngestionControlPublisher,
    IngestionControlService,
)
from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM, INGESTION_EVENTS_STREAM
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetRecord,
    IngestionAssetSource,
    IngestionAssetPatchRequest,
    IngestionAssetUpsertRequest,
)
from libs.common.asset_manifest import (
    ASSET_LIFECYCLE_STREAM,
    AssetManifestStore,
    asset_manifest_key,
    asset_timeframe_manifest_key,
)
from libs.contracts.schemas import IngestionCommandType


class FakeConfigManager:
    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


class FakeConnection:
    def __init__(self, *, fetch_results=None, fetchrow_results=None):
        self.fetch_results = list(fetch_results or [])
        self.fetchrow_results = list(fetchrow_results or [])

    async def fetch(self, query, *args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []

    async def fetchrow(self, query, *args):
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None


class FakePool:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def acquire(self):
        return _Ctx(self._conn)


class _Ctx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return None


class FakeValkey:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.hash_calls: list[tuple[str, dict[str, str]]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def xadd(self, stream: str, payload: dict[str, str], **kwargs):
        self.calls.append((stream, payload))
        return "123-0"

    async def hset(self, key: str, mapping: dict[str, str]):
        self.hash_calls.append((key, mapping))
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def keys(self, pattern: str):
        prefix = pattern.rstrip("*")
        return [key for key in self.hashes if key.startswith(prefix)]

    async def set(self, key: str, value: str):
        self.set_calls.append((key, value))
        self.values[key] = value
        return True

    async def get(self, key: str):
        return self.values.get(key)

    async def delete(self, key: str):
        self.delete_calls.append(key)
        self.values.pop(key, None)
        self.hashes.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_v2_registry_repository_returns_persisted_assets():
    conn = FakeConnection(
        fetch_results=[
            [
                {
                    "symbol": "btcusdt",
                    "exchange": "binance",
                    "provider": "binance_native",
                    "base_timeframe": "1m",
                    "publish_timeframes": ["30m", "1h", "4h"],
                    "historical_backfill_days": 2,
                    "retention_days": 90,
                    "enabled": True,
                    "desired_state": "LIVE",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        ]
    )

    repo = IngestionAssetRegistryRepository(FakePool(conn))
    records = await repo.list_assets()

    assert len(records) == 1
    assert records[0].symbol == "BTCUSDT"
    assert records[0].publish_timeframes == ["30m", "1h", "4h"]
    assert records[0].source == IngestionAssetSource.REGISTRY


@pytest.mark.asyncio
async def test_v2_asset_catalog_falls_back_to_config_when_registry_empty():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT", "ETHUSDT"],
            "ingestion.assets.publish_timeframes": {
                "BTCUSDT": ["1h", "4h"],
                "ETHUSDT": ["4h"],
            },
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.assets.historical_backfill_days": 3,
        }
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(FakeConnection()))
    records = await catalog.list_effective_assets()

    assert [record.symbol for record in records] == ["BTCUSDT", "ETHUSDT"]
    assert all(record.source == IngestionAssetSource.CONFIG for record in records)
    assert records[0].historical_backfill_days == 3


@pytest.mark.asyncio
async def test_v2_asset_catalog_derives_runtime_trigger_lanes_from_models_config():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.assets.publish_timeframes": {"BTCUSDT": []},
            "ingestion.timeframes.base_gap_fill": "1m",
            "models": {
                "assets": {
                    "BTCUSDT": {
                        "timeframes": {
                            "4h": {
                                "Momentum": {
                                    "enabled": True,
                                    "runtime": {
                                        "decision_timeframe": "4h",
                                        "base_timeframe": "1m",
                                        "trigger_mode": "on_base_bar_close",
                                    },
                                }
                            },
                            "1h": {
                                "MeanReversion": {
                                    "enabled": True,
                                    "runtime": {
                                        "decision_timeframe": "1h",
                                        "base_timeframe": "1m",
                                        "trigger_mode": "on_bar_close",
                                    },
                                }
                            },
                        }
                    }
                }
            },
        }
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(FakeConnection()))
    records = await catalog.list_effective_assets()

    assert len(records) == 1
    assert records[0].symbol == "BTCUSDT"
    assert records[0].publish_timeframes == ["1h"]


@pytest.mark.asyncio
async def test_v2_asset_catalog_prefers_registry_over_config():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.assets.publish_timeframes": {"BTCUSDT": ["4h"]},
            "ingestion.timeframes.base_gap_fill": "1m",
        }
    )
    conn = FakeConnection(
        fetchrow_results=[
            {
                "symbol": "ETHUSDT",
                "exchange": "binance",
                "provider": "binance_native",
                "base_timeframe": "1m",
                "publish_timeframes": ["30m", "1h"],
                "historical_backfill_days": 2,
                "retention_days": None,
                "enabled": True,
                "desired_state": "LIVE",
                "created_at": None,
                "updated_at": None,
            }
        ]
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(conn))
    record = await catalog.get_effective_asset("ethusdt")

    assert record is not None
    assert record.symbol == "ETHUSDT"
    assert record.source == IngestionAssetSource.REGISTRY


@pytest.mark.asyncio
async def test_v2_asset_catalog_merges_registry_lanes_with_runtime_trigger_lanes():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.assets.publish_timeframes": {"BTCUSDT": []},
            "ingestion.timeframes.base_gap_fill": "1m",
            "models": {
                "assets": {
                    "BTCUSDT": {
                        "timeframes": {
                            "1h": {
                                "Momentum": {
                                    "enabled": True,
                                    "runtime": {
                                        "decision_timeframe": "1h",
                                        "base_timeframe": "1m",
                                        "trigger_mode": "on_bar_close",
                                    },
                                }
                            }
                        }
                    }
                }
            },
        }
    )
    conn = FakeConnection(
        fetchrow_results=[
            {
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "provider": "binance_native",
                "base_timeframe": "1m",
                "publish_timeframes": ["4h"],
                "historical_backfill_days": 2,
                "retention_days": None,
                "enabled": True,
                "desired_state": "LIVE",
                "created_at": None,
                "updated_at": None,
            }
        ]
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(conn))
    record = await catalog.get_effective_asset("BTCUSDT")

    assert record is not None
    assert record.source == IngestionAssetSource.REGISTRY
    assert record.publish_timeframes == ["4h", "1h"]


@pytest.mark.asyncio
async def test_v2_asset_catalog_get_effective_asset_uses_direct_registry_lookup():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.assets.publish_timeframes": {"BTCUSDT": ["4h"]},
            "ingestion.timeframes.base_gap_fill": "1m",
        }
    )
    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(FakeConnection()))

    with patch.object(
        IngestionAssetRegistryRepository,
        "get_asset",
        AsyncMock(return_value=IngestionAssetRecord(symbol="ETHUSDT")),
    ), patch.object(IngestionAssetCatalog, "_load_registry_assets", AsyncMock()) as mock_list_loader:
        record = await catalog.get_effective_asset("ETHUSDT")

    assert record is not None
    assert record.symbol == "ETHUSDT"
    mock_list_loader.assert_not_called()


@pytest.mark.asyncio
async def test_v2_asset_catalog_merges_registry_overrides_with_config_defaults():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT", "ETHUSDT"],
            "ingestion.assets.publish_timeframes": {
                "BTCUSDT": ["4h"],
                "ETHUSDT": ["1h"],
            },
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.assets.historical_backfill_days": 2,
        }
    )
    conn = FakeConnection(
        fetch_results=[
            [
                {
                    "symbol": "ETHUSDT",
                    "exchange": "binance",
                    "provider": "binance_native",
                    "base_timeframe": "1m",
                    "publish_timeframes": ["30m", "1h"],
                    "historical_backfill_days": 5,
                    "retention_days": None,
                    "enabled": True,
                    "desired_state": "LIVE",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        ]
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(conn))
    records = await catalog.list_effective_assets()

    assert [record.symbol for record in records] == ["BTCUSDT", "ETHUSDT"]
    assert records[0].source == IngestionAssetSource.CONFIG
    assert records[1].source == IngestionAssetSource.REGISTRY
    assert records[1].historical_backfill_days == 5


@pytest.mark.asyncio
async def test_v2_asset_catalog_keeps_registry_tombstone_over_config_defaults():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["SOLUSDT"],
            "ingestion.assets.publish_timeframes": {"SOLUSDT": ["1h", "4h"]},
            "ingestion.timeframes.base_gap_fill": "1m",
        }
    )
    conn = FakeConnection(
        fetch_results=[
            [
                {
                    "symbol": "SOLUSDT",
                    "exchange": "binance",
                    "provider": "binance_native",
                    "base_timeframe": "1m",
                    "publish_timeframes": ["1m"],
                    "historical_backfill_days": 1,
                    "retention_days": None,
                    "enabled": False,
                    "desired_state": "STOPPED",
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        ]
    )

    catalog = IngestionAssetCatalog(config_manager=config_manager, pool=FakePool(conn))
    records = await catalog.list_effective_assets()

    assert len(records) == 1
    assert records[0].symbol == "SOLUSDT"
    assert records[0].source == IngestionAssetSource.REGISTRY
    assert records[0].enabled is False
    assert records[0].desired_state == IngestionAssetDesiredState.STOPPED


@pytest.mark.asyncio
async def test_v2_control_publisher_publishes_two_stream_messages():
    asset = IngestionAssetRecord(
        symbol="SOLUSDT",
        publish_timeframes=["1h", "4h"],
        source=IngestionAssetSource.REGISTRY,
    )
    publisher = IngestionControlPublisher(FakeValkey())

    result = await publisher.publish(
        asset=asset,
        command_type=IngestionCommandType.UPSERT_ASSET,
        requested_by="api_app",
        reason="new asset",
    )

    assert result.command_published is True
    assert result.event_published is True
    assert [stream for stream, _ in publisher.valkey_client.calls] == [
        INGESTION_CONTROL_STREAM,
        INGESTION_EVENTS_STREAM,
        ASSET_LIFECYCLE_STREAM,
    ]
    assert asset_manifest_key("SOLUSDT") in publisher.valkey_client.hashes
    assert asset_timeframe_manifest_key("SOLUSDT", "1m") in publisher.valkey_client.hashes
    assert asset_timeframe_manifest_key("SOLUSDT", "1h") in publisher.valkey_client.hashes
    assert asset_timeframe_manifest_key("SOLUSDT", "4h") in publisher.valkey_client.hashes


@pytest.mark.asyncio
async def test_v2_control_publisher_emits_effective_runtime_lanes_in_manifest_and_result():
    config_manager = FakeConfigManager(
        {
            "models": {
                "assets": {
                    "SOLUSDT": {
                        "timeframes": {
                            "1h": {
                                "Momentum": {
                                    "enabled": True,
                                    "runtime": {
                                        "decision_timeframe": "1h",
                                        "base_timeframe": "1m",
                                        "trigger_mode": "on_bar_close",
                                    },
                                }
                            }
                        }
                    }
                }
            }
        }
    )
    asset = IngestionAssetRecord(
        symbol="SOLUSDT",
        publish_timeframes=[],
        source=IngestionAssetSource.REGISTRY,
    )
    valkey = FakeValkey()
    publisher = IngestionControlPublisher(valkey, config_manager=config_manager)

    result = await publisher.publish(
        asset=asset,
        command_type=IngestionCommandType.UPSERT_ASSET,
        requested_by="api_app",
        reason="new asset",
    )

    manifest = await AssetManifestStore(valkey).read_asset("SOLUSDT")

    assert result.asset.publish_timeframes == ["1h"]
    assert manifest is not None
    assert manifest.publish_timeframes == ["1h"]
    assert manifest.timeframes == ["1m", "1h"]
    assert asset_timeframe_manifest_key("SOLUSDT", "1h") in valkey.hashes


@pytest.mark.asyncio
async def test_v2_control_service_upsert_persists_and_publishes():
    persisted = IngestionAssetRecord(
        symbol="SOLUSDT",
        publish_timeframes=["1h", "4h"],
        source=IngestionAssetSource.REGISTRY,
    )
    service = IngestionControlService(pool=FakePool(FakeConnection()), valkey_client=FakeValkey())
    service.repo.upsert_asset = AsyncMock(return_value=persisted)

    result = await service.upsert_asset(
        IngestionAssetUpsertRequest(
            symbol="SOLUSDT",
            publish_timeframes=["1h", "4h"],
            reason="new asset",
        ),
        command_type=IngestionCommandType.UPSERT_ASSET,
    )

    assert result.asset.symbol == "SOLUSDT"
    assert result.command_type == IngestionCommandType.UPSERT_ASSET.value
    assert result.command_published is True
    assert result.event_published is True


@pytest.mark.asyncio
async def test_v2_control_service_patch_persists_and_publishes():
    existing = IngestionAssetRecord(
        symbol="BTCUSDT",
        publish_timeframes=["1h"],
        source=IngestionAssetSource.REGISTRY,
    )
    persisted = existing.model_copy(update={"publish_timeframes": ["4h"]})
    service = IngestionControlService(
        pool=FakePool(FakeConnection()),
        valkey_client=FakeValkey(),
        config_manager=FakeConfigManager({}),
    )
    service.repo.upsert_asset = AsyncMock(return_value=persisted)

    result = await service.patch_asset(
        existing,
        IngestionAssetPatchRequest(publish_timeframes=["4h"], reason="rebalance"),
    )

    assert result.asset.publish_timeframes == ["4h"]
    assert result.command_type == IngestionCommandType.UPDATE_ASSET.value
    assert result.command_published is True
    assert result.event_published is True


@pytest.mark.asyncio
async def test_v2_control_service_apply_action_persists_and_publishes():
    existing = IngestionAssetRecord(
        symbol="BTCUSDT",
        publish_timeframes=["1h"],
        source=IngestionAssetSource.REGISTRY,
    )
    persisted = existing.model_copy(update={"desired_state": "PAUSED", "enabled": True})
    valkey = FakeValkey()
    service = IngestionControlService(pool=FakePool(FakeConnection()), valkey_client=valkey)
    service.repo.upsert_asset = AsyncMock(return_value=persisted)

    result = await service.apply_action(
        existing,
        desired_state=IngestionAssetDesiredState.PAUSED,
        enabled=True,
        action=IngestionCommandType.PAUSE_ASSET,
        body=IngestionAssetActionRequest(reason="maintenance"),
    )

    assert result.asset.symbol == "BTCUSDT"
    assert result.command_type == IngestionCommandType.PAUSE_ASSET.value
    assert result.command_published is True
    assert result.event_published is True
    assert valkey.set_calls == [("ingestion:resume_backfill_required:BTCUSDT:1m", "1")]


@pytest.mark.asyncio
async def test_v2_control_service_apply_action_keeps_registry_persistence_raw_but_publishes_effective():
    config_manager = FakeConfigManager(
        {
            "models": {
                "assets": {
                    "BTCUSDT": {
                        "timeframes": {
                            "1h": {
                                "Momentum": {
                                    "enabled": True,
                                    "runtime": {
                                        "decision_timeframe": "1h",
                                        "base_timeframe": "1m",
                                        "trigger_mode": "on_bar_close",
                                    },
                                }
                            }
                        }
                    }
                }
            }
        }
    )
    existing_effective = IngestionAssetRecord(
        symbol="BTCUSDT",
        publish_timeframes=["1h"],
        source=IngestionAssetSource.REGISTRY,
    )
    persisted_raw = existing_effective.model_copy(update={"publish_timeframes": []})
    valkey = FakeValkey()
    service = IngestionControlService(
        pool=FakePool(FakeConnection()),
        valkey_client=valkey,
        config_manager=config_manager,
    )
    service.repo.get_asset = AsyncMock(return_value=persisted_raw)
    service.repo.upsert_asset = AsyncMock(
        return_value=persisted_raw.model_copy(
            update={"desired_state": IngestionAssetDesiredState.PAUSED, "enabled": True}
        )
    )

    result = await service.apply_action(
        existing_effective,
        desired_state=IngestionAssetDesiredState.PAUSED,
        enabled=True,
        action=IngestionCommandType.PAUSE_ASSET,
        body=IngestionAssetActionRequest(reason="maintenance"),
    )

    persisted_arg = service.repo.upsert_asset.await_args.args[0]
    assert persisted_arg.publish_timeframes == []
    assert result.asset.publish_timeframes == ["1h"]
    assert valkey.set_calls == [("ingestion:resume_backfill_required:BTCUSDT:1m", "1")]


@pytest.mark.asyncio
async def test_v2_control_service_resume_persists_resuming_without_lifecycle_event():
    existing = IngestionAssetRecord(
        symbol="BTCUSDT",
        publish_timeframes=["1h"],
        source=IngestionAssetSource.REGISTRY,
        desired_state=IngestionAssetDesiredState.PAUSED,
    )
    persisted = existing.model_copy(
        update={"desired_state": IngestionAssetDesiredState.RESUMING, "enabled": True}
    )
    valkey = FakeValkey()
    service = IngestionControlService(pool=FakePool(FakeConnection()), valkey_client=valkey)
    service.repo.upsert_asset = AsyncMock(return_value=persisted)

    result = await service.apply_action(
        existing,
        desired_state=IngestionAssetDesiredState.LIVE,
        enabled=True,
        action=IngestionCommandType.RESUME_ASSET,
        body=IngestionAssetActionRequest(reason="resume"),
    )

    assert result.asset.desired_state == IngestionAssetDesiredState.RESUMING
    assert [stream for stream, _ in valkey.calls] == [
        INGESTION_CONTROL_STREAM,
        INGESTION_EVENTS_STREAM,
    ]


@pytest.mark.asyncio
async def test_asset_manifest_store_prunes_stale_timeframes():
    valkey = FakeValkey()
    store = AssetManifestStore(valkey)

    await store.sync_from_ingestion_asset(
        IngestionAssetRecord(
            symbol="BTCUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h", "4h"],
            source=IngestionAssetSource.REGISTRY,
        ),
        updated_at=100.0,
    )
    await store.sync_from_ingestion_asset(
        IngestionAssetRecord(
            symbol="BTCUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h"],
            source=IngestionAssetSource.REGISTRY,
        ),
        updated_at=200.0,
    )

    manifest = await store.read_asset("BTCUSDT")
    timeframe = await store.read_timeframe("BTCUSDT", "1h")

    assert manifest is not None
    assert manifest.timeframes == ["1m", "1h"]
    assert timeframe is not None
    assert timeframe.timeframe == "1h"
    assert asset_timeframe_manifest_key("BTCUSDT", "4h") in valkey.delete_calls


@pytest.mark.asyncio
async def test_asset_manifest_store_lists_live_runtime_pairs_only():
    valkey = FakeValkey()
    store = AssetManifestStore(valkey)

    await store.sync_from_ingestion_asset(
        IngestionAssetRecord(
            symbol="BTCUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h", "4h"],
            desired_state=IngestionAssetDesiredState.LIVE,
            source=IngestionAssetSource.REGISTRY,
        ),
        updated_at=100.0,
    )
    await store.sync_from_ingestion_asset(
        IngestionAssetRecord(
            symbol="ETHUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h"],
            desired_state=IngestionAssetDesiredState.PAUSED,
            source=IngestionAssetSource.REGISTRY,
        ),
        updated_at=200.0,
    )

    assert await store.list_runtime_pairs() == [
        ("BTCUSDT", "1m"),
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "4h"),
    ]


@pytest.mark.asyncio
async def test_asset_manifest_store_skips_non_hash_asset_keys():
    class MixedKeyValkey(FakeValkey):
        def __init__(self) -> None:
            super().__init__()
            self.key_types: dict[str, str] = {ASSET_LIFECYCLE_STREAM: "stream"}

        async def keys(self, pattern: str):
            return [asset_manifest_key("BTCUSDT"), ASSET_LIFECYCLE_STREAM]

        async def type(self, key: str):
            return self.key_types.get(key, "hash")

    valkey = MixedKeyValkey()
    store = AssetManifestStore(valkey)

    await store.sync_from_ingestion_asset(
        IngestionAssetRecord(
            symbol="BTCUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h"],
            desired_state=IngestionAssetDesiredState.LIVE,
            source=IngestionAssetSource.REGISTRY,
        ),
        updated_at=100.0,
    )

    assert await store.list_runtime_pairs() == [("BTCUSDT", "1m"), ("BTCUSDT", "1h")]
