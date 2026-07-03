from __future__ import annotations

from fastapi.testclient import TestClient

from apps.alert_app.api.app import create_app


class _FakeService:
    async def health(self) -> dict:
        return {"status": "ok", "db_available": True, "valkey_available": True}

    async def summary(self) -> dict:
        return {"open_count": 1, "acked_count": 0, "silenced_count": 0, "resolved_count": 0}

    async def incidents(self, **_: object) -> dict:
        return {"status": "ok", "count": 1, "items": [{"incident_id": "inc_1"}]}

    async def incident_detail(self, incident_id: str) -> dict:
        return {"status": "ok", "incident": {"incident_id": incident_id, "state": "open"}}

    async def routes(self) -> dict:
        return {"status": "ok", "count": 1, "items": {"system_alerts": {"transport": "webhook"}}}

    async def silences(self) -> dict:
        return {"status": "no_data", "count": 0, "items": []}

    async def notifications(self, *, limit: int = 100) -> dict:
        return {"status": "ok", "count": 1, "counts": {"sent": 1}, "items": [{"limit": limit}]}

    async def acknowledge_incident(self, incident_id: str) -> dict:
        return {"status": "ok", "incident": {"incident_id": incident_id, "state": "acked"}}

    async def resolve_incident(self, incident_id: str) -> dict:
        return {"status": "ok", "incident": {"incident_id": incident_id, "state": "resolved"}}

    async def create_silence(self, **_: object) -> dict:
        return {"status": "ok", "silence": {"silence_id": "sil_1"}}

    async def delete_silence(self, silence_id: str) -> dict:
        return {"status": "ok", "silence_id": silence_id}


def test_alert_api_endpoints() -> None:
    client = TestClient(create_app(observability_service=_FakeService()))
    assert client.get("/alerts/health").status_code == 200
    assert client.get("/alerts/summary").json()["open_count"] == 1
    assert client.get("/alerts/incidents").json()["count"] == 1
    assert client.get("/alerts/incidents/inc_1").json()["incident"]["incident_id"] == "inc_1"
    assert client.get("/alerts/routes").json()["count"] == 1
    assert client.get("/alerts/silences").json()["count"] == 0
    assert client.get("/alerts/notifications").json()["count"] == 1
    assert client.post("/alerts/incidents/inc_1/ack").json()["incident"]["state"] == "acked"
    assert client.post("/alerts/incidents/inc_1/resolve").json()["incident"]["state"] == "resolved"
    assert client.post("/alerts/silences", json={"match": {"asset": "BTCUSDT"}}).json()["status"] == "ok"
    assert client.delete("/alerts/silences/sil_1").json()["status"] == "ok"
