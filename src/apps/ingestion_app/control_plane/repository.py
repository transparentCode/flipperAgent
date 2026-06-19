from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import Mock

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
                asset_version,
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
                asset_version,
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
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing_row = await conn.fetchrow(
                    """
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
                        asset_version,
                        created_at,
                        updated_at
                    FROM ingestion_assets
                    WHERE symbol = $1
                    FOR UPDATE
                    """,
                    asset.symbol,
                )

                if existing_row is None:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO ingestion_assets (
                            symbol,
                            exchange,
                            provider,
                            base_timeframe,
                            publish_timeframes,
                            historical_backfill_days,
                            retention_days,
                            enabled,
                            desired_state,
                            asset_version
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 1)
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
                            asset_version,
                            created_at,
                            updated_at
                        """,
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
                else:
                    existing = self._to_model(existing_row)
                    state_changed = self._state_payload(existing) != self._state_payload(asset)
                    next_version = existing.asset_version + 1 if state_changed else existing.asset_version
                    row = await conn.fetchrow(
                        """
                        UPDATE ingestion_assets
                        SET
                            exchange = $2,
                            provider = $3,
                            base_timeframe = $4,
                            publish_timeframes = $5,
                            historical_backfill_days = $6,
                            retention_days = $7,
                            enabled = $8,
                            desired_state = $9,
                            asset_version = $10,
                            updated_at = CASE WHEN $11 THEN NOW() ELSE updated_at END
                        WHERE symbol = $1
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
                            asset_version,
                            created_at,
                            updated_at
                        """,
                        asset.symbol,
                        asset.exchange,
                        asset.provider,
                        asset.base_timeframe,
                        asset.publish_timeframes,
                        asset.historical_backfill_days,
                        asset.retention_days,
                        asset.enabled,
                        asset.desired_state.value,
                        next_version,
                        state_changed,
                    )
        if row is None:
            raise RuntimeError(f"Failed to persist ingestion asset '{asset.symbol}'.")
        return self._to_model(row)

    @staticmethod
    def _to_model(row: Any) -> IngestionAssetRecord:
        if inspect.isawaitable(row) or isinstance(row, Mock):
            raise TypeError(f"Unsupported ingestion asset row type: {type(row)!r}")
        try:
            payload = dict(row)
        except TypeError as exc:
            raise TypeError(f"Unsupported ingestion asset row type: {type(row)!r}") from exc
        payload["source"] = IngestionAssetSource.REGISTRY
        payload["timeframe_version"] = payload.get("asset_version", 1)
        return IngestionAssetRecord.model_validate(payload)

    @staticmethod
    def _state_payload(asset: IngestionAssetRecord) -> dict[str, Any]:
        desired_state = getattr(asset.desired_state, "value", asset.desired_state)
        return {
            "symbol": asset.symbol,
            "exchange": asset.exchange,
            "provider": asset.provider,
            "base_timeframe": asset.base_timeframe,
            "publish_timeframes": list(asset.publish_timeframes),
            "historical_backfill_days": asset.historical_backfill_days,
            "retention_days": asset.retention_days,
            "enabled": asset.enabled,
            "desired_state": str(desired_state),
        }
