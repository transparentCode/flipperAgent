import asyncio
import gc
import tracemalloc
from unittest.mock import AsyncMock, MagicMock, patch

import psutil
import pytest

from apps.ingestion_app.coordination import IngestionState
from apps.ingestion_app.models.asset_registry import IngestionAssetRecord
from apps.ingestion_app.runtime.app import app, lifespan
from apps.ingestion_app.runtime.reconciler import IngestionRuntimeReconciler
from apps.ingestion_app.runtime.websocket import run_websocket_pipeline
from apps.ingestion_app.constants import EXCHANGE_BINANCE


@pytest.mark.asyncio
async def test_lifespan_cold_start_v2():
    mock_arq_pool = AsyncMock()
    mock_valkey_client = AsyncMock()
    mock_coordinator = AsyncMock()
    mock_coordinator.is_stale = AsyncMock(return_value=True)
    mock_coordinator.transition = AsyncMock()

    async def idle_xread(*args, **kwargs):
        await asyncio.sleep(0)
        return []

    with (
        patch("apps.ingestion_app.runtime.app.DBPoolManager") as mock_db_pool,
        patch("apps.ingestion_app.runtime.app.initialize_storage", new=AsyncMock()) as mock_initialize_storage,
        patch("apps.ingestion_app.runtime.app.build_redis_settings", return_value=object()) as mock_build_redis_settings,
        patch("apps.ingestion_app.runtime.app.create_pool", new=AsyncMock(return_value=mock_arq_pool)),
        patch(
            "apps.ingestion_app.runtime.app.create_runtime_coordinator",
            new=AsyncMock(return_value=(mock_valkey_client, mock_coordinator)),
        ) as mock_create_runtime_coordinator,
        patch(
            "apps.ingestion_app.runtime.reconciler.IngestionAssetCatalog.list_effective_assets",
            new=AsyncMock(return_value=[IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=[])]),
        ),
        patch("apps.ingestion_app.runtime.bootstrap.verify_and_launch_ws", new=AsyncMock()) as mock_verify_ws,
        patch("apps.ingestion_app.runtime.app.config_manager") as mock_config,
    ):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "valkey.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000,
        }.get(key, default)

        mock_valkey_client.xread = AsyncMock(side_effect=idle_xread)
        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()

        async with lifespan(app):
            await asyncio.sleep(0)

    mock_initialize_storage.assert_awaited_once_with(mock_config)
    mock_build_redis_settings.assert_called_once_with(mock_config)
    mock_create_runtime_coordinator.assert_awaited_once_with(mock_config)
    mock_arq_pool.enqueue_job.assert_called_once_with("run_rest_gap_fill", ["BTCUSDT"], EXCHANGE_BINANCE)
    mock_verify_ws.assert_awaited_once()
    args = mock_verify_ws.await_args.args
    assert args[:4] == ("BTCUSDT", [], mock_arq_pool, mock_coordinator)
    assert isinstance(args[4], set)


@pytest.mark.asyncio
async def test_lifespan_closes_pools_when_storage_init_fails_v2():
    with (
        patch("apps.ingestion_app.runtime.app.DBPoolManager") as mock_db_pool,
        patch(
            "apps.ingestion_app.runtime.app.initialize_storage",
            new=AsyncMock(side_effect=RuntimeError("storage boom")),
        ),
        patch("apps.ingestion_app.runtime.app.create_pool", new=AsyncMock()) as mock_create_pool,
        patch("apps.ingestion_app.runtime.app.config_manager"),
    ):
        mock_db_pool.close_pools = AsyncMock()

        with pytest.raises(RuntimeError, match="storage boom"):
            async with lifespan(app):
                await asyncio.sleep(0)

    mock_db_pool.close_pools.assert_awaited_once()
    mock_create_pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifespan_caught_up_v2():
    mock_arq_pool = AsyncMock()
    mock_valkey_client = AsyncMock()
    mock_coordinator = AsyncMock()
    mock_coordinator.is_stale = AsyncMock(return_value=False)
    mock_coordinator.transition = AsyncMock()

    async def idle_xread(*args, **kwargs):
        await asyncio.sleep(0)
        return []

    with (
        patch("apps.ingestion_app.runtime.app.DBPoolManager") as mock_db_pool,
        patch("apps.ingestion_app.runtime.app.initialize_storage", new=AsyncMock()) as mock_initialize_storage,
        patch("apps.ingestion_app.runtime.app.build_redis_settings", return_value=object()) as mock_build_redis_settings,
        patch("apps.ingestion_app.runtime.app.create_pool", new=AsyncMock(return_value=mock_arq_pool)),
        patch(
            "apps.ingestion_app.runtime.app.create_runtime_coordinator",
            new=AsyncMock(return_value=(mock_valkey_client, mock_coordinator)),
        ) as mock_create_runtime_coordinator,
        patch(
            "apps.ingestion_app.runtime.reconciler.IngestionAssetCatalog.list_effective_assets",
            new=AsyncMock(return_value=[IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=[])]),
        ),
        patch("apps.ingestion_app.runtime.bootstrap.verify_and_launch_ws", new=AsyncMock()) as mock_verify_ws,
        patch("apps.ingestion_app.runtime.app.config_manager") as mock_config,
    ):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "valkey.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000,
        }.get(key, default)

        mock_valkey_client.xread = AsyncMock(side_effect=idle_xread)
        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()

        async with lifespan(app):
            await asyncio.sleep(0)

    mock_initialize_storage.assert_awaited_once_with(mock_config)
    mock_build_redis_settings.assert_called_once_with(mock_config)
    mock_create_runtime_coordinator.assert_awaited_once_with(mock_config)
    mock_arq_pool.enqueue_job.assert_not_called()
    mock_coordinator.transition.assert_any_call("BTCUSDT", "1m", IngestionState.WARMING)
    mock_verify_ws.assert_awaited_once()
    args = mock_verify_ws.await_args.args
    assert args[:4] == ("BTCUSDT", [], mock_arq_pool, mock_coordinator)
    assert isinstance(args[4], set)


