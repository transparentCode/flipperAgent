import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
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
