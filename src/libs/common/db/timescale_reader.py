import asyncpg
import pandas as pd
from datetime import datetime, timezone

class TimescaleReader:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_max_timestamp(self, symbol: str, timeframe: str) -> int:
        """
        Fetch the maximum timestamp for a given symbol and timeframe from the ohlcv table.
        Returns the timestamp in integer milliseconds, or 0 if no records exist.
        """
        query = """
            SELECT MAX(timestamp) as max_ts
            FROM ohlcv
            WHERE symbol = $1
              AND timeframe = $2
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, symbol, timeframe)
            
        if record and record['max_ts']:
            return int(record['max_ts'].replace(tzinfo=timezone.utc).timestamp() * 1000)
        return 0

    async def get_ohlcv(self, symbol: str, timeframe: str, start_time: int, end_time: int) -> pd.DataFrame:
        """
        Fetch OHLCV data for a given symbol and timeframe.
        start_time and end_time should be provided as integer milliseconds.
        """
        start_dt = datetime.fromtimestamp(start_time / 1000.0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time / 1000.0, tz=timezone.utc)
        
        query = """
            SELECT timestamp, symbol, timeframe, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = $1 
              AND timeframe = $2
              AND timestamp >= $3
              AND timestamp <= $4
            ORDER BY timestamp ASC
        """
        
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, symbol, timeframe, start_dt, end_dt)
            
        columns = ['timestamp', 'symbol', 'timeframe', 'open', 'high', 'low', 'close', 'volume']
        if not records:
            return pd.DataFrame(columns=columns)
            
        df = pd.DataFrame([dict(r) for r in records])
        return df

    async def get_ticks(self, symbol: str, start_time: int, end_time: int) -> pd.DataFrame:
        """
        Fetch tick (trade) data for a given symbol.
        start_time and end_time should be provided as integer milliseconds.
        """
        start_dt = datetime.fromtimestamp(start_time / 1000.0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time / 1000.0, tz=timezone.utc)
        
        query = """
            SELECT timestamp, symbol, side, price, size
            FROM ticks
            WHERE symbol = $1 
              AND timestamp >= $2
              AND timestamp <= $3
            ORDER BY timestamp ASC
        """
        
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, symbol, start_dt, end_dt)
            
        columns = ['timestamp', 'symbol', 'side', 'price', 'size']
        if not records:
            return pd.DataFrame(columns=columns)
            
        return pd.DataFrame([dict(r) for r in records])

    async def get_open_interest(self, symbol: str, start_time: int, end_time: int) -> pd.DataFrame:
        """
        Fetch open interest data for a given symbol.
        start_time and end_time should be provided as integer milliseconds.
        """
        start_dt = datetime.fromtimestamp(start_time / 1000.0, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_time / 1000.0, tz=timezone.utc)
        
        query = """
            SELECT timestamp, symbol, open_interest
            FROM open_interest
            WHERE symbol = $1 
              AND timestamp >= $2
              AND timestamp <= $3
            ORDER BY timestamp ASC
        """
        
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, symbol, start_dt, end_dt)
            
        columns = ['timestamp', 'symbol', 'open_interest']
        if not records:
            return pd.DataFrame(columns=columns)
            
        return pd.DataFrame([dict(r) for r in records])
