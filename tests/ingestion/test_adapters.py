import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.tradingview_socket_interceptor import TradingViewInterceptor
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
        assert list(df.columns) == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        assert df.iloc[0]['close'] == 29050.0


@pytest.mark.asyncio
async def test_tradingview_interceptor_structure():
    """Test that TradingViewInterceptor builds a DataFrame from intercepted data."""
    adapter = TradingViewInterceptor()
    
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_session.page = mock_page
    
    with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.StealthyFetcher", return_value=mock_session):
        with patch.object(adapter, '_load_cookies', new_callable=AsyncMock):
            with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.asyncio.sleep", new_callable=AsyncMock):
                
                # Mock a frame payload that triggers DataFrame appending
                def on_websocket_side_effect(event, callback):
                    if event == "websocket":
                        mock_ws = MagicMock()
                        
                        def on_framereceived_side_effect(ws_event, frm_callback):
                            if ws_event == "framereceived":
                                mock_frame = MagicMock()
                                payload = '{"m": "timescale_update", "p": ["cs_id", {"s": [{"v": [1685412000, 1.1, 1.2, 1.0, 1.15, 1000]}]}]}'
                                mock_frame.text = f"~m~{len(payload)}~m~{payload}"
                                frm_callback(mock_frame)
                        
                        mock_ws.on.side_effect = on_framereceived_side_effect
                        callback(mock_ws)
                
                mock_page.on.side_effect = on_websocket_side_effect
                
                df = await adapter.get_historical_ohlcv(f"BINANCE:{DEFAULT_BINANCE_ASSET}", BASE_GAP_FILL_TIMEFRAME)
                
                assert isinstance(df, pd.DataFrame)
                assert not df.empty
                assert list(df.columns) == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                assert df.iloc[0]['close'] == 1.15
                assert df.iloc[0]['timestamp'] == 1685412000

@pytest.mark.asyncio
async def test_tradingview_interceptor_empty():
    """Test that TradingViewInterceptor returns empty df with correct columns when no matching frame."""
    adapter = TradingViewInterceptor()
    
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_session.page = mock_page
    
    with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.StealthyFetcher", return_value=mock_session):
        with patch.object(adapter, '_load_cookies', new_callable=AsyncMock):
            with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.asyncio.sleep", new_callable=AsyncMock):
                
                def on_websocket_side_effect(event, callback):
                    pass
                
                mock_page.on.side_effect = on_websocket_side_effect
                
                df = await adapter.get_historical_ohlcv(f"BINANCE:{DEFAULT_BINANCE_ASSET}", BASE_GAP_FILL_TIMEFRAME)
                
                assert isinstance(df, pd.DataFrame)
                assert df.empty
                assert list(df.columns) == ['timestamp', 'open', 'high', 'low', 'close', 'volume']


@pytest.mark.asyncio
async def test_tradingview_interceptor_live_and_historical():
    """Test that TradingViewInterceptor builds a DataFrame from both historical (timescale_update) and live (du) payloads."""
    adapter = TradingViewInterceptor()
    
    with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.StealthyFetcher") as mock_fetcher_cls:
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher
        
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_fetcher.page = mock_page
        
        # We need mock context to avoid NoneType
        mock_context = MagicMock()
        mock_context.add_cookies = AsyncMock()
        mock_browser = MagicMock()
        mock_browser.contexts = [mock_context]
        mock_fetcher.browser = mock_browser
        
        with patch.object(adapter, '_load_cookies', new_callable=AsyncMock):
            with patch("apps.ingestion_app.adapters.tradingview_socket_interceptor.asyncio.sleep", new_callable=AsyncMock):
                
                # Mock frames that trigger DataFrame appending
                def on_websocket_side_effect(event, callback):
                    if event == "websocket":
                        mock_ws = MagicMock()
                        
                        def on_framereceived_side_effect(ws_event, frm_callback):
                            if ws_event == "framereceived":
                                # 1. Historical payload
                                mock_frame_hist = MagicMock()
                                hist_payload = '{"m": "timescale_update", "p": ["cs_id", {"s": [{"v": [1685412000, 1.1, 1.2, 1.0, 1.15, 1000]}]}]}'
                                mock_frame_hist.text = f"~m~{len(hist_payload)}~m~{hist_payload}"
                                frm_callback(mock_frame_hist)
                                
                                # 2. Live update payload (du)
                                mock_frame_live = MagicMock()
                                live_payload = '{"m": "du", "p": ["cs_id", {"s": [{"v": [1685412060, 1.15, 1.25, 1.12, 1.22, 500]}]}]}'
                                mock_frame_live.text = f"~m~{len(live_payload)}~m~{live_payload}"
                                frm_callback(mock_frame_live)
                        
                        mock_ws.on.side_effect = on_framereceived_side_effect
                        callback(mock_ws)
                
                mock_page.on.side_effect = on_websocket_side_effect
                
                df = await adapter.get_historical_ohlcv("BINANCE:TOTAL2", "1m")
                
                assert isinstance(df, pd.DataFrame)
                assert not df.empty
                assert len(df) == 2  # One from historic, one from live
                assert list(df.columns) == ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                
                # Assert historical
                assert df.iloc[0]['close'] == 1.15
                assert df.iloc[0]['timestamp'] == 1685412000
                
                # Assert live update tick
                assert df.iloc[1]['close'] == 1.22
                assert df.iloc[1]['timestamp'] == 1685412060
