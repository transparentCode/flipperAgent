import asyncio
import pandas as pd
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from typing import Dict, Any, List, AsyncGenerator

from apps.ingestion_app.adapters.base import BaseExchangeAdapter
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger
from apps.ingestion_app.constants import (
    OHLCV_COLUMNS,
    OHLCV_TAKER_COLUMNS,
    BINANCE_RAW_KLINE_COLUMNS,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

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
        df = df[OHLCV_TAKER_COLUMNS].copy()
        df.rename(columns={'taker_buy_base_asset_volume': 'taker_buy_base'}, inplace=True)
        
        for col in df.columns:
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

    @staticmethod
    def _enqueue_ws_message(
        queue: asyncio.Queue,
        msg: Dict[str, Any] | str,
        state: Dict[str, int],
        drop_warning_every: int,
    ) -> None:
        try:
            queue.put_nowait(msg)
            return
        except asyncio.QueueFull:
            state["dropped"] = state.get("dropped", 0) + 1

        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

        dropped = state["dropped"]
        if dropped == 1 or dropped % drop_warning_every == 0:
            logger.warning(
                "Binance WS queue full; dropped %s message(s) to control backlog",
                dropped,
            )

    async def stream_multiplex_socket(self, symbols_timeframes: Dict[str, List[str]], loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Connect to Binance Websocket using UMFuturesWebsocketClient and bridge via asyncio.Queue.
        """
        config = ConfigManager()
        drop_warning_every = max(
            1,
            int(config.get("ingestion.websocket.queue_drop_warning_every", 100)),
        )
        queue_state = {"dropped": 0}
        ws_client = UMFuturesWebsocketClient(
            stream_url=config.get("ingestion.websocket.stream_url", "wss://fstream.binance.com"),
            on_message=lambda _ws, msg: loop.call_soon_threadsafe(
                self._enqueue_ws_message,
                queue,
                msg,
                queue_state,
                drop_warning_every,
            ),
            is_combined=True,
        )
        
        try:
            for symbol, timeframes in symbols_timeframes.items():
                for interval in timeframes:
                    ws_client.kline(symbol=symbol.lower(), interval=interval)
            
            while True:
                msg = await queue.get()
                yield msg
        finally:
            ws_client.stop()
