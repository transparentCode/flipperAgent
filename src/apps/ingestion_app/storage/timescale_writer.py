import asyncpg
from typing import List

from ..models.tick_models import OHLCVRecord, TickRecord, OIRecord, FundingRateRecord, L2DepthFeatureRecord
from ..constants import TABLE_OHLCV, TABLE_TICKS, TABLE_OPEN_INTEREST, TABLE_FUNDING_RATE, TABLE_L2_DEPTH_FEATURES

# Below this threshold, use executemany; at or above, use COPY protocol.
_COPY_THRESHOLD = 10


class TimescaleWriter:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def insert_ohlcv(self, records: List[OHLCVRecord], timeframe: str) -> None:
        if not records:
            return

        columns = ["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume", "taker_buy_base"]
        tuples = [
            (r.timestamp, r.symbol, timeframe, r.open, r.high, r.low, r.close, r.volume, r.taker_buy_base)
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_OHLCV} ({', '.join(columns)})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (timestamp, symbol, timeframe)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    taker_buy_base = EXCLUDED.taker_buy_base;
                """
                await conn.executemany(query, tuples)
            else:
                async with conn.transaction():
                    await conn.execute(
                        f"CREATE TEMP TABLE _stage (LIKE {TABLE_OHLCV} INCLUDING DEFAULTS) ON COMMIT DROP"
                    )
                    await conn.copy_records_to_table("_stage", records=tuples, columns=columns)
                    col_list = ", ".join(columns)
                    update_cols = ", ".join(
                        f"{c} = EXCLUDED.{c}"
                        for c in columns
                        if c not in ("timestamp", "symbol", "timeframe")
                    )
                    await conn.execute(
                        f"INSERT INTO {TABLE_OHLCV} ({col_list}) "
                        f"SELECT {col_list} FROM _stage "
                        f"ON CONFLICT (timestamp, symbol, timeframe) "
                        f"DO UPDATE SET {update_cols}"
                    )

    async def insert_ticks(self, records: List[TickRecord]) -> None:
        if not records:
            return

        columns = ["timestamp", "symbol", "side", "price", "size"]
        tuples = [
            (r.timestamp, r.symbol, r.side, r.price, r.size)
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_TICKS} ({', '.join(columns)})
                VALUES ($1, $2, $3, $4, $5);
                """
                await conn.executemany(query, tuples)
            else:
                await conn.copy_records_to_table(TABLE_TICKS, records=tuples, columns=columns)

    async def insert_open_interest(self, records: List[OIRecord]) -> None:
        if not records:
            return

        columns = ["timestamp", "symbol", "open_interest"]
        tuples = [
            (r.timestamp, r.symbol, r.open_interest)
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_OPEN_INTEREST} ({', '.join(columns)})
                VALUES ($1, $2, $3)
                ON CONFLICT (timestamp, symbol)
                DO UPDATE SET
                    open_interest = EXCLUDED.open_interest;
                """
                await conn.executemany(query, tuples)
            else:
                async with conn.transaction():
                    await conn.execute(
                        f"CREATE TEMP TABLE _stage (LIKE {TABLE_OPEN_INTEREST} INCLUDING DEFAULTS) ON COMMIT DROP"
                    )
                    await conn.copy_records_to_table("_stage", records=tuples, columns=columns)
                    col_list = ", ".join(columns)
                    await conn.execute(
                        f"INSERT INTO {TABLE_OPEN_INTEREST} ({col_list}) "
                        f"SELECT {col_list} FROM _stage "
                        f"ON CONFLICT (timestamp, symbol) "
                        f"DO UPDATE SET open_interest = EXCLUDED.open_interest"
                    )

    async def insert_l2_depth(self, records: List[L2DepthFeatureRecord]) -> None:
        if not records:
            return

        columns = [
            "timestamp", "symbol", "bid_ask_imbalance", "depth_ratio",
            "spread_bps", "depth_decay_bid", "depth_decay_ask",
            "best_bid", "best_ask", "bid_depth_total", "ask_depth_total",
            "snapshot_levels",
        ]
        tuples = [
            (
                r.timestamp, r.symbol, r.bid_ask_imbalance, r.depth_ratio,
                r.spread_bps, r.depth_decay_bid, r.depth_decay_ask,
                r.best_bid, r.best_ask, r.bid_depth_total, r.ask_depth_total,
                r.snapshot_levels,
            )
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_L2_DEPTH_FEATURES} ({', '.join(columns)})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (timestamp, symbol)
                DO UPDATE SET
                    bid_ask_imbalance = EXCLUDED.bid_ask_imbalance,
                    depth_ratio = EXCLUDED.depth_ratio,
                    spread_bps = EXCLUDED.spread_bps,
                    depth_decay_bid = EXCLUDED.depth_decay_bid,
                    depth_decay_ask = EXCLUDED.depth_decay_ask,
                    best_bid = EXCLUDED.best_bid,
                    best_ask = EXCLUDED.best_ask,
                    bid_depth_total = EXCLUDED.bid_depth_total,
                    ask_depth_total = EXCLUDED.ask_depth_total,
                    snapshot_levels = EXCLUDED.snapshot_levels;
                """
                await conn.executemany(query, tuples)
            else:
                async with conn.transaction():
                    await conn.execute(
                        f"CREATE TEMP TABLE _stage (LIKE {TABLE_L2_DEPTH_FEATURES} INCLUDING DEFAULTS) ON COMMIT DROP"
                    )
                    await conn.copy_records_to_table("_stage", records=tuples, columns=columns)
                    col_list = ", ".join(columns)
                    update_cols = ", ".join(
                        f"{c} = EXCLUDED.{c}"
                        for c in columns
                        if c not in ("timestamp", "symbol")
                    )
                    await conn.execute(
                        f"INSERT INTO {TABLE_L2_DEPTH_FEATURES} ({col_list}) "
                        f"SELECT {col_list} FROM _stage "
                        f"ON CONFLICT (timestamp, symbol) "
                        f"DO UPDATE SET {update_cols}"
                    )

    async def insert_funding_rate(self, records: List[FundingRateRecord]) -> None:
        if not records:
            return

        columns = ["timestamp", "symbol", "funding_rate"]
        tuples = [
            (r.timestamp, r.symbol, r.funding_rate)
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_FUNDING_RATE} ({', '.join(columns)})
                VALUES ($1, $2, $3)
                ON CONFLICT (timestamp, symbol)
                DO UPDATE SET
                    funding_rate = EXCLUDED.funding_rate;
                """
                await conn.executemany(query, tuples)
            else:
                async with conn.transaction():
                    await conn.execute(
                        f"CREATE TEMP TABLE _stage (LIKE {TABLE_FUNDING_RATE} INCLUDING DEFAULTS) ON COMMIT DROP"
                    )
                    await conn.copy_records_to_table("_stage", records=tuples, columns=columns)
                    col_list = ", ".join(columns)
                    await conn.execute(
                        f"INSERT INTO {TABLE_FUNDING_RATE} ({col_list}) "
                        f"SELECT {col_list} FROM _stage "
                        f"ON CONFLICT (timestamp, symbol) "
                        f"DO UPDATE SET funding_rate = EXCLUDED.funding_rate"
                    )
