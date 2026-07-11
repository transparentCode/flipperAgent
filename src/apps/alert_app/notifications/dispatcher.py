from __future__ import annotations

import asyncio
from time import time
from typing import Any
from uuid import uuid4

from apps.alert_app.contracts import AlertDeliveryRecord, AlertIncidentRecord, AlertSilenceRule
from apps.alert_app.incidents.keys import route_counter_key
from apps.alert_app.notifications.transports import (
    AlertTransport,
    TelegramAlertTransport,
    WebhookAlertTransport,
)
from apps.alert_app.settings import create_alert_config_manager, route_configs_from_config
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component="ALERTING")


class AlertNotificationDispatcher:
    def __init__(
        self,
        *,
        redis_client: Any,
        repository: Any,
        incident_service: Any | None = None,
        config_manager: Any | None = None,
        transports: dict[str, AlertTransport] | None = None,
    ) -> None:
        self.redis_client = redis_client
        self.repository = repository
        self.incident_service = incident_service
        self.config_manager = create_alert_config_manager(config_manager)
        self.queue_maxsize = int(
            self.config_manager.get("alerts.notifications.queue_maxsize", 1000),
        )
        self.worker_count = int(
            self.config_manager.get("alerts.notifications.worker_count", 1),
        )
        self.queue: asyncio.Queue[tuple[AlertIncidentRecord, str, dict[str, Any]]] = asyncio.Queue(
            maxsize=self.queue_maxsize,
        )
        self.transports = transports or {
            "webhook": WebhookAlertTransport(),
            "telegram": TelegramAlertTransport(),
        }
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._worker_loop(index))
            for index in range(self.worker_count)
        ]

    async def stop(self) -> None:
        if not self._tasks:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def enqueue_incident(
        self,
        incident: AlertIncidentRecord,
        *,
        route_names: list[str],
    ) -> None:
        routes = route_configs_from_config(self.config_manager)
        silences = await self.repository.list_silences()
        for route_name in route_names:
            route_config = routes.get(route_name)
            if not route_config:
                continue
            if self._is_silenced(incident, silences):
                await self._record_delivery(
                    incident,
                    route_name=route_name,
                    transport=str(route_config.get("transport", "")),
                    destination=str(route_config.get("destination", "")),
                    status="silenced",
                    error=None,
                )
                continue
            if not await self._allow_route(route_name, route_config):
                await self._record_delivery(
                    incident,
                    route_name=route_name,
                    transport=str(route_config.get("transport", "")),
                    destination=str(route_config.get("destination", "")),
                    status="rate_limited",
                    error=None,
                )
                continue
            await self.queue.put((incident, route_name, route_config))

    async def _worker_loop(self, worker_index: int) -> None:
        while True:
            incident, route_name, route_config = await self.queue.get()
            transport_name = str(route_config.get("transport", "")).strip().lower()
            try:
                transport = self.transports.get(transport_name)
                if transport is None:
                    raise ValueError(f"Unknown transport: {transport_name}")
                await transport.send(
                    incident=incident,
                    route_name=route_name,
                    route_config=route_config,
                )
                await self._record_delivery(
                    incident,
                    route_name=route_name,
                    transport=transport_name,
                    destination=str(route_config.get("destination", "")),
                    status="sent",
                    error=None,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Notification dispatch failed for incident=%s route=%s: %s",
                    incident.incident_id,
                    route_name,
                    exc,
                    exc_info=True,
                )
                await self._record_delivery(
                    incident,
                    route_name=route_name,
                    transport=transport_name,
                    destination=str(route_config.get("destination", "")),
                    status="failed",
                    error=_format_exception(exc),
                )
            else:
                if self.incident_service is not None:
                    try:
                        await self.incident_service.mark_notified(
                            incident.incident_id,
                            notified_at=time(),
                        )
                    except Exception as mark_exc:
                        logger.warning(
                            "Failed to update last_notified_at for incident=%s route=%s: %s",
                            incident.incident_id,
                            route_name,
                            mark_exc,
                            exc_info=True,
                        )
            finally:
                self.queue.task_done()

    async def _allow_route(self, route_name: str, route_config: dict[str, Any]) -> bool:
        burst_limit = int(route_config.get("burst_limit", 20))
        window_seconds = int(route_config.get("burst_window_seconds", 300))
        bucket = int(time() // max(window_seconds, 1))
        key = route_counter_key(route_name, bucket)
        current = await self.redis_client.incr(key)
        if current == 1:
            await self.redis_client.expire(key, window_seconds)
        return int(current) <= burst_limit

    async def _record_delivery(
        self,
        incident: AlertIncidentRecord,
        *,
        route_name: str,
        transport: str,
        destination: str,
        status: str,
        error: str | None,
    ) -> None:
        record = AlertDeliveryRecord(
            delivery_id=str(uuid4()),
            incident_id=incident.incident_id,
            route_name=route_name,
            transport=transport,
            status=status,
            destination=destination,
            error=error,
            attempted_at=time(),
        )
        await self.repository.record_delivery(record)

    @staticmethod
    def _is_silenced(
        incident: AlertIncidentRecord,
        silences: list[AlertSilenceRule],
    ) -> bool:
        now_ts = time()
        for silence in silences:
            if silence.expires_at is not None and silence.expires_at < now_ts:
                continue
            if _matches_silence(incident, silence.match):
                return True
        return False


def _matches_silence(incident: AlertIncidentRecord, match: dict[str, str]) -> bool:
    if not match:
        return False
    incident_values = {
        "asset": incident.asset or "",
        "timeframe": incident.timeframe or "",
        "source_app": incident.source_app.value,
        "severity": incident.severity.value,
        "event_type": incident.event_type.value,
    }
    for key, expected in match.items():
        if incident_values.get(str(key), "") != str(expected):
            return False
    return True


def _format_exception(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
