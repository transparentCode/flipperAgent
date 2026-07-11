from __future__ import annotations

import pytest

from apps.alert_app.contracts import (
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
)
from apps.alert_app.notifications.dispatcher import AlertNotificationDispatcher


class _FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        value = self.counters.get(key, 0) + 1
        self.counters[key] = value
        return value

    async def expire(self, key: str, ttl: int) -> bool:
        return True


class _FakeRepository:
    def __init__(self) -> None:
        self.deliveries = []

    async def list_silences(self):
        return []

    async def record_delivery(self, record):
        self.deliveries.append(record)
        return record


class _FakeIncidentService:
    def __init__(self) -> None:
        self.notified: list[tuple[str, float]] = []

    async def mark_notified(self, incident_id: str, *, notified_at: float) -> None:
        self.notified.append((incident_id, notified_at))


class _FailingMarkNotifiedIncidentService:
    async def mark_notified(self, incident_id: str, *, notified_at: float) -> None:
        raise RuntimeError("store down")


class _FakeTransport:
    def __init__(self) -> None:
        self.calls = []

    async def send(self, *, incident, route_name, route_config):
        self.calls.append((incident.incident_id, route_name, route_config["destination"]))


class _FailingTransport:
    async def send(self, *, incident, route_name, route_config):
        raise TimeoutError()


class _FakeConfig:
    def get(self, key: str, default=None):
        values = {
            "alerts.notifications.queue_maxsize": 100,
            "alerts.notifications.worker_count": 1,
            "alerts.routes": {
                "system_alerts": {
                    "enabled": True,
                    "transport": "webhook",
                    "destination": "http://example.invalid",
                    "burst_limit": 2,
                    "burst_window_seconds": 60,
                }
            },
        }
        return values.get(key, default)


def _incident() -> AlertIncidentRecord:
    return AlertIncidentRecord(
        incident_id="inc_1",
        dedupe_key="dedupe_1",
        event_type="execution_failure",
        source_app=AlertSourceApp.EXECUTION,
        source_component="execution_worker",
        severity=AlertSeverity.CRITICAL,
        state=AlertIncidentState.OPEN,
        asset="BTCUSDT",
        timeframe="1h",
        title="Execution failed",
        summary="execution failed",
        first_seen_at=1.0,
        last_seen_at=1.0,
        last_notified_at=1.0,
        updated_at=1.0,
    )


@pytest.mark.asyncio
async def test_dispatcher_enqueues_and_sends() -> None:
    transport = _FakeTransport()
    repository = _FakeRepository()
    incident_service = _FakeIncidentService()
    dispatcher = AlertNotificationDispatcher(
        redis_client=_FakeRedis(),
        repository=repository,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        transports={"webhook": transport},
    )
    await dispatcher.start()
    try:
        await dispatcher.enqueue_incident(_incident(), route_names=["system_alerts"])
        await dispatcher.queue.join()
    finally:
        await dispatcher.stop()

    assert transport.calls == [("inc_1", "system_alerts", "http://example.invalid")]
    assert repository.deliveries[0].status == "sent"
    assert len(incident_service.notified) == 1
    assert incident_service.notified[0][0] == "inc_1"


@pytest.mark.asyncio
async def test_dispatcher_rate_limits_routes() -> None:
    transport = _FakeTransport()
    repository = _FakeRepository()
    incident_service = _FakeIncidentService()
    dispatcher = AlertNotificationDispatcher(
        redis_client=_FakeRedis(),
        repository=repository,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        transports={"webhook": transport},
    )
    await dispatcher.start()
    try:
        await dispatcher.enqueue_incident(_incident(), route_names=["system_alerts"])
        await dispatcher.enqueue_incident(
            _incident().model_copy(update={"incident_id": "inc_2"}),
            route_names=["system_alerts"],
        )
        await dispatcher.enqueue_incident(
            _incident().model_copy(update={"incident_id": "inc_3"}),
            route_names=["system_alerts"],
        )
        await dispatcher.queue.join()
    finally:
        await dispatcher.stop()

    statuses = [delivery.status for delivery in repository.deliveries]
    assert statuses.count("sent") == 2
    assert "rate_limited" in statuses
    assert len(incident_service.notified) == 2


@pytest.mark.asyncio
async def test_dispatcher_records_exception_type_when_message_empty() -> None:
    repository = _FakeRepository()
    incident_service = _FakeIncidentService()
    dispatcher = AlertNotificationDispatcher(
        redis_client=_FakeRedis(),
        repository=repository,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        transports={"webhook": _FailingTransport()},
    )
    await dispatcher.start()
    try:
        await dispatcher.enqueue_incident(_incident(), route_names=["system_alerts"])
        await dispatcher.queue.join()
    finally:
        await dispatcher.stop()

    assert repository.deliveries[0].status == "failed"
    assert repository.deliveries[0].error == "TimeoutError"
    assert len(incident_service.notified) == 0


@pytest.mark.asyncio
async def test_dispatcher_records_sent_not_failed_when_mark_notified_fails() -> None:
    transport = _FakeTransport()
    repository = _FakeRepository()
    incident_service = _FailingMarkNotifiedIncidentService()
    dispatcher = AlertNotificationDispatcher(
        redis_client=_FakeRedis(),
        repository=repository,
        incident_service=incident_service,
        config_manager=_FakeConfig(),
        transports={"webhook": transport},
    )
    await dispatcher.start()
    try:
        await dispatcher.enqueue_incident(_incident(), route_names=["system_alerts"])
        await dispatcher.queue.join()
    finally:
        await dispatcher.stop()

    assert transport.calls == [("inc_1", "system_alerts", "http://example.invalid")]
    assert len(repository.deliveries) == 1
    assert repository.deliveries[0].status == "sent"
    assert repository.deliveries[0].error is None