@pytest.mark.asyncio
async def test_run_websocket_pipeline_transitions_live_after_first_valid_payload_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_arq_pool = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()

    valid_message = {
        "data": {
            "k": {
                "t": 1704067200000,
                "o": "100.0",
                "h": "110.0",
                "l": "95.0",
                "c": "105.0",
                "v": "42.0",
                "Q": "21.0",
                "i": "1m",
                "x": True,
            }
        }
    }

    async def fake_stream(_symbols_timeframes, _loop, _queue):
        mock_coordinator.transition.assert_not_awaited()
        yield {"event": "ping"}
        mock_coordinator.transition.assert_not_awaited()
        yield valid_message
        raise asyncio.CancelledError()

    mock_adapter = MagicMock()
    mock_adapter.stream_multiplex_socket = fake_stream

    with (
        patch(
            "apps.ingestion_app.runtime.websocket.create_valkey_client",
            new=AsyncMock(return_value=mock_redis_client),
        ),
        patch("apps.ingestion_app.runtime.websocket.DBPoolManager") as mock_db_pool,
        patch("apps.ingestion_app.runtime.websocket.TimescaleWriter", return_value=mock_writer),
        patch("apps.ingestion_app.runtime.websocket.BinanceNativeAdapter", return_value=mock_adapter),
        patch("apps.ingestion_app.runtime.websocket.config_manager") as mock_config,
    ):
        mock_db_pool.get_writer_pool.return_value = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.websocket.reconnect_sleep_seconds": 5,
            "ingestion.websocket.queue_maxsize": 10,
        }.get(key, default)

        await run_websocket_pipeline("BTCUSDT", [], arq_pool=mock_arq_pool, coordinator=mock_coordinator)

    assert mock_coordinator.transition.await_args_list == [
        (("BTCUSDT", "1m", IngestionState.LIVE),),
        (("BTCUSDT", "1m", IngestionState.COLD),),
    ]
    mock_writer.insert_ohlcv.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_websocket_pipeline_closes_valkey_clients_across_reconnect_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
    mock_arq_pool = AsyncMock()
    first_redis_client = AsyncMock()
    second_redis_client = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()
    attempt = {"count": 0}

    async def flappy_stream(_symbols_timeframes, _loop, _queue):
        attempt["count"] += 1
        if False:
            yield {}
        if attempt["count"] == 1:
            raise RuntimeError("socket dropped")
        raise asyncio.CancelledError()

    mock_adapter = MagicMock()
    mock_adapter.stream_multiplex_socket = flappy_stream

    with (
        patch(
            "apps.ingestion_app.runtime.websocket.create_valkey_client",
            new=AsyncMock(side_effect=[first_redis_client, second_redis_client]),
        ),
        patch("apps.ingestion_app.runtime.websocket.DBPoolManager") as mock_db_pool,
        patch("apps.ingestion_app.runtime.websocket.TimescaleWriter", return_value=mock_writer),
        patch("apps.ingestion_app.runtime.websocket.BinanceNativeAdapter", return_value=mock_adapter),
        patch("apps.ingestion_app.runtime.websocket.asyncio.sleep", new=AsyncMock()),
        patch("apps.ingestion_app.runtime.websocket.config_manager") as mock_config,
    ):
        mock_db_pool.get_writer_pool.return_value = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.websocket.reconnect_sleep_seconds": 0,
            "ingestion.websocket.queue_maxsize": 10,
            "ingestion.observability.circuit_breaker_threshold": 5,
            "ingestion.observability.circuit_breaker_sleep_seconds": 300,
        }.get(key, default)

        await run_websocket_pipeline("BTCUSDT", [], arq_pool=mock_arq_pool, coordinator=mock_coordinator)

    assert attempt["count"] == 2
    first_redis_client.aclose.assert_awaited_once()
    second_redis_client.aclose.assert_awaited_once()
    mock_arq_pool.enqueue_job.assert_awaited_once_with("run_rest_gap_fill", ["BTCUSDT"], EXCHANGE_BINANCE)


