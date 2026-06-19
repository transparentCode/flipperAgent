import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import IngestionAssetDesiredState, IngestionAssetRecord
from apps.ingestion_app.runtime.app import app, lifespan
from apps.ingestion_app.runtime.bootstrap import initialize_asset_runtime
from apps.ingestion_app.runtime.reconciler import IngestionRuntimeReconciler
from apps.ingestion_app.runtime.shared import AssetRuntimeHandle, AssetRuntimeSpec
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
    assert args[:4] == ("BTCUSDT", ["1m"], mock_arq_pool, mock_coordinator)
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
    mock_coordinator.resume_backfill_required = AsyncMock(return_value=False)
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
    mock_coordinator.transition.assert_any_await(
        "BTCUSDT",
        "1m",
        IngestionState.WARMING,
        reason="history_already_fresh",
        provenance="bootstrap",
    )
    mock_verify_ws.assert_awaited_once()
    args = mock_verify_ws.await_args.args
    assert args[:4] == ("BTCUSDT", ["1m"], mock_arq_pool, mock_coordinator)
    assert isinstance(args[4], set)


@pytest.mark.asyncio
async def test_initialize_asset_runtime_forces_gap_fill_on_resume_marker_v2():
    asset = IngestionAssetRecord(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=["1h"],
        source="registry",
    )
    mock_arq_pool = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.resume_backfill_required = AsyncMock(return_value=True)
    mock_coordinator.is_stale = AsyncMock(return_value=False)
    mock_coordinator.transition = AsyncMock()

    with patch(
        "apps.ingestion_app.runtime.bootstrap.verify_and_launch_ws",
        new=AsyncMock(),
    ) as mock_verify_ws:
        await initialize_asset_runtime(asset, mock_arq_pool, mock_coordinator, set())

    mock_arq_pool.enqueue_job.assert_awaited_once_with("run_rest_gap_fill", ["BTCUSDT"], EXCHANGE_BINANCE)
    mock_coordinator.transition.assert_not_awaited()
    mock_verify_ws.assert_awaited_once()
    assert mock_verify_ws.await_args.args[:2] == ("BTCUSDT", ["1m", "1h"])


def test_asset_runtime_spec_should_run_for_resuming_v2():
    spec = AssetRuntimeSpec(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=("1h",),
        enabled=True,
        desired_state=IngestionAssetDesiredState.RESUMING,
    )

    assert spec.should_run() is True
    assert spec.stream_timeframes == ("1m", "1h")


