from datetime import UTC, datetime

import asyncpg
import pandas as pd


class TimescaleReader:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def get_ticks(
        self, symbol: str, start_time: int, end_time: int
    ) -> pd.DataFrame:
        """
        Fetch tick (trade) data for a given symbol.
        start_time and end_time should be provided as integer milliseconds.
        """
        start_dt = datetime.fromtimestamp(start_time / 1000.0, tz=UTC)
        end_dt = datetime.fromtimestamp(end_time / 1000.0, tz=UTC)

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

        columns = ["timestamp", "symbol", "side", "price", "size"]
        if not records:
            return pd.DataFrame(columns=columns)

        return pd.DataFrame([dict(r) for r in records])

    async def get_open_interest(
        self, symbol: str, start_time: int, end_time: int
    ) -> pd.DataFrame:
        """
        Fetch open interest data for a given symbol.
        start_time and end_time should be provided as integer milliseconds.
        """
        start_dt = datetime.fromtimestamp(start_time / 1000.0, tz=UTC)
        end_dt = datetime.fromtimestamp(end_time / 1000.0, tz=UTC)

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

        columns = ["timestamp", "symbol", "open_interest"]
        if not records:
            return pd.DataFrame(columns=columns)

        return pd.DataFrame([dict(r) for r in records])

    async def get_latest_l2_features(
        self,
        symbol: str,
        *,
        max_age_seconds: int = 600,
    ) -> dict[str, float] | None:
        """Fetch the most recent L2 depth feature row for a symbol.

        Args:
            symbol: Asset symbol (e.g. "BTCUSDT").
            max_age_seconds: Maximum age of the snapshot in seconds.
                Rows older than this are treated as stale and ignored.
                Default 600 (10 min, 2× the 5-min poll interval).

        Returns a flat dict of feature values, or None if no fresh data exists.
        """
        query = """
            SELECT bid_ask_imbalance, depth_ratio, spread_bps,
                   depth_decay_bid, depth_decay_ask
            FROM l2_depth_features
            WHERE symbol = $1
              AND timestamp >= now() - make_interval(secs => $2::double precision)
            ORDER BY timestamp DESC
            LIMIT 1
        """
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(query, symbol, float(max_age_seconds))

        if not record:
            return None

        result: dict[str, float] = {}
        for col in (
            "bid_ask_imbalance",
            "depth_ratio",
            "spread_bps",
            "depth_decay_bid",
            "depth_decay_ask",
        ):
            val = record[col]
            if val is not None:
                result[col] = float(val)
            # Skip NULL columns — downstream sees absence, not TypeError
        return result if result else None