@pytest.mark.asyncio
@pytest.mark.slow
async def test_run_websocket_pipeline_bounded_memory_across_repeated_cycles_v2():
    process = psutil.Process()
    cycle_count = 8
    rss_threshold_bytes = 32 * 1024 * 1024
    traced_threshold_bytes = 4 * 1024 * 1024
    baseline_live_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())
    rss_samples: list[int] = []

    gc.collect()
    tracemalloc.start()
    baseline_traced_bytes, _ = tracemalloc.get_traced_memory()
    baseline_rss_bytes = process.memory_info().rss

    for cycle_index in range(cycle_count):
        mock_coordinator = MagicMock()
        mock_coordinator.transition = AsyncMock()
        mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
        mock_arq_pool = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.insert_ohlcv = AsyncMock()
        created_redis_clients: list[AsyncMock] = []
        attempt = {"count": 0}

        async def make_client(_config_manager):
            client = AsyncMock()
            created_redis_clients.append(client)
            return client

        valid_message = {
            "data": {
                "k": {
                    "t": 1704067200000 + cycle_index,
                    "o": "100.0",
                    "h": "110.0",
                    "l": "95.0",
                    "c": "105.0",
                    "v": "42.0",
                    "Q": "21.0",
                    "i": "1m",
                    "x": True,
                }
            }
        }

        async def cycle_stream(_symbols_timeframes, _loop, _queue):
            attempt["count"] += 1
            if attempt["count"] == 1:
                raise RuntimeError("socket dropped")
            yield valid_message
            raise asyncio.CancelledError()

        mock_adapter = MagicMock()
        mock_adapter.stream_multiplex_socket = cycle_stream

        with (
            patch(
                "apps.ingestion_app.runtime.websocket.create_valkey_client",
                new=AsyncMock(side_effect=make_client),
            ),
            patch("apps.ingestion_app.runtime.websocket.DBPoolManager") as mock_db_pool,
            patch("apps.ingestion_app.runtime.websocket.TimescaleWriter", return_value=mock_writer),
            patch("apps.ingestion_app.runtime.websocket.BinanceNativeAdapter", return_value=mock_adapter),
            patch("apps.ingestion_app.runtime.websocket.asyncio.sleep", new=AsyncMock()),
            patch("apps.ingestion_app.runtime.websocket.config_manager") as mock_config,
        ):
            mock_db_pool.get_writer_pool.return_value = MagicMock()
            mock_config.get.side_effect = lambda key, default=None: {
                "ingestion.timeframes.base_gap_fill": "1m",
                "ingestion.websocket.reconnect_sleep_seconds": 0,
                "ingestion.websocket.queue_maxsize": 10,
                "ingestion.observability.circuit_breaker_threshold": 5,
                "ingestion.observability.circuit_breaker_sleep_seconds": 300,
            }.get(key, default)

            await run_websocket_pipeline("BTCUSDT", [], arq_pool=mock_arq_pool, coordinator=mock_coordinator)

        assert attempt["count"] == 2
        assert len(created_redis_clients) == 2
        for client in created_redis_clients:
            client.aclose.assert_awaited_once()

        del mock_adapter
        del mock_writer
        del mock_arq_pool
        del mock_coordinator
        del created_redis_clients

        await asyncio.sleep(0)
        gc.collect()
        rss_samples.append(process.memory_info().rss)

    final_traced_bytes, peak_traced_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    gc.collect()
    final_rss_bytes = process.memory_info().rss
    final_live_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())

    traced_growth_bytes = final_traced_bytes - baseline_traced_bytes
    rss_growth_bytes = final_rss_bytes - baseline_rss_bytes

    assert traced_growth_bytes < traced_threshold_bytes, (
        "Traced Python allocations grew too much across repeated WS cycles: "
        f"{traced_growth_bytes} bytes (baseline={baseline_traced_bytes}, "
        f"final={final_traced_bytes}, peak={peak_traced_bytes})"
    )
    assert rss_growth_bytes < rss_threshold_bytes, (
        "RSS grew too much across repeated WS cycles: "
        f"{rss_growth_bytes} bytes (baseline={baseline_rss_bytes}, final={final_rss_bytes}, "
        f"samples={rss_samples})"
    )
    assert final_live_tasks <= baseline_live_tasks + 1, (
        f"Live asyncio task count drifted: baseline={baseline_live_tasks}, final={final_live_tasks}"
    )


