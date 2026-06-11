from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.ingestion_app.asset_registry import (
    IngestionAssetCatalog,
    IngestionControlService,
    IngestionAssetRegistryRepository,
)
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetRecord,
    IngestionAssetSource,
    IngestionAssetUpsertRequest,
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


@pytest.mark.asyncio
async def test_registry_repository_returns_persisted_assets():
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
async def test_asset_catalog_falls_back_to_config_when_registry_empty():
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
async def test_asset_catalog_prefers_registry_over_config():
    config_manager = FakeConfigManager(
        {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.assets.publish_timeframes": {"BTCUSDT": ["4h"]},
            "ingestion.timeframes.base_gap_fill": "1m",
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
                    "historical_backfill_days": 2,
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
    record = await catalog.get_effective_asset("ethusdt")

    assert record is not None
    assert record.symbol == "ETHUSDT"
    assert record.source == IngestionAssetSource.REGISTRY


@pytest.mark.asyncio
async def test_asset_catalog_merges_registry_overrides_with_config_defaults():
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
async def test_control_service_upsert_persists_and_publishes():
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


class FakeValkey:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def xadd(self, stream: str, payload: dict[str, str], **kwargs):
        self.calls.append((stream, payload))
        return "123-0"
