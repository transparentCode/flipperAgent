from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.ingestion_app.storage.janitor import IngestionStorageJanitor
from apps.ingestion_app.jobs.cleanup import purge_removed_asset, scheduled_asset_cleanup
from libs.common.asset_manifest import asset_manifest_key, asset_timeframe_manifest_key


class FakeConnection:
    def __init__(self) -> None:
        self.deleted_tables: list[str] = []

    async def fetch(self, query, *args):
        return [
            {"symbol": "BTCUSDT", "base_timeframe": "1m"},
            {"symbol": "ETHUSDT", "base_timeframe": "1m"},
        ]

    async def fetchval(self, query, table):
        return table

    async def execute(self, query, *args):
        if "UPDATE ingestion_assets" in query:
            return "UPDATE 1"
        for table in ("ohlcv", "ticks", "open_interest", "funding_rate", "l2_depth_features"):
            if f"DELETE FROM {table}" in query:
                self.deleted_tables.append(table)
                return "DELETE 2"
        return "DELETE 0"


class FakePool:
    def __init__(self, conn) -> None:
        self._conn = conn

    def acquire(self):
        return _Ctx(self._conn)


class _Ctx:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_storage_janitor_lists_pending_removals_and_purges_rows():
    conn = FakeConnection()
    janitor = IngestionStorageJanitor(FakePool(conn))

    pending = await janitor.list_pending_removals()
    deleted = await janitor.purge_asset_data("BTCUSDT")
    finalized = await janitor.finalize_asset_removal("BTCUSDT")

    assert pending == [("BTCUSDT", "1m"), ("ETHUSDT", "1m")]
    assert deleted["ohlcv"] == 2
    assert deleted["l2_depth_features"] == 2
    assert finalized is True


@pytest.mark.asyncio
async def test_purge_removed_asset_clears_keys_and_emits_completion_event():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.purge_asset_data = AsyncMock(return_value={"ohlcv": 5})
    janitor.finalize_asset_removal = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_asset = AsyncMock(return_value=MagicMock(publish_timeframes=["1m", "1h"]))

    with patch(
        "apps.ingestion_app.jobs.cleanup.IngestionStorageJanitor",
        return_value=janitor,
    ), patch(
        "apps.ingestion_app.jobs.cleanup.IngestionAssetRegistryRepository",
        return_value=registry,
    ), patch(
        "apps.ingestion_app.jobs.cleanup.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.ingestion_app.jobs.cleanup.publish_ingestion_runtime_event",
        new=AsyncMock(),
    ) as mock_publish:
        await purge_removed_asset(ctx, "BTCUSDT", "1m")

    janitor.purge_asset_data.assert_awaited_once_with("BTCUSDT")
    janitor.finalize_asset_removal.assert_awaited_once_with("BTCUSDT")
    assert ctx["valkey_client"].delete.await_count == 15
    deleted_keys = [call.args[0] for call in ctx["valkey_client"].delete.await_args_list]
    assert asset_manifest_key("BTCUSDT") in deleted_keys
    assert asset_timeframe_manifest_key("BTCUSDT", "1m") in deleted_keys
    assert asset_timeframe_manifest_key("BTCUSDT", "1h") in deleted_keys
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduled_asset_cleanup_replays_pending_removals():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.list_pending_removals = AsyncMock(return_value=[("BTCUSDT", "1m"), ("ETHUSDT", "4h")])

    with patch(
        "apps.ingestion_app.jobs.cleanup.IngestionStorageJanitor",
        return_value=janitor,
    ), patch(
        "apps.ingestion_app.jobs.cleanup.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.ingestion_app.jobs.cleanup.purge_removed_asset",
        new=AsyncMock(),
    ) as mock_purge:
        await scheduled_asset_cleanup(ctx)

    assert mock_purge.await_count == 2
