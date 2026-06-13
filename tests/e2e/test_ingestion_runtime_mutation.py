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


async def _fetch_asset_flags(symbol: str) -> tuple[str, bool] | None:
    pool = DBPoolManager.get_reader_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT desired_state, enabled FROM ingestion_assets WHERE symbol = $1",
            symbol,
        )
    if row is None:
        return None
    return str(row["desired_state"]), bool(row["enabled"])


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


@pytest.mark.asyncio
@pytest.mark.slow
async def test_runtime_asset_pause_and_resume_lifecycle(db_pools, valkey_client):
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
            reason="pause resume validation",
        ),
        command_type=IngestionCommandType.UPSERT_ASSET,
    )

    assert result.command_published is True

    remove_requested = False
    try:
        await _wait_until(
            lambda: _fetch_asset_flags(TEST_SYMBOL),
            timeout_s=60,
            interval_s=1,
            description=f"{TEST_SYMBOL} asset registry row",
        )

        await _wait_until(
            lambda: _live_state_snapshot(coordinator),
            timeout_s=240,
            interval_s=1,
            description=f"{TEST_SYMBOL} to reach LIVE state",
        )

        initial_stream_len = await _wait_until(
            lambda: valkey_client.xlen(STREAM_KEY),
            timeout_s=120,
            interval_s=2,
            description=f"{STREAM_KEY} to receive initial candle-close entries",
        )
        assert initial_stream_len > 0

        pause_result = await service.apply_action(
            result.asset,
            desired_state=IngestionAssetDesiredState.PAUSED,
            enabled=True,
            action=IngestionCommandType.PAUSE_ASSET,
            body=IngestionAssetActionRequest(
                requested_by="tests.e2e",
                reason="pause runtime lifecycle validation",
            ),
        )

        assert pause_result.command_published is True

        paused_flags = await _wait_until(
            lambda: _asset_flags_match(TEST_SYMBOL, IngestionAssetDesiredState.PAUSED.value, True),
            timeout_s=60,
            interval_s=1,
            description=f"{TEST_SYMBOL} to persist paused state",
        )
        assert paused_flags == (IngestionAssetDesiredState.PAUSED.value, True)

        await _wait_until(
            lambda: _cold_state_snapshot(coordinator),
            timeout_s=120,
            interval_s=1,
            description=f"{TEST_SYMBOL} to transition to COLD after pause",
        )

        await asyncio.sleep(3)
        paused_stream_len = await valkey_client.xlen(STREAM_KEY)
        await asyncio.sleep(10)
        assert await valkey_client.xlen(STREAM_KEY) == paused_stream_len

        resume_result = await service.apply_action(
            pause_result.asset,
            desired_state=IngestionAssetDesiredState.LIVE,
            enabled=True,
            action=IngestionCommandType.RESUME_ASSET,
            body=IngestionAssetActionRequest(
                requested_by="tests.e2e",
                reason="resume runtime lifecycle validation",
            ),
        )

        assert resume_result.command_published is True

        resumed_flags = await _wait_until(
            lambda: _asset_flags_match(TEST_SYMBOL, IngestionAssetDesiredState.LIVE.value, True),
            timeout_s=60,
            interval_s=1,
            description=f"{TEST_SYMBOL} to persist resumed state",
        )
        assert resumed_flags == (IngestionAssetDesiredState.LIVE.value, True)

        resumed_snapshot = await _wait_until(
            lambda: _live_state_snapshot(coordinator),
            timeout_s=240,
            interval_s=1,
            description=f"{TEST_SYMBOL} to transition back to LIVE after resume",
        )
        assert resumed_snapshot["disconnects_in_window"] >= 1

        resumed_stream_len = await _wait_until(
            lambda: _stream_len_greater_than(valkey_client, paused_stream_len),
            timeout_s=120,
            interval_s=2,
            description=f"{STREAM_KEY} to resume candle-close entries",
        )
        assert resumed_stream_len > paused_stream_len
    finally:
        if await _ingestion_asset_exists(TEST_SYMBOL):
            await service.apply_action(
                result.asset,
                desired_state=IngestionAssetDesiredState.REMOVING,
                enabled=False,
                action=IngestionCommandType.REMOVE_ASSET,
                body=IngestionAssetActionRequest(
                    requested_by="tests.e2e",
                    reason="pause resume validation cleanup",
                ),
            )
            remove_requested = True

        if remove_requested:
            await _wait_until(
                lambda: _asset_removed(TEST_SYMBOL),
                timeout_s=180,
                interval_s=2,
                description=f"{TEST_SYMBOL} registry deletion after pause/resume validation",
            )


async def _live_state_snapshot(coordinator: IngestionCoordinator):
    snapshot = await coordinator.get_observability_snapshot(TEST_SYMBOL, BASE_TIMEFRAME)
    if snapshot["last_live_ts"] and snapshot["state"] == IngestionState.LIVE.value:
        return snapshot
    return None


async def _cold_state_snapshot(coordinator: IngestionCoordinator):
    snapshot = await coordinator.get_observability_snapshot(TEST_SYMBOL, BASE_TIMEFRAME)
    if snapshot["state"] == IngestionState.COLD.value:
        return snapshot
    return None


async def _stream_len_greater_than(valkey_client, previous_len: int):
    current_len = await valkey_client.xlen(STREAM_KEY)
    if current_len > previous_len:
        return current_len
    return None


async def _asset_flags_match(symbol: str, desired_state: str, enabled: bool):
    flags = await _fetch_asset_flags(symbol)
    if flags == (desired_state, enabled):
        return flags
    return None
