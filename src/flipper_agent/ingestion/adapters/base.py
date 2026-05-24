from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pandas as pd

class BaseExchangeAdapter(ABC):
    """
    Abstract Base Class for all ingestion data exchange adapters.
    Ensures all extraction modules adhere to a standard data contract.
    """

    @abstractmethod
    async def get_historical_ohlcv(self, symbol: str, timeframe: str, since: int = None, until: int = None, limit: int = None) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.

        Returns:
            pd.DataFrame: A DataFrame with columns ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        """
        pass
