from __future__ import annotations

import asyncio
from typing import Any

from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from apps.alert_app.incidents import AlertIncidentService
from apps.alert_app.notifications import AlertNotificationDispatcher
from apps.alert_app.rules import resolve_routes_for_event
from apps.alert_app.runtime.normalizers import (
    normalize_execution_failure_event,
    normalize_ingestion_runtime_event,
    normalize_lifecycle_event,
)
from apps.alert_app.settings import AlertAppSettings, create_alert_config_manager
from apps.execution_app.state import ExecutionFailureEvent
from libs.common.asset_manifest import ASSET_LIFECYCLE_STREAM, AssetLifecycleEvent, AssetManifestStore
from libs.common.lifecycle_dedup import mark_lifecycle_event_processed
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import ensure_consumer_group
from libs.contracts.ingestion import IngestionRuntimeEvent
from libs.contracts.serialization import valkey_decode

logger = bind_logger(__name__, system_component="ALERTING")


class AlertEventConsumer:
    def __init__(
        self,
        *,
        redis_client: Any,
        settings: AlertAppSettings,
        incident_service: AlertIncidentService,
        notification_dispatcher: AlertNotificationDispatcher | None = None,
        config_manager: Any | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.settings = settings
        self.incident_service = incident_service
        self.notification_dispatcher = notification_dispatcher
        self.config_manager = create_alert_config_manager(config_manager)
        self.manifest_store = AssetManifestStore(redis_client)
        self._known_execution_streams: set[str] = set()

    async def ensure_groups(self) -> None:
        await ensure_consumer_group(
            self.redis_client,
            self.settings.lifecycle_stream,
            self.settings.consumer_group,
            start_id="$",
        )
        await ensure_consumer_group(
            self.redis_client,
            self.settings.ingestion_events_stream,
            self.settings.consumer_group,
            start_id="$",
        )
        for stream in await self._refresh_execution_failure_streams():
            await ensure_consumer_group(
                self.redis_client,
                stream,
                self.settings.consumer_group,
                start_id="$",
            )

    async def watch_lifecycle(self) -> None:
        consumer_name = f"{self.settings.consumer_name_prefix}_lifecycle"
        streams = {self.settings.lifecycle_stream: ">"}
        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.settings.consumer_group,
                    consumer_name,
                    streams,
                    count=25,
                    block=self.settings.poll_block_ms,
                )
                if not response:
                    continue
                for _stream_name, messages in response:
                    for message_id, payload in messages:
                        event = valkey_decode(payload, AssetLifecycleEvent)
                        if not await mark_lifecycle_event_processed(
                            self.redis_client,
                            consumer_namespace="alert",
                            event_id=event.event_id,
                        ):
                            await self.redis_client.xack(
                                ASSET_LIFECYCLE_STREAM,
                                self.settings.consumer_group,
                                message_id,
                            )
                            continue
                        normalized = normalize_lifecycle_event(event)
                        routes = resolve_routes_for_event(
                            normalized,
                            config_manager=self.config_manager,
                        )
                        incident, should_notify = await self.incident_service.record_event(
                            normalized,
                            route_names=routes,
                        )
                        if should_notify and self.notification_dispatcher is not None:
                            await self.notification_dispatcher.enqueue_incident(
                                incident,
                                route_names=routes,
                            )
                        await self.redis_client.xack(
                            self.settings.lifecycle_stream,
                            self.settings.consumer_group,
                            message_id,
                        )
            except asyncio.CancelledError:
                raise
            except ValkeyTimeoutError:
                logger.warning("Alert lifecycle consumer timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning("Alert lifecycle consumer failed: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def watch_ingestion_events(self) -> None:
        consumer_name = f"{self.settings.consumer_name_prefix}_ingestion"
        streams = {self.settings.ingestion_events_stream: ">"}
        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.settings.consumer_group,
                    consumer_name,
                    streams,
                    count=25,
                    block=self.settings.poll_block_ms,
                )
                if not response:
                    continue
                for _stream_name, messages in response:
                    for message_id, payload in messages:
                        event = valkey_decode(payload, IngestionRuntimeEvent)
                        normalized = normalize_ingestion_runtime_event(event)
                        routes = resolve_routes_for_event(
                            normalized,
                            config_manager=self.config_manager,
                        )
                        incident, should_notify = await self.incident_service.record_event(
                            normalized,
                            route_names=routes,
                        )
                        if should_notify and self.notification_dispatcher is not None:
                            await self.notification_dispatcher.enqueue_incident(
                                incident,
                                route_names=routes,
                            )
                        await self.redis_client.xack(
                            self.settings.ingestion_events_stream,
                            self.settings.consumer_group,
                            message_id,
                        )
            except asyncio.CancelledError:
                raise
            except ValkeyTimeoutError:
                logger.warning("Alert ingestion consumer timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning("Alert ingestion consumer failed: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def watch_execution_failures(self) -> None:
        consumer_name = f"{self.settings.consumer_name_prefix}_execution"
        while True:
            try:
                streams = {
                    stream: ">"
                    for stream in await self._refresh_execution_failure_streams()
                }
                if not streams:
                    await asyncio.sleep(self.settings.idle_sleep_seconds)
                    continue
                response = await self.redis_client.xreadgroup(
                    self.settings.consumer_group,
                    consumer_name,
                    streams,
                    count=25,
                    block=self.settings.poll_block_ms,
                )
                if not response:
                    continue
                for stream_name, messages in response:
                    for message_id, payload in messages:
                        event = valkey_decode(payload, ExecutionFailureEvent)
                        normalized = normalize_execution_failure_event(event)
                        routes = resolve_routes_for_event(
                            normalized,
                            config_manager=self.config_manager,
                        )
                        incident, should_notify = await self.incident_service.record_event(
                            normalized,
                            route_names=routes,
                        )
                        if should_notify and self.notification_dispatcher is not None:
                            await self.notification_dispatcher.enqueue_incident(
                                incident,
                                route_names=routes,
                            )
                        await self.redis_client.xack(
                            stream_name,
                            self.settings.consumer_group,
                            message_id,
                        )
            except asyncio.CancelledError:
                raise
            except ValkeyTimeoutError:
                logger.warning("Alert execution-failure consumer timed out; retrying.")
                await asyncio.sleep(1)
            except Exception as exc:
                logger.warning(
                    "Alert execution-failure consumer failed: %s",
                    exc,
                    exc_info=True,
                )
                await asyncio.sleep(1)

    async def _refresh_execution_failure_streams(self) -> list[str]:
        manifests = await self.manifest_store.list_assets()
        discovered: list[str] = []
        seen: set[str] = set()

        def _add_stream(value: str) -> None:
            normalized = str(value).strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            discovered.append(normalized)

        streams: list[str] = []
        for manifest in manifests:
            stream = f"{self.settings.execution_failure_prefix}{manifest.symbol}"
            _add_stream(stream)
        scan_iter = getattr(self.redis_client, "scan_iter", None)
        if callable(scan_iter):
            pattern = f"{self.settings.execution_failure_prefix}*"
            async for raw_key in scan_iter(match=pattern):
                key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key)
                _add_stream(key)

        streams.extend(discovered)
        for stream in streams:
            if stream not in self._known_execution_streams:
                await ensure_consumer_group(
                    self.redis_client,
                    stream,
                    self.settings.consumer_group,
                    start_id="$",
                )
                self._known_execution_streams.add(stream)
        return streams
