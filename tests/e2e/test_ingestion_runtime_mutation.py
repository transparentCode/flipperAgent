from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio

from apps.ingestion_app.control_plane.service import IngestionControlService
from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM, INGESTION_EVENTS_STREAM
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetUpsertRequest,
)
from libs.common.db.pool_manager import DBPoolManager
from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM
from libs.contracts.schemas import IngestionCommandType


TEST_SYMBOL = "SOLUSDT"
BASE_TIMEFRAME = "1m"
PUBLISH_TIMEFRAMES = ["1m"]
STREAM_KEY = "stream:ohlcv:solusdt:1m"
FEATURE_STREAM_KEY = "features:SOLUSDT:1m"
PRICE_UPDATE_STREAM_KEY = "price_update:SOLUSDT:1m"


async def _wait_until(predicate, *, timeout_s: float, interval_s: float = 1.0, description: str):
    deadline = time.time() + timeout_s
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            value = await predicate()
        except Exception as exc:
            last_error = exc
            value = None
        if value:
            return value
        await asyncio.sleep(interval_s)
    raise AssertionError(f"Timed out waiting for {description}") from last_error


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


async def _purge_symbol_rows(symbol: str) -> None:
    pool = DBPoolManager.get_writer_pool()
    tables = [
        "ohlcv",
        "ticks",
        "open_interest",
        "funding_rate",
        "l2_depth_features",
        "ingestion_assets",
    ]
    async with pool.acquire() as conn:
        for table in tables:
            await conn.execute(f"DELETE FROM {table} WHERE symbol = $1", symbol)


async def _purge_symbol_keys(valkey_client, symbol: str, base_timeframe: str, publish_timeframes: list[str]) -> None:
    runtime_timeframes: list[str] = []
    for timeframe in [base_timeframe, *publish_timeframes]:
        normalized = str(timeframe).strip()
        if normalized and normalized not in runtime_timeframes:
            runtime_timeframes.append(normalized)

    keys: list[str] = [
        f"derivatives:latest:{symbol}:oi",
        f"derivatives:latest:{symbol}:funding",
    ]
    for timeframe in runtime_timeframes:
        keys.extend(
            [
                f"stream:ohlcv:{symbol.lower()}:{timeframe}",
                f"features:{symbol}:{timeframe}",
                f"price_update:{symbol}:{timeframe}",
                f"signals:{symbol}:{timeframe}",
                IngestionCoordinator._state_key(symbol, timeframe),
                IngestionCoordinator._state_updated_ts_key(symbol, timeframe),
                IngestionCoordinator._disconnect_ts_key(symbol, timeframe),
                IngestionCoordinator._last_live_ts_key(symbol, timeframe),
                IngestionCoordinator._last_ready_ts_key(symbol, timeframe),
                IngestionCoordinator._disconnect_count_key(symbol, timeframe),
                IngestionCoordinator._resume_backfill_key(symbol, timeframe),
            ]
        )
    await valkey_client.delete(*keys)


