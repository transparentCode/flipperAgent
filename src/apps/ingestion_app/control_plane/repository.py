from __future__ import annotations

from typing import Any

import asyncpg

from apps.ingestion_app.models.asset_registry import IngestionAssetRecord, IngestionAssetSource


class IngestionAssetRegistryRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def list_assets(self) -> list[IngestionAssetRecord]:
        query = """
            SELECT
                symbol,
                exchange,
                provider,
                base_timeframe,
                publish_timeframes,
                historical_backfill_days,
                retention_days,
                enabled,
                desired_state,
                created_at,
                updated_at
            FROM ingestion_assets
            ORDER BY symbol ASC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
        return [self._to_model(row) for row in rows]

    async def get_asset(self, symbol: str) -> IngestionAssetRecord | None:
        query = """
            SELECT
                symbol,
                exchange,
                provider,
                base_timeframe,
                publish_timeframes,
                historical_backfill_days,
                retention_days,
                enabled,
                desired_state,
                created_at,
                updated_at
            FROM ingestion_assets
            WHERE symbol = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, symbol.upper())
        if row is None:
            return None
        return self._to_model(row)

    async def upsert_asset(self, asset: IngestionAssetRecord) -> IngestionAssetRecord:
        query = """
            INSERT INTO ingestion_assets (
                symbol,
                exchange,
                provider,
                base_timeframe,
                publish_timeframes,
                historical_backfill_days,
                retention_days,
                enabled,
                desired_state
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (symbol) DO UPDATE SET
                exchange = EXCLUDED.exchange,
                provider = EXCLUDED.provider,
                base_timeframe = EXCLUDED.base_timeframe,
                publish_timeframes = EXCLUDED.publish_timeframes,
                historical_backfill_days = EXCLUDED.historical_backfill_days,
                retention_days = EXCLUDED.retention_days,
                enabled = EXCLUDED.enabled,
                desired_state = EXCLUDED.desired_state,
                updated_at = NOW()
            RETURNING
                symbol,
                exchange,
                provider,
                base_timeframe,
                publish_timeframes,
                historical_backfill_days,
                retention_days,
                enabled,
                desired_state,
                created_at,
                updated_at
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                asset.symbol,
                asset.exchange,
                asset.provider,
                asset.base_timeframe,
                asset.publish_timeframes,
                asset.historical_backfill_days,
                asset.retention_days,
                asset.enabled,
                asset.desired_state.value,
            )
        if row is None:
            raise RuntimeError(f"Failed to persist ingestion asset '{asset.symbol}'.")
        return self._to_model(row)

    @staticmethod
    def _to_model(row: Any) -> IngestionAssetRecord:
        payload = dict(row)
        payload["source"] = IngestionAssetSource.REGISTRY
        return IngestionAssetRecord.model_validate(payload)

