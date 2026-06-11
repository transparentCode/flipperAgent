from __future__ import annotations

from typing import Any

import asyncpg

from apps.ingestion_app_v2.control_plane.publisher import IngestionControlPublisher
from apps.ingestion_app_v2.control_plane.repository import IngestionAssetRegistryRepository
from apps.ingestion_app_v2.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetDesiredState,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetSource,
    IngestionAssetUpsertRequest,
    IngestionControlResult,
)
from libs.contracts.schemas import IngestionCommandType


class IngestionControlService:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        valkey_client: Any | None = None,
    ) -> None:
        self.repo = IngestionAssetRegistryRepository(pool)
        self.publisher = IngestionControlPublisher(valkey_client)

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
        return await self.publisher.publish(
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
        asset = existing.model_copy(update={**updates, "source": IngestionAssetSource.REGISTRY})
        persisted = await self.repo.upsert_asset(asset)
        return await self.publisher.publish(
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
        return await self.publisher.publish(
            asset=persisted,
            command_type=action,
            requested_by=body.requested_by,
            reason=body.reason,
        )

