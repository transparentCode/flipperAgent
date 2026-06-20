from __future__ import annotations

import asyncpg

from apps.ingestion_app.constants import (
    TABLE_FUNDING_RATE,
    TABLE_L2_DEPTH_FEATURES,
    TABLE_OHLCV,
    TABLE_OPEN_INTEREST,
    TABLE_TICKS,
    TABLE_TV_INDEX_OHLCV,
)


class IngestionStorageJanitor:
    _DATA_TABLES = (
        TABLE_OHLCV,
        TABLE_TICKS,
        TABLE_OPEN_INTEREST,
        TABLE_FUNDING_RATE,
        TABLE_L2_DEPTH_FEATURES,
        TABLE_TV_INDEX_OHLCV,
    )

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def list_pending_removals(self) -> list[tuple[str, str]]:
        query = """
            SELECT symbol, base_timeframe
            FROM ingestion_assets
            WHERE desired_state = 'REMOVING'
            ORDER BY symbol ASC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [(str(row["symbol"]).upper(), str(row["base_timeframe"])) for row in rows]

    async def purge_asset_data(self, symbol: str) -> dict[str, int]:
        symbol = symbol.upper()
        deleted_rows: dict[str, int] = {}

        async with self.pool.acquire() as conn:
            for table in self._DATA_TABLES:
                exists = await conn.fetchval("SELECT to_regclass($1)", table)
                if exists is None:
                    continue

                result = await conn.execute(f"DELETE FROM {table} WHERE symbol = $1", symbol)
                deleted_rows[table] = _parse_delete_count(result)

        return deleted_rows

    async def finalize_asset_removal(self, symbol: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE ingestion_assets
                SET enabled = FALSE,
                    desired_state = 'STOPPED',
                    updated_at = NOW()
                WHERE symbol = $1
                  AND desired_state = 'REMOVING'
                """,
                symbol.upper(),
            )
        return _parse_delete_count(result) > 0


def _parse_delete_count(result: str) -> int:
    try:
        return int(str(result).split()[-1])
    except (IndexError, ValueError):
        return 0