@pytest_asyncio.fixture(autouse=True)
async def ensure_runtime_test_symbols_clean(db_pools, valkey_client):
    for symbol in ("SOLUSDT", "ADAUSDT"):
        await _purge_symbol_rows(symbol)
        await _purge_symbol_keys(valkey_client, symbol, BASE_TIMEFRAME, PUBLISH_TIMEFRAMES)
    await asyncio.sleep(1)
    yield
    for symbol in ("SOLUSDT", "ADAUSDT"):
        await _purge_symbol_rows(symbol)
        await _purge_symbol_keys(valkey_client, symbol, BASE_TIMEFRAME, PUBLISH_TIMEFRAMES)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_runtime_asset_addition_backfill_live_stream_and_removal(
    db_pools,
    valkey_client,
    runtime_config,
):
    service = IngestionControlService(
        pool=DBPoolManager.get_writer_pool(),
        valkey_client=valkey_client,
        config_manager=runtime_config,
    )
    coordinator = IngestionCoordinator(valkey_client, runtime_config)

    result = await service.upsert_asset(
        IngestionAssetUpsertRequest(
            symbol=TEST_SYMBOL,
            base_timeframe=BASE_TIMEFRAME,
            publish_timeframes=PUBLISH_TIMEFRAMES,
            historical_backfill_days=1,
            desired_state=IngestionAssetDesiredState.LIVE,
            request_id=f"e2e-runtime-add-remove-{int(time.time() * 1000)}",
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

    feature_stream_len = await _wait_until(
        lambda: valkey_client.xlen(FEATURE_STREAM_KEY),
        timeout_s=120,
        interval_s=2,
        description=f"{FEATURE_STREAM_KEY} to receive feature entries",
    )
    assert feature_stream_len > 0

    price_update_stream_len = await _wait_until(
        lambda: valkey_client.xlen(PRICE_UPDATE_STREAM_KEY),
        timeout_s=120,
        interval_s=2,
        description=f"{PRICE_UPDATE_STREAM_KEY} to receive price update entries",
    )
    assert price_update_stream_len > 0

    remove_result = await service.apply_action(
        result.asset,
        desired_state=IngestionAssetDesiredState.REMOVING,
        enabled=False,
        action=IngestionCommandType.REMOVE_ASSET,
        body=IngestionAssetActionRequest(
            request_id=f"e2e-runtime-add-remove-cleanup-{int(time.time() * 1000)}",
            requested_by="tests.e2e",
            reason="runtime lifecycle validation cleanup",
        ),
    )

    assert remove_result.command_published is True

    tombstone_flags = await _wait_until(
        lambda: _asset_flags_match(TEST_SYMBOL, IngestionAssetDesiredState.STOPPED.value, False),
        timeout_s=180,
        interval_s=2,
        description=f"{TEST_SYMBOL} tombstone state after removal",
    )
    assert tombstone_flags == (IngestionAssetDesiredState.STOPPED.value, False)

    assert await _wait_until(
        lambda: _symbol_count_zero("ohlcv", TEST_SYMBOL),
        timeout_s=60,
        interval_s=2,
        description=f"{TEST_SYMBOL} OHLCV rows to clear after removal",
    ) is True
    assert await _wait_until(
        lambda: _symbol_count_zero("ticks", TEST_SYMBOL),
        timeout_s=60,
        interval_s=2,
        description=f"{TEST_SYMBOL} tick rows to clear after removal",
    ) is True
    assert await _wait_until(
        lambda: _symbol_count_zero("open_interest", TEST_SYMBOL),
        timeout_s=60,
        interval_s=2,
        description=f"{TEST_SYMBOL} open interest rows to clear after removal",
    ) is True
    assert await _wait_until(
        lambda: _symbol_count_zero("funding_rate", TEST_SYMBOL),
        timeout_s=60,
        interval_s=2,
        description=f"{TEST_SYMBOL} funding rows to clear after removal",
    ) is True
    assert await _wait_until(
        lambda: _symbol_count_zero("l2_depth_features", TEST_SYMBOL),
        timeout_s=60,
        interval_s=2,
        description=f"{TEST_SYMBOL} L2 rows to clear after removal",
    ) is True

    state_key = IngestionCoordinator._state_key(TEST_SYMBOL, BASE_TIMEFRAME)
    disconnect_key = IngestionCoordinator._disconnect_ts_key(TEST_SYMBOL, BASE_TIMEFRAME)
    last_live_key = IngestionCoordinator._last_live_ts_key(TEST_SYMBOL, BASE_TIMEFRAME)
    disconnect_count_key = IngestionCoordinator._disconnect_count_key(TEST_SYMBOL, BASE_TIMEFRAME)

    assert await valkey_client.exists(state_key) == 0
    assert await valkey_client.exists(disconnect_key) == 0
    assert await valkey_client.exists(last_live_key) == 0
    assert await valkey_client.exists(disconnect_count_key) == 0
    assert await valkey_client.exists(STREAM_KEY) == 0
    assert await valkey_client.exists(FEATURE_STREAM_KEY) == 0
    assert await valkey_client.exists(PRICE_UPDATE_STREAM_KEY) == 0


@pytest.mark.asyncio
@pytest.mark.slow
async def test_runtime_asset_pause_and_resume_lifecycle(
    db_pools,
    valkey_client,
    runtime_config,
):
    service = IngestionControlService(
        pool=DBPoolManager.get_writer_pool(),
        valkey_client=valkey_client,
        config_manager=runtime_config,
    )
    coordinator = IngestionCoordinator(valkey_client, runtime_config)
    resume_backfill_key = IngestionCoordinator._resume_backfill_key(TEST_SYMBOL, BASE_TIMEFRAME)

    result = await service.upsert_asset(
        IngestionAssetUpsertRequest(
            symbol=TEST_SYMBOL,
            base_timeframe=BASE_TIMEFRAME,
            publish_timeframes=PUBLISH_TIMEFRAMES,
            historical_backfill_days=1,
            desired_state=IngestionAssetDesiredState.LIVE,
            request_id=f"e2e-runtime-pause-resume-{int(time.time() * 1000)}",
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
                request_id=f"e2e-runtime-pause-{int(time.time() * 1000)}",
                requested_by="tests.e2e",
                reason="pause runtime lifecycle validation",
            ),
        )

        assert pause_result.command_published is True

        pause_marker_exists = await _wait_until(
            lambda: _valkey_key_exists(valkey_client, resume_backfill_key),
            timeout_s=10,
            interval_s=0.5,
            description=f"{resume_backfill_key} to exist after pause command",
        )
        assert pause_marker_exists is True

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
                request_id=f"e2e-runtime-resume-{int(time.time() * 1000)}",
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

        resume_marker_cleared = await _wait_until(
            lambda: _valkey_key_missing(valkey_client, resume_backfill_key),
            timeout_s=120,
            interval_s=1,
            description=f"{resume_backfill_key} to clear after resume gap-fill",
        )
        assert resume_marker_cleared is True

        resumed_snapshot = await _wait_until(
            lambda: _live_state_snapshot(coordinator),
            timeout_s=240,
            interval_s=1,
            description=f"{TEST_SYMBOL} to transition back to LIVE after resume",
        )
        assert resumed_snapshot["disconnects_in_window"] == 0

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
                    request_id=f"e2e-runtime-pause-resume-cleanup-{int(time.time() * 1000)}",
                    requested_by="tests.e2e",
                    reason="pause resume validation cleanup",
                ),
            )
            remove_requested = True

        if remove_requested:
            tombstone_flags = await _wait_until(
                lambda: _asset_flags_match(TEST_SYMBOL, IngestionAssetDesiredState.STOPPED.value, False),
                timeout_s=180,
                interval_s=2,
                description=f"{TEST_SYMBOL} tombstone state after pause/resume cleanup",
            )
            assert tombstone_flags == (IngestionAssetDesiredState.STOPPED.value, False)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_duplicate_ingestion_upsert_request_is_deduplicated(
    db_pools,
    valkey_client,
    runtime_config,
):
    service = IngestionControlService(
        pool=DBPoolManager.get_writer_pool(),
        valkey_client=valkey_client,
        config_manager=runtime_config,
    )
    symbol = "ADAUSDT"
    request_id = f"e2e-ingestion-dedup-{int(time.time() * 1000)}"
    request = IngestionAssetUpsertRequest(
        symbol=symbol,
        base_timeframe=BASE_TIMEFRAME,
        publish_timeframes=["1h"],
        historical_backfill_days=1,
        desired_state=IngestionAssetDesiredState.LIVE,
        request_id=request_id,
        requested_by="tests.e2e",
        reason="duplicate request validation",
    )

    control_before = await valkey_client.xlen(INGESTION_CONTROL_STREAM)
    events_before = await valkey_client.xlen(INGESTION_EVENTS_STREAM)
    lifecycle_before = await valkey_client.xlen(ASSET_LIFECYCLE_STREAM)

    first = await service.upsert_asset(
        request,
        command_type=IngestionCommandType.UPSERT_ASSET,
    )
    second = await service.upsert_asset(
        request,
        command_type=IngestionCommandType.UPSERT_ASSET,
    )

    assert first.command_published is True
    assert first.event_published is True
    assert first.lifecycle_published is True
    assert second.command_published is False
    assert second.event_published is False
    assert second.lifecycle_published is False
    assert second.deduplicated is True
    assert first.command_id == second.command_id
    assert second.asset.asset_version == first.asset.asset_version

    assert await valkey_client.xlen(INGESTION_CONTROL_STREAM) == control_before + 1
    assert await valkey_client.xlen(INGESTION_EVENTS_STREAM) == events_before + 1
    assert await valkey_client.xlen(ASSET_LIFECYCLE_STREAM) == lifecycle_before + 1

    remove_requested = False
    try:
        flags = await _wait_until(
            lambda: _fetch_asset_flags(symbol),
            timeout_s=60,
            interval_s=1,
            description=f"{symbol} registry row after duplicate upsert validation",
        )
        assert flags == (IngestionAssetDesiredState.LIVE.value, True)
    finally:
        if await _ingestion_asset_exists(symbol):
            await service.apply_action(
                first.asset,
                desired_state=IngestionAssetDesiredState.REMOVING,
                enabled=False,
                action=IngestionCommandType.REMOVE_ASSET,
                body=IngestionAssetActionRequest(
                    request_id=f"e2e-runtime-dedup-cleanup-{int(time.time() * 1000)}",
                    requested_by="tests.e2e",
                    reason="duplicate request validation cleanup",
                ),
            )
            remove_requested = True

        if remove_requested:
            tombstone_flags = await _wait_until(
                lambda: _asset_flags_match(symbol, IngestionAssetDesiredState.STOPPED.value, False),
                timeout_s=180,
                interval_s=2,
                description=f"{symbol} tombstone state after duplicate request cleanup",
            )
            assert tombstone_flags == (IngestionAssetDesiredState.STOPPED.value, False)


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


async def _valkey_key_exists(valkey_client, key: str):
    if await valkey_client.exists(key):
        return True
    return None


async def _valkey_key_missing(valkey_client, key: str):
    if await valkey_client.exists(key) == 0:
        return True
    return None


async def _asset_flags_match(symbol: str, desired_state: str, enabled: bool):
    flags = await _fetch_asset_flags(symbol)
    if flags == (desired_state, enabled):
        return flags
    return None


async def _symbol_count_zero(table: str, symbol: str):
    if await _fetch_symbol_count(table, symbol) == 0:
        return True
    return None
