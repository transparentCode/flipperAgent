import pytest
import pandas as pd
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from flipper_agent.commons.db.timescale_reader import TimescaleReader

@pytest.mark.asyncio
async def test_timescale_reader_empty_ohlcv():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    # Return empty list for fetch
    mock_conn.fetch.return_value = []
    
    # Mock acquire context manager
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_ctx
    
    reader = TimescaleReader(mock_pool)
    df = await reader.get_ohlcv('BTC/USDT', '1h', 1600000000000, 1600000000000)
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0
    assert list(df.columns) == ['timestamp', 'symbol', 'timeframe', 'open', 'high', 'low', 'close', 'volume']
    
@pytest.mark.asyncio
async def test_timescale_reader_with_data():
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    
    # Create fake records that behave like dicts (asyncpg.Record can be converted to dict)
    dt = datetime.now(timezone.utc)
    fake_record = {
        'timestamp': dt,
        'symbol': 'BTC/USDT',
        'timeframe': '1h',
        'open': 50000.0,
        'high': 51000.0,
        'low': 49000.0,
        'close': 50500.0,
        'volume': 100.0
    }
    
    mock_conn.fetch.return_value = [fake_record]
    
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_conn
    mock_pool.acquire.return_value = mock_ctx
    
    reader = TimescaleReader(mock_pool)
    df = await reader.get_ohlcv('BTC/USDT', '1h', 1600000000000, 1600000000000)
    
    assert len(df) == 1
    assert df.iloc[0]['close'] == 50500.0
    assert df.iloc[0]['volume'] == 100.0
