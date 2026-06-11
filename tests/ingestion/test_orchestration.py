import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import pandas as pd
import asyncio

from apps.ingestion_app.coordination import IngestionState
from apps.ingestion_app.models.asset_registry import IngestionAssetRecord
from libs.common.exceptions import DataIngestionError
from apps.ingestion_app.orchestration.tasks import _fetch_asset_gap
from apps.ingestion_app.orchestration.controller import (
    IngestionRuntimeReconciler,
    app,
    lifespan,
    run_websocket_pipeline,
)
from apps.ingestion_app.constants import EXCHANGE_BINANCE

@pytest.mark.asyncio
async def test_fetch_asset_gap_pagination():
    ccxt_adapter = AsyncMock()
    
    # Return 1000 rows so it doesn't break early
    df1 = pd.DataFrame([
        {"timestamp": 1000 + i, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}
        for i in range(1000)
    ])
    df2 = pd.DataFrame([
        {"timestamp": 2000 + i, "open": 2, "high": 3, "low": 2, "close": 3, "volume": 10}
        for i in range(1000)
    ])
    df3 = pd.DataFrame()
    
    ccxt_adapter.get_historical_ohlcv.side_effect = [df1, df2, df3]
    
    ctx = {}
    symbol = "BTCUSDT"
    
    with patch('apps.ingestion_app.orchestration.tasks.TimescaleReader') as mock_reader_class, \
         patch('apps.ingestion_app.orchestration.tasks.DBPoolManager', new_callable=MagicMock), \
         patch('apps.ingestion_app.orchestration.tasks.TimescaleWriter') as mock_writer_class, \
         patch('apps.ingestion_app.orchestration.tasks.datetime') as mock_datetime, \
         patch('apps.ingestion_app.orchestration.tasks.config_manager') as mock_config:
        
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.assets.historical_backfill_days": 30,
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.concurrency.gap_fill_sleep_seconds": 0.0
        }.get(k, default)

        # Setup mock reader and max_timestamp = 0
        mock_reader = mock_reader_class.return_value
        mock_reader.get_max_timestamp = AsyncMock(return_value=0)
        
        # Setup mock writer
        mock_writer = mock_writer_class.return_value
        mock_writer.insert_ohlcv = AsyncMock()
        
        # Setup mock datetime so since_ms calculation is predictable
        mock_now = datetime(2023, 1, 31, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        
        # Run
        await _fetch_asset_gap(ctx, ccxt_adapter, symbol)
        
        # Assert get_max_timestamp called
        mock_reader.get_max_timestamp.assert_called_once_with(symbol, "1m")
        
        # Assert ccxt adapter called multiple times logically
        assert ccxt_adapter.get_historical_ohlcv.call_count == 3
        
        # First call has since=since_ms. 
        # now_ms = 1675123200000. 30 days = 30 * 86400 * 1000 = 2592000000. 
        # since_ms = 1675123200000 - 2592000000 = 1672531200000.
        first_call = ccxt_adapter.get_historical_ohlcv.call_args_list[0]
        assert first_call[0][:2] == (symbol, "1m")
        assert first_call[1]['since'] == 1672531200000
        
        # Second call has since=2000
        second_call = ccxt_adapter.get_historical_ohlcv.call_args_list[1]
        assert second_call[1]['since'] == 2000

@pytest.mark.asyncio
async def test_lifespan_cold_start():
    # Mocking create_pool
    mock_arq_pool = AsyncMock()
    mock_valkey_client = AsyncMock()
    mock_coordinator = AsyncMock()
    mock_coordinator.is_stale = AsyncMock(return_value=True)
    mock_coordinator.transition = AsyncMock()

    async def idle_xread(*args, **kwargs):
        await asyncio.sleep(0)
        return []

    with patch('apps.ingestion_app.orchestration.controller.DBPoolManager') as mock_db_pool, \
         patch('apps.ingestion_app.orchestration.controller.apply_ingestion_schema', new=AsyncMock()) as mock_apply_schema, \
         patch('apps.ingestion_app.orchestration.controller.create_pool') as mock_create_pool, \
         patch('apps.ingestion_app.orchestration.controller.create_valkey_client') as mock_create_valkey, \
         patch('apps.ingestion_app.orchestration.controller.IngestionCoordinator') as mock_coordinator_class, \
         patch('apps.ingestion_app.orchestration.controller.IngestionAssetCatalog.list_effective_assets', new=AsyncMock(return_value=[
             IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=[]),
         ])) as _mock_assets, \
         patch('apps.ingestion_app.orchestration.controller.verify_and_launch_ws') as mock_verify_ws, \
         patch('apps.ingestion_app.orchestration.controller.config_manager') as mock_config:

        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "valkey.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000
        }.get(k, default)

        mock_create_pool.return_value = mock_arq_pool
        mock_create_valkey.return_value = mock_valkey_client
        mock_valkey_client.xread = AsyncMock(side_effect=idle_xread)
        mock_coordinator_class.return_value = mock_coordinator

        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()

        # Make verify_and_launch_ws return immediately
        mock_verify_ws.return_value = None

        async with lifespan(app):
            # In the lifespan block
            await asyncio.sleep(0)

        mock_apply_schema.assert_awaited_once_with(mock_db_pool.get_writer_pool.return_value)
        mock_arq_pool.enqueue_job.assert_called_once_with("run_rest_gap_fill", ["BTCUSDT"], EXCHANGE_BINANCE)
        mock_verify_ws.assert_called_once()
        args = mock_verify_ws.call_args.args
        assert args[:4] == ("BTCUSDT", [], mock_arq_pool, mock_coordinator)
        assert isinstance(args[4], set)

