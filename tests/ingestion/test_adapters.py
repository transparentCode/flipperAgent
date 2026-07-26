import asyncio
import pytest
import pandas as pd
from unittest.mock import patch

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.crypto_ccxt import CCXTAdapter
DEFAULT_BINANCE_ASSET = 'BTCUSDT'
BASE_GAP_FILL_TIMEFRAME = '1m'

@pytest.mark.asyncio
async def test_binance_native_adapter_structure():
    """Test that BinanceNativeAdapter returns a DataFrame with expected columns."""
    adapter = BinanceNativeAdapter()
    
    # Mock the klines return data (simulating simple OHLCV)
    mock_klines_data = [
        [1609459200000, "29000.0", "29100.0", "28900.0", "29050.0", "1500.0", 1609459259999, "43500000.0", 500, "700.0", "20300000.0", "0"]
    ]
    
    with patch.object(adapter.client, "klines", return_value=mock_klines_data):
        df = await adapter.get_historical_ohlcv(DEFAULT_BINANCE_ASSET, BASE_GAP_FILL_TIMEFRAME)
        
        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert list(df.columns) == ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_base']
        assert df.iloc[0]['close'] == 29050.0
        assert df.iloc[0]['taker_buy_base'] == 700.0


def test_ccxt_adapter_defaults_binance_to_linear_futures():
    adapter = CCXTAdapter("binance")

    assert adapter.exchange.options["defaultType"] == "future"
    assert adapter.exchange.options["defaultSubType"] == "linear"


@pytest.mark.asyncio
async def test_binance_native_adapter_queue_overflow_keeps_latest_message():
    queue = asyncio.Queue(maxsize=1)
    state = {"dropped": 0}

    BinanceNativeAdapter._enqueue_ws_message(queue, "first", state, 100)
    BinanceNativeAdapter._enqueue_ws_message(queue, "second", state, 100)

    assert state["dropped"] == 1
    assert queue.qsize() == 1
    assert await queue.get() == "second"


@pytest.mark.asyncio
async def test_binance_native_adapter_default_columns_stay_unchanged():
    adapter = BinanceNativeAdapter()
    mock_klines_data = [
        [1609459200000, "29000.0", "29100.0", "28900.0", "29050.0", "1500.0", 1609459259999, "43500000.0", 500, "700.0", "20300000.0", "0"]
    ]

    with patch.object(adapter.client, "klines", return_value=mock_klines_data):
        frame = await adapter.get_historical_ohlcv(DEFAULT_BINANCE_ASSET, BASE_GAP_FILL_TIMEFRAME)

    assert list(frame.columns) == [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base",
    ]


@pytest.mark.asyncio
async def test_binance_native_adapter_opt_in_returns_numeric_close_time():
    adapter = BinanceNativeAdapter()
    close_time = 1609459259999
    mock_klines_data = [
        [1609459200000, "29000.0", "29100.0", "28900.0", "29050.0", "1500.0", close_time, "43500000.0", 500, "700.0", "20300000.0", "0"]
    ]

    with patch.object(adapter.client, "klines", return_value=mock_klines_data):
        frame = await adapter.get_historical_ohlcv(
            DEFAULT_BINANCE_ASSET,
            BASE_GAP_FILL_TIMEFRAME,
            include_close_time=True,
        )

    assert "close_time" in frame.columns
    assert frame.iloc[0]["close_time"] == close_time
