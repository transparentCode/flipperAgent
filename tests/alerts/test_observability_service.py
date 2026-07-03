from __future__ import annotations

import pytest

from apps.alert_app.contracts import (
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
    AlertSummary,
)
from apps.alert_app.observability.service import AlertObservabilityService


class _FakeConn:
    async def fetchrow(self, _query: str):
        return {"ok": 1}


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


class _FakeRepository:
    def __init__(self) -> None:
        self.saved_silences = []
        self.deleted_silence_ids = []

    async def list_incidents(self, **_: object):
        return []

    async def get_incident(self, incident_id: str):
        return AlertIncidentRecord(
            incident_id=incident_id,
            dedupe_key="dedupe",
            event_type="execution_failure",
            source_app=AlertSourceApp.EXECUTION,
            source_component="execution_worker",
            severity=AlertSeverity.CRITICAL,
            state=AlertIncidentState.OPEN,
            title="detail",
            summary="detail",
            first_seen_at=1.0,
            last_seen_at=1.0,
            updated_at=1.0,
        )

    async def summary(self):
        return AlertSummary(open_count=2)

    async def list_silences(self):
        return []

    async def save_silence(self, silence):
        self.saved_silences.append(silence)
        return silence

    async def delete_silence(self, silence_id: str):
        self.deleted_silence_ids.append(silence_id)
        return True


class _FakeConfig:
    def get(self, key: str, default=None):
        if key == "alerts.routes":
            return {
                "ops_alerts": {
                    "enabled": True,
                    "transport": "telegram",
                    "bot_token": "secret-token",
                    "chat_id": "-100",
                }
            }
        return default


class _FakeStore:
    def __init__(self) -> None:
        self.summary = None

    async def read_hot_summary(self):
        return None

    async def write_hot_summary(self, summary):
        self.summary = summary


class _FakeIncidentService:
    async def get_incident(self, incident_id: str):
        return AlertIncidentRecord(
            incident_id=incident_id,
            dedupe_key="dedupe",
            event_type="execution_failure",
            source_app=AlertSourceApp.EXECUTION,
            source_component="execution_worker",
            severity=AlertSeverity.CRITICAL,
            state=AlertIncidentState.OPEN,
            title="detail",
            summary="detail",
            first_seen_at=1.0,
            last_seen_at=1.0,
            updated_at=1.0,
        )

    async def acknowledge(self, incident_id: str):
        return AlertIncidentRecord(
            incident_id=incident_id,
            dedupe_key="dedupe",
            event_type="execution_failure",
            source_app=AlertSourceApp.EXECUTION,
            source_component="execution_worker",
            severity=AlertSeverity.CRITICAL,
            state=AlertIncidentState.ACKED,
            title="acked",
            summary="acked",
            first_seen_at=1.0,
            last_seen_at=2.0,
            updated_at=2.0,
            acknowledged_at=2.0,
        )

    async def resolve(self, incident_id: str):
        return AlertIncidentRecord(
            incident_id=incident_id,
            dedupe_key="dedupe",
            event_type="execution_failure",
            source_app=AlertSourceApp.EXECUTION,
            source_component="execution_worker",
            severity=AlertSeverity.CRITICAL,
            state=AlertIncidentState.RESOLVED,
            title="resolved",
            summary="resolved",
            first_seen_at=1.0,
            last_seen_at=3.0,
            updated_at=3.0,
            resolved_at=3.0,
        )


@pytest.mark.asyncio
async def test_observability_service_ack_and_silence() -> None:
    repository = _FakeRepository()
    service = AlertObservabilityService(
        _FakePool(),
        None,
        repository=repository,
        store=_FakeStore(),
        incident_service=_FakeIncidentService(),
    )

    ack = await service.acknowledge_incident("inc_1")
    silence = await service.create_silence(
        match={"asset": "BTCUSDT"},
        reason="maintenance",
        created_by="tester",
    )

    assert ack["incident"]["state"] == "acked"
    assert silence["status"] == "ok"
    assert repository.saved_silences[0].match["asset"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_observability_service_detail_resolve_and_delete_silence() -> None:
    repository = _FakeRepository()
    service = AlertObservabilityService(
        _FakePool(),
        None,
        repository=repository,
        store=_FakeStore(),
        incident_service=_FakeIncidentService(),
    )

    detail = await service.incident_detail("inc_2")
    resolved = await service.resolve_incident("inc_2")
    deleted = await service.delete_silence("sil_2")

    assert detail["incident"]["incident_id"] == "inc_2"
    assert resolved["incident"]["state"] == "resolved"
    assert deleted["status"] == "ok"
    assert repository.deleted_silence_ids == ["sil_2"]


@pytest.mark.asyncio
async def test_observability_service_redacts_route_secrets() -> None:
    service = AlertObservabilityService(
        _FakePool(),
        None,
        repository=_FakeRepository(),
        store=_FakeStore(),
        incident_service=_FakeIncidentService(),
        config_mgr=_FakeConfig(),
    )

    routes = await service.routes()

    assert routes["items"]["ops_alerts"]["bot_token"] == "[redacted]"
    assert routes["items"]["ops_alerts"]["chat_id"] == "-100"
