import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone
import pandas as pd
import asyncio

from apps.ingestion_app.orchestration.tasks import _fetch_asset_gap
from apps.ingestion_app.orchestration.controller import lifespan, app
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
         patch('apps.ingestion_app.orchestration.tasks.DBPoolManager', new_callable=MagicMock) as mock_db_pool, \
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
    
    with patch('apps.ingestion_app.orchestration.controller.DBPoolManager') as mock_db_pool, \
         patch('apps.ingestion_app.orchestration.controller.TimescaleReader') as mock_reader_class, \
         patch('apps.ingestion_app.orchestration.controller.create_pool') as mock_create_pool, \
         patch('apps.ingestion_app.orchestration.controller.verify_and_launch_ws') as mock_verify_ws, \
         patch('apps.ingestion_app.orchestration.controller.config_manager') as mock_config:
        
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "redis.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000
        }.get(k, default)
        
        mock_create_pool.return_value = mock_arq_pool
        
        # max_ts = 0
        mock_reader = mock_reader_class.return_value
        mock_reader.get_max_timestamp = AsyncMock(return_value=0)
        
        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()
        
        # Make verify_and_launch_ws return immediately
        mock_verify_ws.return_value = None
        
        async with lifespan(app):
            # In the lifespan block
            pass
            
        mock_arq_pool.enqueue_job.assert_called_once_with("run_rest_gap_fill", ["BTCUSDT"], EXCHANGE_BINANCE)
        mock_verify_ws.assert_called_once_with("BTCUSDT", [], mock_arq_pool)

@pytest.mark.asyncio
async def test_lifespan_caught_up():
    mock_arq_pool = AsyncMock()
    
    with patch('apps.ingestion_app.orchestration.controller.DBPoolManager') as mock_db_pool, \
         patch('apps.ingestion_app.orchestration.controller.TimescaleReader') as mock_reader_class, \
         patch('apps.ingestion_app.orchestration.controller.create_pool') as mock_create_pool, \
         patch('apps.ingestion_app.orchestration.controller.verify_and_launch_ws') as mock_verify_ws, \
         patch('apps.ingestion_app.orchestration.controller.config_manager') as mock_config, \
         patch('apps.ingestion_app.orchestration.controller.datetime') as mock_datetime:
        
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT"],
            "ingestion.timeframes.base_gap_fill": "1m",
            "redis.uri": "redis://localhost:6379/0",
            "ingestion.websocket.warmup_threshold_ms": 300000
        }.get(k, default)
        
        mock_create_pool.return_value = mock_arq_pool
        
        mock_now = datetime(2023, 1, 31, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        now_ms = int(mock_now.timestamp() * 1000)
        
        # max_ts is just 1 minute (60s) ago
        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.close_pools = AsyncMock()
        
        mock_reader = mock_reader_class.return_value
        mock_reader.get_max_timestamp = AsyncMock(return_value=now_ms - 60000)
        
        mock_verify_ws.return_value = None
        
        async with lifespan(app):
            pass
            
        # Gap-fill shouldn't be called
        mock_arq_pool.enqueue_job.assert_not_called()
        mock_verify_ws.assert_called_once_with("BTCUSDT", [], mock_arq_pool)
