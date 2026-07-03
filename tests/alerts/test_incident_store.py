from __future__ import annotations

import pytest

from apps.alert_app.contracts import (
    AlertEventType,
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
)
from apps.alert_app.incidents.store import AlertIncidentStore


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


def _incident() -> AlertIncidentRecord:
    return AlertIncidentRecord(
        incident_id="inc_1",
        dedupe_key="dedupe_1",
        event_type=AlertEventType.EXECUTION_FAILURE,
        source_app=AlertSourceApp.EXECUTION,
        source_component="execution_worker",
        severity=AlertSeverity.CRITICAL,
        state=AlertIncidentState.OPEN,
        asset="BTCUSDT",
        timeframe="1h",
        title="Execution failed",
        summary="execution failure for BTCUSDT",
        detail={"reason": "timeout"},
        route_names=["system_alerts"],
        first_seen_at=1.0,
        last_seen_at=2.0,
        updated_at=2.0,
    )


@pytest.mark.asyncio
async def test_alert_incident_store_roundtrip() -> None:
    store = AlertIncidentStore(_FakeRedis())
    incident = _incident()

    await store.write(incident)
    saved = await store.read(incident.incident_id)

    assert saved is not None
    assert saved.incident_id == incident.incident_id
    assert saved.detail["reason"] == "timeout"
    assert await store.incident_id_for_dedupe("dedupe_1") == "inc_1"
    assert await store.list_open_incident_ids() == ["inc_1"]
