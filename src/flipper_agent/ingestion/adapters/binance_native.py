from flipper_agent.commons.config import ConfigManager
config_manager = ConfigManager()

import asyncio
import pandas as pd
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from typing import Dict, Any, List, AsyncGenerator

from flipper_agent.ingestion.adapters.base import BaseExchangeAdapter
from flipper_agent.commons.exceptions import DataIngestionError
from flipper_agent.ingestion.constants import (
    OHLCV_COLUMNS,
    BINANCE_KLINE_STREAM_TEMPLATE,
    BINANCE_RAW_KLINE_COLUMNS,
)

class BinanceNativeAdapter(BaseExchangeAdapter):
    """
    Adapter for Binance USD-M Futures using native binance-futures-connector.
    """

    def __init__(self, key: str = None, secret: str = None, **kwargs):
        self.client = UMFutures(key=key, secret=secret, **kwargs)

    def _fetch_and_parse_klines_sync(self, symbol: str, timeframe: str, **params) -> pd.DataFrame:
        lines = self.client.klines(symbol, timeframe, **params)
        
        df = pd.DataFrame(lines)
        if df.empty:
            return pd.DataFrame(columns=OHLCV_COLUMNS)

        df.columns = BINANCE_RAW_KLINE_COLUMNS
        df = df[OHLCV_COLUMNS]
        
        for col in OHLCV_COLUMNS:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        return df

    async def get_historical_ohlcv(self, symbol: str, timeframe: str, since: int = None, until: int = None, limit: int = None) -> pd.DataFrame:
        """
        Fetch historical OHLCV data using binance-futures-connector.
        """
        params = {}
        if since:
            params['startTime'] = since
        if until:
            params['endTime'] = until
        if limit:
            params['limit'] = limit

        try:
            return await asyncio.to_thread(self._fetch_and_parse_klines_sync, symbol, timeframe, **params)
        except Exception as e:
            raise DataIngestionError(f"Binance API failed to fetch OHLCV for {symbol}: {e}") from e

    async def stream_multiplex_socket(self, symbols: List[str], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Connect to Binance Websocket using ThreadedWebsocketManager and bridge via asyncio.Queue.
        """
        ws_client = UMFuturesWebsocketClient(on_message=lambda msg: loop.call_soon_threadsafe(queue.put_nowait, msg))
        
        try:
            streams = [BINANCE_KLINE_STREAM_TEMPLATE.format(symbol=symbol.lower(), interval=config_manager.get("ingestion.timeframes.binance_stream_interval", "1m")) for symbol in symbols]
            ws_client.multiplex_socket(streams)
            
            while True:
                msg = await queue.get()
                yield msg
        finally:
            ws_client.stop()

