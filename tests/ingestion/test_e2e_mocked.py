import pytest
import pandas as pd
import ccxt
from pydantic import ValidationError
from unittest.mock import AsyncMock

from apps.ingestion_app.orchestration.tasks import run_rest_gap_fill, _fetch_asset_gap
from apps.ingestion_app.constants import EXCHANGE_BINANCE
DEFAULT_ASSET = 'BTCUSDT'
BASE_GAP_FILL_TIMEFRAME = '1m'

DEFAULT_MOCK_TIMESTAMP = 1672531200000

pytestmark = pytest.mark.asyncio

async def test_standard_ingestion_flow(base_worker_ctx, mock_ccxt_adapter, mock_asyncpg_pool):
    """
    Standard Ingestion Flow:
    Given a mocked CCXT response.
    When run_rest_gap_fill is executed.
    Then raw data is normalized, and executemany is called on the DB poll.
    """
    symbol = DEFAULT_ASSET
    # Mocking CCXT adapter to return a DataFrame as expected
    mock_df = pd.DataFrame([
        [DEFAULT_MOCK_TIMESTAMP, 16000.0, 16100.0, 15900.0, 16050.0, 100.0]
    ], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    mock_ccxt_adapter.get_historical_ohlcv.return_value = mock_df
    
    await run_rest_gap_fill(base_worker_ctx, [symbol], EXCHANGE_BINANCE)
    
    # Assert DB `executemany` was called on the connection
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.executemany.assert_awaited_once()
    
    # Check that parameters passed to executemany have the normalized records
    call_args = conn.executemany.call_args
    query, tuples = call_args[0]
    
    assert "INSERT INTO market_1m_bars" in query or "INSERT INTO" in query
    assert len(tuples) == 1
    
    # timestamp, symbol, timeframe, open, high, low, close, volume
    res_tuple = tuples[0]
    assert res_tuple[1] == symbol
    assert res_tuple[2] == BASE_GAP_FILL_TIMEFRAME
    assert res_tuple[3] == 16000.0


async def test_rate_limit_backoff_validation(base_worker_ctx, mock_ccxt_adapter, mock_asyncpg_pool, mocker):
    """
    Rate Limit Backoff Validation:
    Given an adapter that raises ccxt.RateLimitExceeded on the first two calls, but succeeds on the third.
    When the task is invoked.
    Then tenacity logic retries without crashing and DB insert succeeds eventually.
    """
    # Mute the tenacity sleep to run fast in tests
    mocker.patch('tenacity.nap.time.sleep', return_value=None)
    mocker.patch('asyncio.sleep', return_value=None) # Mute asyncio sleep inside retry too
    
    symbol = "ETH/USDT"
    mock_df = pd.DataFrame([
        [DEFAULT_MOCK_TIMESTAMP, 1200.0, 1210.0, 1190.0, 1205.0, 50.0]
    ], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    call_count = 0
    async def mock_get_historical_ohlcv(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise ccxt.RateLimitExceeded("Simulated 429 Rate Limit")
        return mock_df
        
    mock_ccxt_adapter.get_historical_ohlcv.side_effect = mock_get_historical_ohlcv
    
    await run_rest_gap_fill(base_worker_ctx, [symbol], EXCHANGE_BINANCE)
    
    assert call_count == 3
    
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.executemany.assert_awaited_once()


async def test_invalid_payload_rejection(base_worker_ctx, mock_ccxt_adapter, mock_asyncpg_pool):
    """
    Invalid Payload Rejection:
    Given a mocked exchange response with invalid/missing fields.
    When the adapter hands off to Pydantic (inside the task or client).
    Then validation error is caught, the DB is not called.
    """
    symbol = "SOL/USDT"
    
    # Missing required field or invalid logic (e.g. high < low)
    mock_df = pd.DataFrame([
        [DEFAULT_MOCK_TIMESTAMP, 1000.0, 900.0, 950.0, 1000.0, 10.0] # high=900, low=950 (triggers check_high_low)
    ], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    mock_ccxt_adapter.get_historical_ohlcv.return_value = mock_df
    
    # Pydantic ValidationError isn't caught gracefully inside process_asset right now, 
    # we expect the task to either suppress it (log it) or bubble it depending on our change. 
    # The current code in run_rest_gap_fill catches Exception and logs it.
    await run_rest_gap_fill(base_worker_ctx, [symbol], EXCHANGE_BINANCE)
    
    # Database is not called
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.executemany.assert_not_called()