@pytest.mark.asyncio
async def test_reconciler_starts_new_runtime_for_live_asset_v2():
    asset = IngestionAssetRecord(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        source="registry",
    )
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key, default=None: {
        "ingestion.runtime.reconcile_interval_seconds": 1,
    }.get(key, default)

    reconciler = IngestionRuntimeReconciler(
        config_manager=mock_config,
        arq_pool=AsyncMock(),
        coordinator=MagicMock(transition=AsyncMock()),
        redis_client=MagicMock(),
        asset_catalog=MagicMock(list_effective_assets=AsyncMock(return_value=[asset])),
    )

    with patch(
        "apps.ingestion_app.runtime.reconciler.initialize_asset_runtime",
        new=AsyncMock(),
    ) as mock_initialize:
        await reconciler.reconcile_once()
        await asyncio.sleep(0)

    assert "BTCUSDT" in reconciler.asset_handles
    mock_initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciler_stops_runtime_when_asset_paused_v2():
    asset = IngestionAssetRecord(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        source="registry",
    )
    paused_asset = asset.model_copy(update={"desired_state": "PAUSED"})
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key, default=None: {
        "ingestion.runtime.reconcile_interval_seconds": 1,
    }.get(key, default)
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()

    reconciler = IngestionRuntimeReconciler(
        config_manager=mock_config,
        arq_pool=AsyncMock(),
        coordinator=mock_coordinator,
        redis_client=MagicMock(),
        asset_catalog=MagicMock(list_effective_assets=AsyncMock(side_effect=[[asset], [paused_asset]])),
    )

    with patch(
        "apps.ingestion_app.runtime.reconciler.initialize_asset_runtime",
        new=AsyncMock(),
    ):
        await reconciler.reconcile_once()
        await reconciler.reconcile_once()

    assert "BTCUSDT" not in reconciler.asset_handles
    mock_coordinator.transition.assert_awaited()


@pytest.mark.asyncio
async def test_reconciler_dispatches_removal_once_v2():
    removing_asset = IngestionAssetRecord(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        desired_state="REMOVING",
        enabled=False,
        source="registry",
    )
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key, default=None: {
        "ingestion.runtime.reconcile_interval_seconds": 1,
    }.get(key, default)
    mock_arq_pool = AsyncMock()

    reconciler = IngestionRuntimeReconciler(
        config_manager=mock_config,
        arq_pool=mock_arq_pool,
        coordinator=MagicMock(transition=AsyncMock()),
        redis_client=MagicMock(),
        asset_catalog=MagicMock(list_effective_assets=AsyncMock(side_effect=[[removing_asset], [removing_asset]])),
    )

    await reconciler.reconcile_once()
    await reconciler.reconcile_once()

    mock_arq_pool.enqueue_job.assert_awaited_once_with("purge_removed_asset", "BTCUSDT", "1m")


@pytest.mark.asyncio
async def test_run_websocket_pipeline_emits_retry_exhausted_event_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_coordinator.get_disconnect_count = AsyncMock(return_value=5)
    mock_arq_pool = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()

    async def broken_stream(_symbols_timeframes, _loop, _queue):
        if False:
            yield {}
        raise RuntimeError("socket dropped")

    mock_adapter = MagicMock()
    mock_adapter.stream_multiplex_socket = broken_stream

    with (
        patch(
            "apps.ingestion_app.runtime.websocket.create_valkey_client",
            new=AsyncMock(return_value=mock_redis_client),
        ),
        patch("apps.ingestion_app.runtime.websocket.DBPoolManager") as mock_db_pool,
        patch("apps.ingestion_app.runtime.websocket.TimescaleWriter", return_value=mock_writer),
        patch("apps.ingestion_app.runtime.websocket.BinanceNativeAdapter", return_value=mock_adapter),
        patch(
            "apps.ingestion_app.runtime.websocket.publish_ingestion_runtime_event",
            new=AsyncMock(),
        ) as mock_event,
        patch(
            "apps.ingestion_app.runtime.websocket.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
        patch("apps.ingestion_app.runtime.websocket.config_manager") as mock_config,
    ):
        mock_db_pool.get_writer_pool.return_value = MagicMock()
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.websocket.reconnect_sleep_seconds": 5,
            "ingestion.websocket.queue_maxsize": 10,
            "ingestion.observability.circuit_breaker_threshold": 5,
            "ingestion.observability.circuit_breaker_sleep_seconds": 300,
        }.get(key, default)

        with pytest.raises(asyncio.CancelledError):
            await run_websocket_pipeline("BTCUSDT", [], arq_pool=mock_arq_pool, coordinator=mock_coordinator)

    mock_event.assert_awaited_once()
