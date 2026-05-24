import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from typing import Dict, Any

from apps.ingestion_app.adapters.base import BaseExchangeAdapter
from libs.common.exceptions import DataIngestionError
from apps.ingestion_app.constants import OHLCV_COLUMNS

class CCXTAdapter(BaseExchangeAdapter):
    """
    Adapter for fetching data via CCXT async_support.
    """
    
    def __init__(self, exchange_id: str, config: Dict[str, Any] = None):
        self.exchange_id = exchange_id
        config = config or {}
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class(config)

    @staticmethod
    def _parse_ohlcv_sync(ohlcv: list) -> pd.DataFrame:
        df = pd.DataFrame(ohlcv, columns=OHLCV_COLUMNS)
        return df

    async def get_historical_ohlcv(self, symbol: str, timeframe: str, since: int = None, until: int = None, limit: int = None) -> pd.DataFrame:
        """
        Fetch historical OHLCV data using CCXT.
        """
        try:
            params = {}
            if until:
                params['until'] = until
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, since, limit, params=params)
            # DataFrame assembly can be CPU-bound, defer to thread
            return await asyncio.to_thread(self._parse_ohlcv_sync, ohlcv)
        except ccxt.BaseError as e:
            raise DataIngestionError(f"CCXT failed to fetch OHLCV for {symbol}: {e}") from e

    async def close(self) -> None:
        """
        Close the underlying CCXT exchange connection.
        """
        if self.exchange:
            await self.exchange.close()
