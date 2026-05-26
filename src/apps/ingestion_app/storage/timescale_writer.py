import asyncpg
from typing import List

from ..models.tick_models import OHLCVRecord, TickRecord, OIRecord
from ..constants import TABLE_OHLCV, TABLE_TICKS, TABLE_OPEN_INTEREST

# Below this threshold, use executemany; at or above, use COPY protocol.
_COPY_THRESHOLD = 10


class TimescaleWriter:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def insert_ohlcv(self, records: List[OHLCVRecord], timeframe: str) -> None:
        if not records:
            return

        columns = ["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"]
        tuples = [
            (r.timestamp, r.symbol, timeframe, r.open, r.high, r.low, r.close, r.volume)
            for r in records
        ]

        async with self.pool.acquire() as conn:
            if len(tuples) < _COPY_THRESHOLD:
                query = f"""
                INSERT INTO {TABLE_OHLCV} ({', '.join(columns)})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (timestamp, symbol, timeframe)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume;
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
