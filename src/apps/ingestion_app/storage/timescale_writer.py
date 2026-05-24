import asyncpg
from typing import List

from ..models.tick_models import OHLCVRecord, TickRecord, OIRecord
from ..constants import TABLE_OHLCV, TABLE_TICKS, TABLE_OPEN_INTEREST

class TimescaleWriter:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def insert_ohlcv(self, records: List[OHLCVRecord], timeframe: str) -> None:
        if not records:
            return
            
        tuples = [
            (
                r.timestamp, 
                r.symbol, 
                timeframe, 
                r.open, 
                r.high, 
                r.low, 
                r.close, 
                r.volume
            )
            for r in records
        ]
        
        query = f"""
        INSERT INTO {TABLE_OHLCV} (timestamp, symbol, timeframe, open, high, low, close, volume)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (timestamp, symbol, timeframe) 
        DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, tuples)

    async def insert_ticks(self, records: List[TickRecord]) -> None:
        if not records:
            return
            
        tuples = [
            (
                r.timestamp,
                r.symbol,
                r.side,
                r.price,
                r.size
            )
            for r in records
        ]
        
        query = f"""
        INSERT INTO {TABLE_TICKS} (timestamp, symbol, side, price, size)
        VALUES ($1, $2, $3, $4, $5);
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, tuples)

    async def insert_open_interest(self, records: List[OIRecord]) -> None:
        if not records:
            return
            
        tuples = [
            (
                r.timestamp,
                r.symbol,
                r.open_interest
            )
            for r in records
        ]
        
        query = f"""
        INSERT INTO {TABLE_OPEN_INTEREST} (timestamp, symbol, open_interest)
        VALUES ($1, $2, $3)
        ON CONFLICT (timestamp, symbol) 
        DO UPDATE SET 
            open_interest = EXCLUDED.open_interest;
        """
        async with self.pool.acquire() as conn:
            await conn.executemany(query, tuples)
