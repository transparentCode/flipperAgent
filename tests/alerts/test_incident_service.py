from __future__ import annotations

import pytest

from apps.alert_app.contracts import (
    AlertEventType,
    AlertSummary,
    AlertIncidentRecord,
    AlertSeverity,
    AlertSourceApp,
    NormalizedAlertEvent,
)
from apps.alert_app.incidents.service import AlertIncidentService
from apps.alert_app.incidents.store import AlertIncidentStore


class _FakeRepository:
    def __init__(self) -> None:
        self.items: dict[str, AlertIncidentRecord] = {}

    async def get_incident(self, incident_id: str) -> AlertIncidentRecord | None:
        return self.items.get(incident_id)

    async def get_by_dedupe_key(self, dedupe_key: str) -> AlertIncidentRecord | None:
        for incident in self.items.values():
            if incident.dedupe_key == dedupe_key:
                return incident
        return None

    async def upsert_incident(self, incident: AlertIncidentRecord) -> AlertIncidentRecord:
        self.items[incident.incident_id] = incident
        return incident

    async def summary(self):
        open_count = sum(1 for incident in self.items.values() if incident.state.value == "open")
        return AlertSummary(open_count=open_count)


class _FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes[key] = dict(mapping)
        return 1

    async def expire(self, key: str, ttl: int) -> bool:
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def sadd(self, key: str, *values: str) -> int:
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    async def srem(self, key: str, *values: str) -> int:
        existing = self.sets.setdefault(key, set())
        for value in values:
            existing.discard(value)
        return len(values)

    async def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    async def delete(self, key: str) -> int:
        self.hashes.pop(key, None)
        self.values.pop(key, None)
        self.sets.pop(key, None)
        return 1


def _event(
    *,
    event_id: str = "evt_1",
    dedupe_key: str = "dedupe_1",
    recovery_key: str | None = None,
    title: str = "Execution failed",
    detail: dict | None = None,
    emitted_at: float = 1.0,
) -> NormalizedAlertEvent:
    return NormalizedAlertEvent(
        event_id=event_id,
        event_type=AlertEventType.EXECUTION_FAILURE if recovery_key is None else AlertEventType.RECOVERY,
        source_app=AlertSourceApp.EXECUTION,
        source_component="execution_worker",
        severity=AlertSeverity.CRITICAL,
        asset="BTCUSDT",
        timeframe="1h",
        title=title,
        summary="execution failure",
        detail=detail if detail is not None else {"reason": "timeout"},
        dedupe_key=dedupe_key,
        recovery_key=recovery_key,
        emitted_at=emitted_at,
    )


@pytest.mark.asyncio
async def test_record_event_opens_and_updates_incident() -> None:
    repository = _FakeRepository()
    store = AlertIncidentStore(_FakeRedis())
    service = AlertIncidentService(repository, store, renotify_seconds=10)

    created, should_notify = await service.record_event(_event(), route_names=["system_alerts"])
    await service.mark_notified(created.incident_id, notified_at=1.0)
    updated, should_renotify = await service.record_event(
        _event(event_id="evt_2", emitted_at=5.0),
        route_names=["system_alerts"],
    )

    assert should_notify is True
    assert created.occurrence_count == 1
    assert created.last_notified_at is None
    assert should_renotify is False
    assert updated.occurrence_count == 2
    assert updated.last_notified_at == 1.0


@pytest.mark.asyncio
async def test_record_event_advances_last_notified_only_via_mark_notified() -> None:
    repository = _FakeRepository()
    store = AlertIncidentStore(_FakeRedis())
    service = AlertIncidentService(repository, store, renotify_seconds=10)

    created, should_notify = await service.record_event(_event(), route_names=["system_alerts"])
    assert should_notify is True
    assert created.last_notified_at is None

    await service.mark_notified(created.incident_id, notified_at=1.0)

    updated, should_renotify = await service.record_event(
        _event(event_id="evt_2", emitted_at=5.0),
        route_names=["system_alerts"],
    )
    assert should_renotify is False
    assert updated.last_notified_at == 1.0

    renotified, should_renotify = await service.record_event(
        _event(event_id="evt_3", emitted_at=12.0),
        route_names=["system_alerts"],
    )
    assert should_renotify is True
    assert renotified.last_notified_at == 1.0


@pytest.mark.asyncio
async def test_record_event_resolves_matching_incident() -> None:
    repository = _FakeRepository()
    store = AlertIncidentStore(_FakeRedis())
    service = AlertIncidentService(repository, store, renotify_seconds=10)

    created, _ = await service.record_event(
        _event(detail={"error": "timeout", "context": "old"}),
        route_names=["system_alerts"],
    )
    resolved, _ = await service.record_event(
        _event(
            event_id="evt_3",
            dedupe_key="recovery_evt",
            recovery_key="dedupe_1",
            emitted_at=8.0,
            title="Execution recovered",
            detail={"status": "recovered"},
        ),
        route_names=["system_alerts"],
    )

    assert created.incident_id == resolved.incident_id
    assert resolved.state.value == "resolved"
    assert resolved.title == "Execution recovered"
    assert resolved.detail == {"status": "recovered"}


@pytest.mark.asyncio
async def test_resolve_and_get_incident() -> None:
    repository = _FakeRepository()
    store = AlertIncidentStore(_FakeRedis())
    service = AlertIncidentService(repository, store, renotify_seconds=10)

    created, _ = await service.record_event(_event(), route_names=["system_alerts"])
    fetched = await service.get_incident(created.incident_id)
    resolved = await service.resolve(created.incident_id, resolved_at=9.0)

    assert fetched is not None
    assert fetched.incident_id == created.incident_id
    assert resolved is not None
    assert resolved.state.value == "resolved"
    assert resolved.resolved_at == 9.0
