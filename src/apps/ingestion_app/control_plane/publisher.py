from __future__ import annotations

import hashlib
from time import time
from typing import Any

from apps.ingestion_app.constants import INGESTION_CONTROL_STREAM, INGESTION_EVENTS_STREAM
from apps.ingestion_app.control_plane.catalog import apply_effective_runtime_contract
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetDesiredState,
    IngestionAssetRecord,
    IngestionControlResult,
)
from libs.common.config import ConfigManager
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

_PUBLISH_DEDUP_PREFIX = "ingestion:publish_dedup"


def _desired_state_value(asset: IngestionAssetRecord) -> str:
    desired_state = asset.desired_state
    if isinstance(desired_state, IngestionAssetDesiredState):
        return desired_state.value
    return IngestionAssetDesiredState(str(desired_state)).value


class IngestionControlPublisher:
    def __init__(
        self,
        valkey_client: Any | None = None,
        *,
        config_manager: ConfigManager | Any | None = None,
    ) -> None:
        self.valkey_client = valkey_client
        self.config_manager = config_manager or ConfigManager()
        self.command_stream_maxlen = int(
            self.config_manager.get("ingestion.streams.control_maxlen", 5000)
        )
        self.command_stream_approximate = bool(
            self.config_manager.get("ingestion.streams.control_approximate", True)
        )
        self.event_stream_maxlen = int(
            self.config_manager.get("ingestion.streams.events_maxlen", 5000)
        )
        self.event_stream_approximate = bool(
            self.config_manager.get("ingestion.streams.events_approximate", True)
        )
        self.lifecycle_stream_maxlen = int(
            self.config_manager.get("ingestion.streams.lifecycle_maxlen", 5000)
        )
        self.lifecycle_stream_approximate = bool(
            self.config_manager.get("ingestion.streams.lifecycle_approximate", True)
        )
        self.publish_dedup_ttl_seconds = int(
            self.config_manager.get("ingestion.idempotency.publish_dedup_ttl_seconds", 7 * 24 * 60 * 60)
        )

    async def publish(
        self,
        *,
        asset: IngestionAssetRecord,
        command_type: IngestionCommandType,
        request_id: str | None = None,
        requested_by: str,
        reason: str | None,
    ) -> IngestionControlResult:
        effective_asset = apply_effective_runtime_contract(
            asset,
            config_manager=self.config_manager,
        )
        asset_version = int(getattr(effective_asset, "asset_version", 1))
        timeframe_version = int(getattr(effective_asset, "timeframe_version", None) or asset_version)
        command_id = self._make_command_id(
            symbol=effective_asset.symbol,
            command_type=command_type,
            asset_version=asset_version,
            request_id=request_id,
        )
        control_event_id = self._make_child_event_id("control", command_id)
        lifecycle_event_id = self._make_child_event_id("lifecycle", command_id)
        published_at = time()
        command_stream_id: str | None = None
        event_stream_id: str | None = None
        command_published = False
        event_published = False
        lifecycle_published = False
        deduplicated = False

        command = IngestionControlCommand(
            command_id=command_id,
            command_type=command_type,
            symbol=effective_asset.symbol,
            exchange=effective_asset.exchange,
            provider=effective_asset.provider,
            base_timeframe=effective_asset.base_timeframe,
            publish_timeframes=effective_asset.publish_timeframes,
            historical_backfill_days=effective_asset.historical_backfill_days,
            retention_days=effective_asset.retention_days,
            enabled=effective_asset.enabled,
            desired_state=_desired_state_value(effective_asset),
            request_id=request_id,
            asset_version=asset_version,
            timeframe_version=timeframe_version,
            requested_by=requested_by,
            reason=reason,
            requested_at=published_at,
        )
        event = IngestionControlEvent(
            event_id=control_event_id,
            event_type=IngestionEventType.COMMAND_ACCEPTED,
            command_id=command_id,
            command_type=command_type,
            symbol=effective_asset.symbol,
            request_id=request_id,
            asset_version=asset_version,
            timeframe_version=timeframe_version,
            requested_by=requested_by,
            detail={
                "enabled": effective_asset.enabled,
                "desired_state": _desired_state_value(effective_asset),
                "publish_timeframes": effective_asset.publish_timeframes,
            },
            emitted_at=published_at,
        )

        if self.valkey_client is not None:
            manifest_store = AssetManifestStore(
                self.valkey_client,
                lifecycle_stream_maxlen=self.lifecycle_stream_maxlen,
                lifecycle_stream_approximate=self.lifecycle_stream_approximate,
            )
            manifest_synced = False
            try:
                await manifest_store.sync_from_ingestion_asset(
                    effective_asset,
                    updated_at=published_at,
                    request_id=request_id,
                )
                manifest_synced = True
            except Exception as exc:
                logger.warning(
                    f"Failed to sync asset manifest for {asset.symbol}: {exc}",
                    exc_info=True,
                )
            try:
                command_published, command_stream_id = await self._publish_once(
                    kind="control",
                    identifier=command_id,
                    stream=INGESTION_CONTROL_STREAM,
                    payload=valkey_encode(command),
                    maxlen=self.command_stream_maxlen,
                    approximate=self.command_stream_approximate,
                )
                deduplicated = deduplicated or not command_published
            except Exception as exc:
                logger.warning(
                    f"Failed to publish ingestion control command for {asset.symbol}: {exc}",
                    exc_info=True,
                )

            try:
                event_published, event_stream_id = await self._publish_once(
                    kind="event",
                    identifier=control_event_id,
                    stream=INGESTION_EVENTS_STREAM,
                    payload=valkey_encode(event),
                    maxlen=self.event_stream_maxlen,
                    approximate=self.event_stream_approximate,
                )
                deduplicated = deduplicated or not event_published
            except Exception as exc:
                logger.warning(
                    f"Failed to publish ingestion control event for {asset.symbol}: {exc}",
                    exc_info=True,
                )
            if manifest_synced and self._should_publish_lifecycle_event(command_type, effective_asset):
                try:
                    lifecycle_published, _ = await self._publish_lifecycle_once(
                        manifest_store=manifest_store,
                        lifecycle_event_id=lifecycle_event_id,
                        command=command,
                        asset=effective_asset,
                        requested_by=requested_by,
                        reason=reason,
                        emitted_at=published_at,
                    )
                    deduplicated = deduplicated or not lifecycle_published
                except Exception as exc:
                    logger.warning(
                        f"Failed to publish asset lifecycle event for {asset.symbol}: {exc}",
                        exc_info=True,
                    )

        return IngestionControlResult(
            asset=effective_asset,
            command_id=command_id,
            command_type=command_type.value,
            request_id=request_id,
            asset_version=asset_version,
            timeframe_version=timeframe_version,
            command_published=command_published,
            event_published=event_published,
            lifecycle_published=lifecycle_published,
            deduplicated=deduplicated,
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

    @staticmethod
    def _make_command_id(
        *,
        symbol: str,
        command_type: IngestionCommandType,
        asset_version: int,
        request_id: str | None,
    ) -> str:
        raw = f"command|{str(symbol).upper().strip()}|{command_type.value}|{asset_version}|{request_id or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _make_child_event_id(kind: str, command_id: str) -> str:
        return hashlib.sha256(f"{kind}|{command_id}".encode("utf-8")).hexdigest()[:24]

    def _publish_dedup_key(self, kind: str, identifier: str) -> str:
        return f"{_PUBLISH_DEDUP_PREFIX}:{kind}:{identifier}"

    async def _publish_once(
        self,
        *,
        kind: str,
        identifier: str,
        stream: str,
        payload: dict[str, str],
        maxlen: int,
        approximate: bool,
    ) -> tuple[bool, str | None]:
        if self.valkey_client is None:
            return False, None
        marker_key = self._publish_dedup_key(kind, identifier)
        acquired = await self._acquire_publish_slot(marker_key)
        if not acquired:
            return False, None
        try:
            stream_id = await self.valkey_client.xadd(
                stream,
                payload,
                maxlen=maxlen,
                approximate=approximate,
            )
            return True, stream_id
        except Exception:
            await self._release_publish_slot(marker_key)
            raise

    async def _publish_lifecycle_once(
        self,
        *,
        manifest_store: AssetManifestStore,
        lifecycle_event_id: str,
        command: IngestionControlCommand,
        asset: IngestionAssetRecord,
        requested_by: str,
        reason: str | None,
        emitted_at: float,
    ) -> tuple[bool, str | None]:
        marker_key = self._publish_dedup_key("lifecycle", lifecycle_event_id)
        acquired = await self._acquire_publish_slot(marker_key)
        if not acquired:
            return False, None
        try:
            stream_id = await manifest_store.publish_lifecycle_event(
                asset=asset,
                command_type=command.command_type,
                requested_by=requested_by,
                reason=reason,
                emitted_at=emitted_at,
                event_id=lifecycle_event_id,
                command_id=command.command_id,
                request_id=command.request_id,
            )
            return True, stream_id
        except Exception:
            await self._release_publish_slot(marker_key)
            raise

    async def _acquire_publish_slot(self, key: str) -> bool:
        try:
            created = await self.valkey_client.set(
                key,
                "1",
                nx=True,
                ex=self.publish_dedup_ttl_seconds,
            )
        except TypeError:
            existing = await self.valkey_client.get(key)
            if existing:
                return False
            await self.valkey_client.set(key, "1")
            return True
        return bool(created)

    async def _release_publish_slot(self, key: str) -> None:
        try:
            await self.valkey_client.delete(key)
        except Exception:
            logger.warning("Failed to release publish dedup marker %s", key, exc_info=True)
