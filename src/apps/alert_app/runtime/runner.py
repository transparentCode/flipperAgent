from __future__ import annotations

import asyncio
from typing import Any

from apps.alert_app.incidents import (
    AlertIncidentRepository,
    AlertIncidentService,
    AlertIncidentStore,
)
from apps.alert_app.notifications import AlertNotificationDispatcher
from apps.alert_app.runtime.consumer import AlertEventConsumer
from apps.alert_app.runtime.reconciler import AlertFreshnessReconciler
from apps.alert_app.settings import AlertAppSettings
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component="ALERTING")


class AlertRuntimeRunner:
    def __init__(
        self,
        *,
        settings: AlertAppSettings,
        redis_client: Any,
        db_pool: Any,
        incident_service: AlertIncidentService | None = None,
        config_manager: Any | None = None,
    ) -> None:
        self.settings = settings
        self.redis_client = redis_client
        self.db_pool = db_pool
        self.incident_service = incident_service or AlertIncidentService(
            AlertIncidentRepository(db_pool),
            AlertIncidentStore(
                redis_client,
                dedupe_ttl_seconds=settings.dedupe_ttl_seconds,
                open_state_ttl_seconds=settings.open_state_ttl_seconds,
                hot_summary_ttl_seconds=settings.hot_summary_ttl_seconds,
            ),
            renotify_seconds=settings.renotify_seconds,
        )
        self.repository = AlertIncidentRepository(db_pool)
        self.notification_dispatcher = AlertNotificationDispatcher(
            redis_client=redis_client,
            repository=self.repository,
            incident_service=self.incident_service,
            config_manager=config_manager,
        )
        self.consumer = AlertEventConsumer(
            redis_client=redis_client,
            settings=settings,
            incident_service=self.incident_service,
            notification_dispatcher=self.notification_dispatcher,
            config_manager=config_manager,
        )
        self.reconciler = AlertFreshnessReconciler(
            redis_client=redis_client,
            incident_service=self.incident_service,
            notification_dispatcher=self.notification_dispatcher,
            config_manager=config_manager,
        )
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []

    async def run(self) -> None:
        await self.consumer.ensure_groups()
        await self.notification_dispatcher.start()
        logger.info(
            "alert_app runtime started with lifecycle stream=%s",
            self.settings.lifecycle_stream,
        )
        self._tasks = [
            asyncio.create_task(self.consumer.watch_lifecycle()),
            asyncio.create_task(self.consumer.watch_execution_failures()),
            asyncio.create_task(self.reconciler.run()),
        ]
        stop_task = asyncio.create_task(self._stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                [*self._tasks, stop_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop_task in done:
                return
            for task in done:
                if task.cancelled():
                    continue
                error = task.exception()
                if error is not None:
                    raise error
        finally:
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            await self.stop()

    async def stop(self) -> None:
        self._stop_event.set()
        if not self._tasks:
            await self.notification_dispatcher.stop()
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        await self.notification_dispatcher.stop()
