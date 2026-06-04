import asyncpg
import pandas as pd
from datetime import datetime, timezone, timedelta

# Map timeframe strings to PostgreSQL interval literals
TF_INTERVAL_MAP: dict[str, str] = {
    "1m": "1 minute",
    "5m": "5 minutes",
    "15m": "15 minutes",
    "30m": "30 minutes",
    "1h": "1 hour",
    "4h": "4 hours",
    "1d": "1 day",
}

# Map timeframe strings to seconds (for lookback calculation)
TF_SECONDS_MAP: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

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
            SELECT timestamp, symbol, timeframe, open, high, low, close, volume, taker_buy_base
            FROM ohlcv
            WHERE symbol = $1 
              AND timeframe = $2
              AND timestamp >= $3
              AND timestamp <= $4
            ORDER BY timestamp ASC
        """
        
        async with self.pool.acquire() as conn:
            records = await conn.fetch(query, symbol, timeframe, start_dt, end_dt)
            
        columns = ['timestamp', 'symbol', 'timeframe', 'open', 'high', 'low', 'close', 'volume', 'taker_buy_base']
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

    async def get_ohlcv_aggregated(
        self,
        symbol: str,
        timeframe: str,
        max_lookback: int,
    ) -> pd.DataFrame:
        """Aggregate 1m candles into a higher timeframe using time_bucket.

        Falls back to a direct query when timeframe is '1m'.
        Returns a DataFrame with columns [timestamp, open, high, low, close, volume].
        """
        interval = TF_INTERVAL_MAP.get(timeframe)
        if interval is None:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        tf_seconds = TF_SECONDS_MAP.get(timeframe, 60)
        since = datetime.now(timezone.utc) - timedelta(seconds=tf_seconds * max_lookback)
        interval_td = timedelta(seconds=tf_seconds)

        if timeframe == "1m":
            query = """
                SELECT timestamp, open, high, low, close, volume, taker_buy_base
                FROM ohlcv
                WHERE symbol = $1 AND timeframe = '1m'
                  AND timestamp >= $2
                ORDER BY timestamp ASC
                LIMIT $3
            """
            async with self.pool.acquire() as conn:
                records = await conn.fetch(query, symbol, since, max_lookback)
        else:
            # Aggregate higher-TF candles from 1m data using time_bucket
            agg_query = """
                SELECT
                    time_bucket($2::interval, timestamp) AS timestamp,
                    FIRST(open, timestamp) AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST(close, timestamp) AS close,
                    SUM(volume) AS volume,
                    SUM(taker_buy_base) AS taker_buy_base
                FROM ohlcv
                WHERE symbol = $1 AND timeframe = '1m'
                  AND timestamp >= $3
                GROUP BY time_bucket($2::interval, timestamp)
                ORDER BY timestamp ASC
                LIMIT $4
            """
            async with self.pool.acquire() as conn:
                records = await conn.fetch(agg_query, symbol, interval_td, since, max_lookback)

        columns = ["timestamp", "open", "high", "low", "close", "volume", "taker_buy_base"]
        if not records:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([dict(r) for r in records])

    async def get_latest_l2_features(self, symbol: str) -> dict[str, float] | None:
        """Fetch the most recent L2 depth feature row for a symbol.

        Returns a flat dict of feature values, or None if no data exists.
        """
        query = """
            SELECT bid_ask_imbalance, depth_ratio, spread_bps,
                   depth_decay_bid, depth_decay_ask
            FROM l2_depth_features
            WHERE symbol = $1
            ORDER BY timestamp DESC
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, symbol)

        if not record:
            return None

        return {
            "bid_ask_imbalance": float(record["bid_ask_imbalance"]),
            "depth_ratio": float(record["depth_ratio"]),
            "spread_bps": float(record["spread_bps"]),
            "depth_decay_bid": float(record["depth_decay_bid"]),
            "depth_decay_ask": float(record["depth_decay_ask"]),
        }
