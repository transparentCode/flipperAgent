from __future__ import annotations

import asyncio
import time

import pytest

from apps.ingestion_app.control_plane.service import IngestionControlService
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetUpsertRequest,
)
from libs.common.db.pool_manager import DBPoolManager
from libs.contracts.schemas import IngestionCommandType


TEST_SYMBOL = "SOLUSDT"
BASE_TIMEFRAME = "1m"
PUBLISH_TIMEFRAMES = ["1m"]
STREAM_KEY = "stream:ohlcv:solusdt:1m"


async def _wait_until(predicate, *, timeout_s: float, interval_s: float = 1.0, description: str):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for {description}")


async def _fetch_symbol_count(table: str, symbol: str) -> int:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"SELECT COUNT(*) AS cnt FROM {table} WHERE symbol = $1", symbol)
    return int(row["cnt"])


async def _ingestion_asset_exists(symbol: str) -> bool:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM ingestion_assets WHERE symbol = $1",
            symbol,
        )
    return row is not None


@pytest.mark.asyncio
@pytest.mark.slow
async def test_runtime_asset_addition_backfill_live_stream_and_removal(db_pools, valkey_client):
    service = IngestionControlService(
        pool=DBPoolManager.get_writer_pool(),
        valkey_client=valkey_client,
    )
    coordinator = IngestionCoordinator(valkey_client)

    result = await service.upsert_asset(
        IngestionAssetUpsertRequest(
            symbol=TEST_SYMBOL,
            base_timeframe=BASE_TIMEFRAME,
            publish_timeframes=PUBLISH_TIMEFRAMES,
            historical_backfill_days=1,
            desired_state=IngestionAssetDesiredState.LIVE,
            requested_by="tests.e2e",
            reason="runtime lifecycle validation",
        ),
        command_type=IngestionCommandType.UPSERT_ASSET,
    )

    assert result.command_published is True
    assert result.event_published is True

    observed_states: list[str] = []

    async def _live_snapshot():
        snapshot = await coordinator.get_observability_snapshot(TEST_SYMBOL, BASE_TIMEFRAME)
        state = snapshot["state"]
        if not observed_states or observed_states[-1] != state:
            observed_states.append(state)
        if snapshot["last_live_ts"] and state == IngestionState.LIVE.value:
            return snapshot
        return None

    live_snapshot = await _wait_until(
        _live_snapshot,
        timeout_s=240,
        interval_s=1,
        description=f"{TEST_SYMBOL} to reach LIVE state",
    )

    assert await _ingestion_asset_exists(TEST_SYMBOL) is True
    assert observed_states[-1] == IngestionState.LIVE.value, f"Unexpected state history: {observed_states}"
    assert live_snapshot["disconnects_in_window"] >= 0

    ohlcv_count = await _wait_until(
        lambda: _fetch_symbol_count("ohlcv", TEST_SYMBOL),
        timeout_s=120,
        interval_s=2,
        description=f"{TEST_SYMBOL} OHLCV backfill rows",
    )
    assert ohlcv_count > 0

    stream_len = await _wait_until(
        lambda: valkey_client.xlen(STREAM_KEY),
        timeout_s=120,
        interval_s=2,
        description=f"{STREAM_KEY} to receive candle-close entries",
    )
    assert stream_len > 0

    remove_result = await service.apply_action(
        result.asset,
        desired_state=IngestionAssetDesiredState.REMOVING,
        enabled=False,
        action=IngestionCommandType.REMOVE_ASSET,
        body=IngestionAssetActionRequest(
            requested_by="tests.e2e",
            reason="runtime lifecycle validation cleanup",
        ),
    )

    assert remove_result.command_published is True

    await _wait_until(
        lambda: _asset_removed(TEST_SYMBOL),
        timeout_s=180,
        interval_s=2,
        description=f"{TEST_SYMBOL} registry deletion",
    )

    assert await _fetch_symbol_count("ohlcv", TEST_SYMBOL) == 0
    assert await _fetch_symbol_count("ticks", TEST_SYMBOL) == 0
    assert await _fetch_symbol_count("open_interest", TEST_SYMBOL) == 0
    assert await _fetch_symbol_count("funding_rate", TEST_SYMBOL) == 0
    assert await _fetch_symbol_count("l2_depth_features", TEST_SYMBOL) == 0

    state_key = IngestionCoordinator._state_key(TEST_SYMBOL, BASE_TIMEFRAME)
    disconnect_key = IngestionCoordinator._disconnect_ts_key(TEST_SYMBOL, BASE_TIMEFRAME)
    last_live_key = IngestionCoordinator._last_live_ts_key(TEST_SYMBOL, BASE_TIMEFRAME)
    disconnect_count_key = IngestionCoordinator._disconnect_count_key(TEST_SYMBOL, BASE_TIMEFRAME)

    assert await valkey_client.exists(state_key) == 0
    assert await valkey_client.exists(disconnect_key) == 0
    assert await valkey_client.exists(last_live_key) == 0
    assert await valkey_client.exists(disconnect_count_key) == 0
    assert await valkey_client.exists(STREAM_KEY) == 0


async def _asset_removed(symbol: str) -> bool:
    return not await _ingestion_asset_exists(symbol)
