from __future__ import annotations

from typing import Any

import asyncpg

from apps.ingestion_app.control_plane.publisher import IngestionControlPublisher
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.control_plane.repository import IngestionAssetRegistryRepository
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
from libs.contracts.schemas import IngestionCommandType


class IngestionControlService:
    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        valkey_client: Any | None = None,
        config_manager: ConfigManager | Any | None = None,
    ) -> None:
        self.repo = IngestionAssetRegistryRepository(pool)
        self.config_manager = config_manager or ConfigManager()
        self.publisher = IngestionControlPublisher(
            valkey_client,
            config_manager=self.config_manager,
        )

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
        persistence_base = await self._resolve_persistence_base_asset(existing)
        updates = patch.model_dump(exclude_none=True, exclude={"reason", "requested_by"})
        asset = persistence_base.model_copy(
            update={**updates, "source": IngestionAssetSource.REGISTRY}
        )
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
        effective_desired_state = (
            IngestionAssetDesiredState.RESUMING
            if action == IngestionCommandType.RESUME_ASSET
            else desired_state
        )
        persistence_base = await self._resolve_persistence_base_asset(existing)
        asset = persistence_base.model_copy(
            update={
                "desired_state": effective_desired_state,
                "enabled": enabled,
                "source": IngestionAssetSource.REGISTRY,
            }
        )
        persisted = await self.repo.upsert_asset(asset)
        if self.publisher.valkey_client is not None and action in {
            IngestionCommandType.PAUSE_ASSET,
            IngestionCommandType.STOP_ASSET,
        }:
            coordinator = IngestionCoordinator(self.publisher.valkey_client)
            await coordinator.mark_resume_backfill_required(
                persisted.symbol,
                persisted.base_timeframe,
            )
        return await self.publisher.publish(
            asset=persisted,
            command_type=action,
            requested_by=body.requested_by,
            reason=body.reason,
        )

    async def _resolve_persistence_base_asset(
        self,
        existing: IngestionAssetRecord,
    ) -> IngestionAssetRecord:
        persisted = await self.repo.get_asset(existing.symbol)
        if persisted is not None:
            return persisted
        return existing
