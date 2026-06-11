from __future__ import annotations

import uuid
from time import time
from typing import Any

import asyncpg

from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM, INGESTION_EVENTS_STREAM
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetSource,
    IngestionAssetUpsertRequest,
    IngestionControlResult,
)
from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    IngestionCommandType,
    IngestionControlCommand,
    IngestionControlEvent,
    IngestionEventType,
    valkey_encode,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


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

    @staticmethod
    def _to_model(row: Any) -> IngestionAssetRecord:
        payload = dict(row)
        payload["source"] = IngestionAssetSource.REGISTRY
        return IngestionAssetRecord.model_validate(payload)

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


class IngestionAssetCatalog:
    def __init__(
        self,
        *,
        config_manager: ConfigManager | Any | None = None,
        pool: asyncpg.Pool | None = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.pool = pool

    async def list_effective_assets(self) -> list[IngestionAssetRecord]:
        config_assets = {asset.symbol: asset for asset in self._assets_from_config()}
        registry_assets = await self._load_registry_assets()
        if not registry_assets:
            return list(config_assets.values())

        for asset in registry_assets:
            config_assets[asset.symbol] = asset
        return [config_assets[symbol] for symbol in sorted(config_assets)]

    async def get_effective_asset(self, symbol: str) -> IngestionAssetRecord | None:
        symbol = symbol.upper()
        registry_assets = await self._load_registry_assets()
        for asset in registry_assets:
            if asset.symbol == symbol:
                return asset

        for asset in self._assets_from_config():
            if asset.symbol == symbol:
                return asset
        return None

    async def _load_registry_assets(self) -> list[IngestionAssetRecord]:
        try:
            pool = self.pool or DBPoolManager.get_reader_pool()
        except RuntimeError as exc:
            logger.warning(f"Registry DB pool unavailable; falling back to config assets: {exc}")
            return []

        repo = IngestionAssetRegistryRepository(pool)
        try:
            return await repo.list_assets()
        except asyncpg.PostgresError as exc:
            logger.warning(f"Registry table unavailable or unreadable; falling back to config assets: {exc}")
            return []

    def _assets_from_config(self) -> list[IngestionAssetRecord]:
        target_assets = self.config_manager.get("ingestion.assets.target_list", ["BTCUSDT"])
        publish_timeframes = self.config_manager.get("ingestion.assets.publish_timeframes", {})
        base_timeframe = self.config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
        historical_backfill_days = int(
            self.config_manager.get("ingestion.assets.historical_backfill_days", 2)
        )

        assets: list[IngestionAssetRecord] = []
        for symbol in target_assets:
            assets.append(
                IngestionAssetRecord(
                    symbol=symbol,
                    exchange="binance",
                    provider="binance_native",
                    base_timeframe=base_timeframe,
                    publish_timeframes=publish_timeframes.get(symbol, []),
                    historical_backfill_days=historical_backfill_days,
                    enabled=True,
                    desired_state=IngestionAssetDesiredState.LIVE,
                    source=IngestionAssetSource.CONFIG,
                )
            )
        return assets


class IngestionControlService:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        valkey_client: Any | None = None,
    ) -> None:
        self.repo = IngestionAssetRegistryRepository(pool)
        self.valkey_client = valkey_client

    async def upsert_asset(
        self,
        request: IngestionAssetUpsertRequest,
        *,
        command_type: IngestionCommandType,
    ) -> IngestionControlResult:
        asset = IngestionAssetRecord(
            symbol=request.symbol,
            exchange=request.exchange,
            provider=request.provider,
            base_timeframe=request.base_timeframe,
            publish_timeframes=request.publish_timeframes,
            historical_backfill_days=request.historical_backfill_days,
            retention_days=request.retention_days,
            enabled=request.enabled,
            desired_state=request.desired_state,
            source=IngestionAssetSource.REGISTRY,
        )
        persisted = await self.repo.upsert_asset(asset)
        return await self._publish_control_result(
            asset=persisted,
            command_type=command_type,
            requested_by=request.requested_by,
            reason=request.reason,
        )

    async def patch_asset(
        self,
        existing: IngestionAssetRecord,
        patch: IngestionAssetPatchRequest,
    ) -> IngestionControlResult:
        updates = patch.model_dump(exclude_none=True, exclude={"reason", "requested_by"})
        asset = existing.model_copy(
            update={**updates, "source": IngestionAssetSource.REGISTRY}
        )
        persisted = await self.repo.upsert_asset(asset)
        return await self._publish_control_result(
            asset=persisted,
            command_type=IngestionCommandType.UPDATE_ASSET,
            requested_by=patch.requested_by,
            reason=patch.reason,
        )

    async def apply_action(
        self,
        existing: IngestionAssetRecord,
        *,
        desired_state: IngestionAssetDesiredState,
        enabled: bool,
        action: IngestionCommandType,
        body: IngestionAssetActionRequest,
    ) -> IngestionControlResult:
        asset = existing.model_copy(
            update={
                "desired_state": desired_state,
                "enabled": enabled,
                "source": IngestionAssetSource.REGISTRY,
            }
        )
        persisted = await self.repo.upsert_asset(asset)
        return await self._publish_control_result(
            asset=persisted,
            command_type=action,
            requested_by=body.requested_by,
            reason=body.reason,
        )

    async def _publish_control_result(
        self,
        *,
        asset: IngestionAssetRecord,
        command_type: IngestionCommandType,
        requested_by: str,
        reason: str | None,
    ) -> IngestionControlResult:
        command_id = str(uuid.uuid4())
        command_stream_id: str | None = None
        event_stream_id: str | None = None
        command_published = False
        event_published = False

        command = IngestionControlCommand(
            command_id=command_id,
            command_type=command_type,
            symbol=asset.symbol,
            exchange=asset.exchange,
            provider=asset.provider,
            base_timeframe=asset.base_timeframe,
            publish_timeframes=asset.publish_timeframes,
            historical_backfill_days=asset.historical_backfill_days,
            retention_days=asset.retention_days,
            enabled=asset.enabled,
            desired_state=asset.desired_state.value,
            requested_by=requested_by,
            reason=reason,
            requested_at=time(),
        )
        event = IngestionControlEvent(
            event_id=str(uuid.uuid4()),
            event_type=IngestionEventType.COMMAND_ACCEPTED,
            command_id=command_id,
            command_type=command_type,
            symbol=asset.symbol,
            requested_by=requested_by,
            detail={
                "enabled": asset.enabled,
                "desired_state": asset.desired_state.value,
                "publish_timeframes": asset.publish_timeframes,
            },
            emitted_at=time(),
        )

        if self.valkey_client is not None:
            try:
                command_stream_id = await self.valkey_client.xadd(
                    INGESTION_CONTROL_STREAM,
                    valkey_encode(command),
                    maxlen=10_000,
                    approximate=True,
                )
                command_published = True
            except Exception as exc:
                logger.warning(
                    f"Failed to publish ingestion control command for {asset.symbol}: {exc}",
                    exc_info=True,
                )

            try:
                event_stream_id = await self.valkey_client.xadd(
                    INGESTION_EVENTS_STREAM,
                    valkey_encode(event),
                    maxlen=10_000,
                    approximate=True,
                )
                event_published = True
            except Exception as exc:
                logger.warning(
                    f"Failed to publish ingestion control event for {asset.symbol}: {exc}",
                    exc_info=True,
                )

        return IngestionControlResult(
            asset=asset,
            command_id=command_id,
            command_type=command_type.value,
            command_published=command_published,
            event_published=event_published,
            command_stream_id=command_stream_id,
            event_stream_id=event_stream_id,
        )