@pytest.mark.asyncio
async def test_lifespan_caught_up():
    mock_arq_pool = AsyncMock()
    mock_valkey_client = AsyncMock()
    mock_coordinator = AsyncMock()
    mock_coordinator.is_stale = AsyncMock(return_value=False)
    mock_coordinator.transition = AsyncMock()

    async def idle_xread(*args, **kwargs):
        await asyncio.sleep(0)
        return []

    with patch('apps.ingestion_app.orchestration.controller.DBPoolManager') as mock_db_pool, \
         patch('apps.ingestion_app.orchestration.controller.apply_ingestion_schema', new=AsyncMock()) as mock_apply_schema, \
         patch('apps.ingestion_app.orchestration.controller.create_pool') as mock_create_pool, \
         patch('apps.ingestion_app.orchestration.controller.create_valkey_client') as mock_create_valkey, \
         patch('apps.ingestion_app.orchestration.controller.IngestionCoordinator') as mock_coordinator_class, \
         patch('apps.ingestion_app.orchestration.controller.IngestionAssetCatalog.list_effective_assets', new=AsyncMock(return_value=[
             IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=[]),
         ])) as _mock_assets, \
         patch('apps.ingestion_app.orchestration.controller.verify_and_launch_ws') as mock_verify_ws, \
         patch('apps.ingestion_app.orchestration.controller.config_manager') as mock_config:

        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "valkey.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000
        }.get(k, default)

        mock_create_pool.return_value = mock_arq_pool
        mock_create_valkey.return_value = mock_valkey_client
        mock_valkey_client.xread = AsyncMock(side_effect=idle_xread)
        mock_coordinator_class.return_value = mock_coordinator

        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()

        mock_verify_ws.return_value = None

        async with lifespan(app):
            await asyncio.sleep(0)

        mock_apply_schema.assert_awaited_once_with(mock_db_pool.get_writer_pool.return_value)
        # Gap-fill shouldn't be called
        mock_arq_pool.enqueue_job.assert_not_called()
        # Coordinator should be set to WARMING since data is caught up
        mock_coordinator.transition.assert_any_call("BTCUSDT", "1m", IngestionState.WARMING)
        mock_verify_ws.assert_called_once()
        args = mock_verify_ws.call_args.args
        assert args[:4] == ("BTCUSDT", [], mock_arq_pool, mock_coordinator)
        assert isinstance(args[4], set)


@pytest.mark.asyncio
async def test_run_rest_gap_fill_logs_partial_failures():
    ctx = {
        "ccxt_adapter": AsyncMock(),
        "coordinator": MagicMock(transition=AsyncMock()),
    }

    with patch("apps.ingestion_app.orchestration.tasks._fetch_asset_gap", new=AsyncMock(side_effect=[None, RuntimeError("boom")])), \
         patch("apps.ingestion_app.orchestration.tasks.config_manager") as mock_config, \
         patch("apps.ingestion_app.orchestration.tasks.logger") as mock_logger:
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.concurrency.gap_fill_limit": 5,
            "ingestion.concurrency.gap_fill_sleep_seconds": 0.0,
        }.get(k, default)

        from apps.ingestion_app.orchestration.tasks import run_rest_gap_fill

        with pytest.raises(DataIngestionError) as exc_info:
            await run_rest_gap_fill(ctx, ["BTCUSDT", "ETHUSDT"], EXCHANGE_BINANCE)

    mock_logger.warning.assert_called_once_with(
        "Gap fill completed with failures for %s. succeeded=%s failed=%s failed_assets=%s",
        EXCHANGE_BINANCE,
        1,
        1,
        ["ETHUSDT"],
    )
    mock_logger.error.assert_any_call("Failed to gap-fill ETHUSDT: boom")
    assert exc_info.value.context["failed_assets"] == ["ETHUSDT"]
    assert exc_info.value.context["successful_assets"] == ["BTCUSDT"]


@pytest.mark.asyncio
async def test_run_websocket_pipeline_transitions_live_after_first_valid_payload():
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

    with patch("apps.ingestion_app.orchestration.controller.create_valkey_client", new=AsyncMock(return_value=mock_redis_client)), \
         patch("apps.ingestion_app.orchestration.controller.DBPoolManager") as mock_db_pool, \
         patch("apps.ingestion_app.orchestration.controller.TimescaleWriter", return_value=mock_writer), \
         patch("apps.ingestion_app.orchestration.controller.BinanceNativeAdapter", return_value=mock_adapter), \
         patch("apps.ingestion_app.orchestration.controller.config_manager") as mock_config:
        mock_db_pool.get_writer_pool.return_value = MagicMock()
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.websocket.reconnect_sleep_seconds": 5,
            "ingestion.websocket.queue_maxsize": 10,
        }.get(k, default)

        await run_websocket_pipeline(
            "BTCUSDT",
            [],
            arq_pool=mock_arq_pool,
            coordinator=mock_coordinator,
        )

    assert mock_coordinator.transition.await_args_list == [
        (( "BTCUSDT", "1m", IngestionState.LIVE),),
        (( "BTCUSDT", "1m", IngestionState.COLD),),
    ]
    mock_writer.insert_ohlcv.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciler_starts_new_runtime_for_live_asset():
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
        'apps.ingestion_app.orchestration.controller._initialize_asset_runtime',
        new=AsyncMock(),
    ) as mock_initialize:
        await reconciler.reconcile_once()
        await asyncio.sleep(0)

    assert "BTCUSDT" in reconciler.asset_handles
    mock_initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconciler_stops_runtime_when_asset_paused():
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
        'apps.ingestion_app.orchestration.controller._initialize_asset_runtime',
        new=AsyncMock(),
    ):
        await reconciler.reconcile_once()
        await reconciler.reconcile_once()

    assert "BTCUSDT" not in reconciler.asset_handles
    mock_coordinator.transition.assert_awaited()