@pytest.mark.asyncio
async def test_reconciler_does_not_restart_when_asset_promotes_from_resuming_to_live_v2():
    reconciler = IngestionRuntimeReconciler(
        config_manager=MagicMock(get=MagicMock(return_value=5)),
        arq_pool=AsyncMock(),
        coordinator=MagicMock(),
        redis_client=AsyncMock(),
    )
    current = AssetRuntimeSpec(
        symbol="BTCUSDT",
        base_timeframe="1m",
        publish_timeframes=("1h",),
        enabled=True,
        desired_state=IngestionAssetDesiredState.RESUMING,
    )
    active_task = asyncio.create_task(asyncio.sleep(60))
    reconciler.asset_handles["BTCUSDT"] = AssetRuntimeHandle(spec=current, tasks={active_task})
    reconciler.stop_asset = AsyncMock()
    reconciler.start_asset = AsyncMock()
    reconciler.asset_catalog = MagicMock()
    reconciler.asset_catalog.list_effective_assets = AsyncMock(
        return_value=[
            IngestionAssetRecord(
                symbol="BTCUSDT",
                base_timeframe="1m",
                publish_timeframes=["1h"],
                enabled=True,
                desired_state=IngestionAssetDesiredState.LIVE,
                source="registry",
            )
        ]
    )

    try:
        await reconciler.reconcile_once()
        reconciler.stop_asset.assert_not_awaited()
        reconciler.start_asset.assert_not_awaited()
    finally:
        active_task.cancel()
        await asyncio.gather(active_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_run_websocket_pipeline_transitions_live_after_first_valid_payload_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
    mock_arq_pool = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[])
    mock_redis_client.pipeline = MagicMock(return_value=mock_pipe)
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()
    seen_symbols_timeframes = {}

    valid_message = {
        "data": {
            "k": {
                "t": 1704067200000,
                "T": 1704067259999,
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
        seen_symbols_timeframes.update(_symbols_timeframes)
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

        await run_websocket_pipeline("BTCUSDT", ["1h"], arq_pool=mock_arq_pool, coordinator=mock_coordinator)

    assert mock_coordinator.transition.await_args_list == [
        call(
            "BTCUSDT",
            "1m",
            IngestionState.LIVE,
            reason="first_live_bar",
            provenance="websocket",
        ),
        call(
            "BTCUSDT",
            "1m",
            IngestionState.COLD,
            reason="websocket_cancelled",
            provenance="websocket",
        ),
    ]
    mock_writer.insert_ohlcv.assert_awaited_once()
    pipe = mock_redis_client.pipeline.return_value
    assert pipe.xadd.call_count == 1
    xadd_args = pipe.xadd.call_args.args
    assert xadd_args[0] == "stream:ohlcv:btcusdt:1m"
    payload = xadd_args[1]
    assert seen_symbols_timeframes == {"BTCUSDT": ["1m", "1h"]}
    assert payload["base_timeframe"] == "1m"
    assert payload["bar_span_seconds"] == "60"
    assert payload["provider"] == "binance_native"
    assert payload["origin"] == "live_websocket"
    assert payload["close_timestamp"] == "1704067259.999"


@pytest.mark.asyncio
async def test_run_websocket_pipeline_uses_asset_specific_base_timeframe_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
    mock_arq_pool = AsyncMock()
    mock_redis_client = AsyncMock()
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[])
    mock_redis_client.pipeline = MagicMock(return_value=mock_pipe)
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()

    valid_message = {
        "data": {
            "k": {
                "t": 1704067200000,
                "T": 1704067499999,
                "o": "100.0",
                "h": "110.0",
                "l": "95.0",
                "c": "105.0",
                "v": "42.0",
                "Q": "21.0",
                "i": "5m",
                "x": True,
            }
        }
    }

    async def fake_stream(_symbols_timeframes, _loop, _queue):
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

        await run_websocket_pipeline(
            "BTCUSDT",
            ["15m"],
            arq_pool=mock_arq_pool,
            coordinator=mock_coordinator,
            base_timeframe="5m",
        )

    assert mock_coordinator.transition.await_args_list == [
        call(
            "BTCUSDT",
            "5m",
            IngestionState.LIVE,
            reason="first_live_bar",
            provenance="websocket",
        ),
        call(
            "BTCUSDT",
            "5m",
            IngestionState.COLD,
            reason="websocket_cancelled",
            provenance="websocket",
        ),
    ]
    payload = mock_redis_client.pipeline.return_value.xadd.call_args.args[1]
    assert payload["base_timeframe"] == "5m"


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
@pytest.mark.skip(reason="Covered by scripts/qa/ingestion_runtime_memory_soak.py")
async def test_run_websocket_pipeline_bounded_memory_across_repeated_cycles_v2():
    cycle_count = 3
    baseline_live_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())

    for cycle_index in range(cycle_count):
        mock_coordinator = MagicMock()
        mock_coordinator.transition = AsyncMock()
        mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
        mock_arq_pool = AsyncMock()
        mock_writer = MagicMock()
        mock_writer.insert_ohlcv = AsyncMock()
        created_redis_clients = []
        attempt = {"count": 0}

        async def make_client(_config_manager, clients=created_redis_clients):
            client = AsyncMock()
            clients.append(client)
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

    final_live_tasks = sum(1 for task in asyncio.all_tasks() if not task.done())
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
async def test_reconciler_wait_for_change_treats_valkey_timeout_as_idle_v2():
    mock_config = MagicMock()
    mock_config.get.side_effect = lambda key, default=None: {
        "ingestion.runtime.reconcile_interval_seconds": 1,
    }.get(key, default)
    redis_client = MagicMock()
    redis_client.xread = AsyncMock(side_effect=ValkeyTimeoutError("Timeout reading from broker:6379"))
    reconciler = IngestionRuntimeReconciler(
        config_manager=mock_config,
        arq_pool=AsyncMock(),
        coordinator=MagicMock(transition=AsyncMock()),
        redis_client=redis_client,
    )

    with patch("apps.ingestion_app.runtime.reconciler.asyncio.sleep", new=AsyncMock()) as mock_sleep:
        await reconciler.wait_for_change()

    mock_sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_snapshot_includes_state_timing_metadata_v2():
    symbol = "BTCUSDT"
    timeframe = "1m"
    now_ms = 1_781_410_000_000
    state_updated_ts = now_ms - 2_000
    last_ready_ts = now_ms - 4_000
    last_live_ts = now_ms - 9_000
    last_disconnect_ts = now_ms - 5_000
    values = {
        IngestionCoordinator._state_key(symbol, timeframe): IngestionState.WARMING.value,
        IngestionCoordinator._state_updated_ts_key(symbol, timeframe): str(state_updated_ts),
        IngestionCoordinator._last_ready_ts_key(symbol, timeframe): str(last_ready_ts),
        IngestionCoordinator._last_live_ts_key(symbol, timeframe): str(last_live_ts),
        IngestionCoordinator._disconnect_ts_key(symbol, timeframe): str(last_disconnect_ts),
        IngestionCoordinator._disconnect_count_key(symbol, timeframe): "3",
    }
    valkey_client = MagicMock()
    valkey_client.get = AsyncMock(side_effect=lambda key: values.get(key))
    valkey_client.hgetall = AsyncMock(return_value={})
    coordinator = IngestionCoordinator(valkey_client)

    with patch("apps.ingestion_app.coordination.datetime") as mock_datetime:
        mock_now = MagicMock()
        mock_now.timestamp.return_value = now_ms / 1000
        mock_datetime.now.return_value = mock_now
        snapshot = await coordinator.get_observability_snapshot(symbol, timeframe)

    assert snapshot["state"] == IngestionState.WARMING.value
    assert snapshot["state_updated_ts"] == state_updated_ts
    assert snapshot["state_age_ms"] == 2_000
    assert snapshot["downstream_ready"] is True
    assert snapshot["resume_backfill_required"] is False
    assert snapshot["last_ready_ts"] == last_ready_ts
    assert snapshot["last_ready_age_ms"] == 4_000
    assert snapshot["last_live_ts"] == last_live_ts
    assert snapshot["last_live_age_ms"] == 9_000
    assert snapshot["last_disconnect_ts"] == last_disconnect_ts
    assert snapshot["disconnects_in_window"] == 3


@pytest.mark.asyncio
async def test_coordinator_transition_publishes_runtime_status_v2():
    symbol = "BTCUSDT"
    timeframe = "1m"
    storage: dict[str, str] = {}
    status_hashes: dict[str, dict[str, str]] = {}
    stream_calls: list[tuple[str, dict[str, str]]] = []

    async def fake_get(key: str):
        return storage.get(key)

    async def fake_set(key: str, value: str):
        storage[key] = value
        return True

    async def fake_hset(key: str, mapping: dict[str, str]):
        status_hashes[key] = dict(mapping)
        return len(mapping)

    async def fake_xadd(stream: str, payload: dict[str, str], **kwargs):
        stream_calls.append((stream, payload))
        return "1-0"

    valkey_client = MagicMock()
    valkey_client.get = AsyncMock(side_effect=fake_get)
    valkey_client.set = AsyncMock(side_effect=fake_set)
    valkey_client.hset = AsyncMock(side_effect=fake_hset)
    valkey_client.xadd = AsyncMock(side_effect=fake_xadd)
    coordinator = IngestionCoordinator(valkey_client)

    await coordinator.transition(
        symbol,
        timeframe,
        IngestionState.WARMING,
        reason="history_already_fresh",
        provenance="bootstrap",
    )

    assert any(stream == "asset:status" for stream, _ in stream_calls)
    status_payload = next(payload for stream, payload in stream_calls if stream == "asset:status")
    assert status_payload["symbol"] == symbol
    assert status_payload["timeframe"] == timeframe
    assert status_payload["runtime_state"] == IngestionState.WARMING.value
    assert status_payload["downstream_ready"] == "True"
    assert status_payload["provenance"] == "bootstrap"


@pytest.mark.asyncio
async def test_coordinator_transition_counts_only_real_disconnects_v2():
    symbol = "BTCUSDT"
    timeframe = "1m"
    storage: dict[str, str] = {}
    disconnect_counter = {"count": 0}

    async def fake_get(key: str):
        if key == IngestionCoordinator._disconnect_count_key(symbol, timeframe):
            return str(disconnect_counter["count"]) if disconnect_counter["count"] else None
        return storage.get(key)

    async def fake_set(key: str, value: str):
        storage[key] = value
        return True

    async def fake_incr(_key: str):
        disconnect_counter["count"] += 1
        return disconnect_counter["count"]

    valkey_client = MagicMock()
    valkey_client.get = AsyncMock(side_effect=fake_get)
    valkey_client.set = AsyncMock(side_effect=fake_set)
    valkey_client.hset = AsyncMock(return_value=1)
    valkey_client.xadd = AsyncMock(return_value="1-0")
    valkey_client.incr = AsyncMock(side_effect=fake_incr)
    valkey_client.expire = AsyncMock(return_value=True)
    coordinator = IngestionCoordinator(valkey_client)

    await coordinator.transition(
        symbol,
        timeframe,
        IngestionState.COLD,
        reason="runtime_stopped",
        provenance="reconciler",
    )
    await coordinator.transition(
        symbol,
        timeframe,
        IngestionState.COLD,
        reason="websocket_disconnected",
        provenance="websocket",
    )

    assert disconnect_counter["count"] == 1
    valkey_client.expire.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_run_websocket_pipeline_skips_duplicate_closed_candle_publication_v2():
    mock_coordinator = MagicMock()
    mock_coordinator.transition = AsyncMock()
    mock_coordinator.get_disconnect_count = AsyncMock(return_value=1)
    mock_arq_pool = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.insert_ohlcv = AsyncMock()
    dedupe_storage: dict[str, str] = {}
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[])

    valid_message = {
        "data": {
            "k": {
                "t": 1704067200000,
                "T": 1704067259999,
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
        yield valid_message
        yield valid_message
        raise asyncio.CancelledError()

    async def fake_get(key: str):
        return dedupe_storage.get(key)

    async def fake_set(key: str, value: str):
        dedupe_storage[key] = value
        return True

    mock_redis_client = MagicMock()
    mock_redis_client.get = AsyncMock(side_effect=fake_get)
    mock_redis_client.set = AsyncMock(side_effect=fake_set)
    mock_redis_client.aclose = AsyncMock()
    mock_redis_client.pipeline = MagicMock(return_value=mock_pipe)
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

    assert mock_writer.insert_ohlcv.await_count == 2
    assert mock_pipe.xadd.call_count == 1
