from __future__ import annotations

import uuid
from time import time
from typing import Any

from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM, INGESTION_EVENTS_STREAM
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetDesiredState,
    IngestionAssetRecord,
    IngestionControlResult,
)
from libs.common.asset_manifest import AssetManifestStore
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


def _desired_state_value(asset: IngestionAssetRecord) -> str:
    desired_state = asset.desired_state
    if isinstance(desired_state, IngestionAssetDesiredState):
        return desired_state.value
    return IngestionAssetDesiredState(str(desired_state)).value


class IngestionControlPublisher:
    def __init__(self, valkey_client: Any | None = None) -> None:
        self.valkey_client = valkey_client

    async def publish(
        self,
        *,
        asset: IngestionAssetRecord,
        command_type: IngestionCommandType,
        requested_by: str,
        reason: str | None,
    ) -> IngestionControlResult:
        command_id = str(uuid.uuid4())
        published_at = time()
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
            desired_state=_desired_state_value(asset),
            requested_by=requested_by,
            reason=reason,
            requested_at=published_at,
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
                "desired_state": _desired_state_value(asset),
                "publish_timeframes": asset.publish_timeframes,
            },
            emitted_at=published_at,
        )

        if self.valkey_client is not None:
            manifest_store = AssetManifestStore(self.valkey_client)
            manifest_synced = False
            try:
                await manifest_store.sync_from_ingestion_asset(asset, updated_at=published_at)
                manifest_synced = True
            except Exception as exc:
                logger.warning(
                    f"Failed to sync asset manifest for {asset.symbol}: {exc}",
                    exc_info=True,
                )
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
            if manifest_synced and self._should_publish_lifecycle_event(command_type, asset):
                try:
                    await manifest_store.publish_lifecycle_event(
                        asset=asset,
                        command_type=command_type,
                        requested_by=requested_by,
                        reason=reason,
                        emitted_at=published_at,
                    )
                except Exception as exc:
                    logger.warning(
                        f"Failed to publish asset lifecycle event for {asset.symbol}: {exc}",
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

    @staticmethod
    def _should_publish_lifecycle_event(
        command_type: IngestionCommandType,
        asset: IngestionAssetRecord,
    ) -> bool:
        return not (
            command_type == IngestionCommandType.RESUME_ASSET
            and _desired_state_value(asset) == IngestionAssetDesiredState.RESUMING.value
        )
