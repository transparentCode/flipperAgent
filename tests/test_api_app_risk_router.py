from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api_app.routers import risk as risk_router


class _FakeValkey:
    async def aclose(self) -> None:
        return None


class _FakeService:
    def __init__(self, db_pool, redis_client, config_mgr=None, manifest_store=None):
        self.db_pool = db_pool
        self.redis_client = redis_client

    async def health(self):
        return {"status": "ok", "db_available": True, "valkey_available": True}

    async def summary(self):
        return {"account": {"status": "ok"}, "orders": {"status": "ok"}, "positions": {"status": "ok"}}

    async def latest_orders(self, *, assets=None):
        assert assets == ["BTCUSDT", "ETHUSDT"]
        return {"status": "ok", "count": 2, "items": [{"asset": "BTCUSDT"}, {"asset": "ETHUSDT"}]}

    async def account_snapshot(self):
        return {"status": "ok", "snapshot": {"equity": 100.0}}

    async def open_positions(self, *, asset=None):
        assert asset == "BTCUSDT"
        return {"status": "ok", "count": 1, "positions": [{"asset": asset}]}

    async def status(self):
        return {"status": "ok", "count": 1, "assets": [{"asset": "BTCUSDT"}]}


class _ErrorService(_FakeService):
    async def account_snapshot(self):
        return {"status": "error", "error": "db unavailable"}


def test_api_app_risk_router_routes(monkeypatch) -> None:
    async def fake_create_valkey_client(config_mgr):
        return _FakeValkey()

    monkeypatch.setattr(risk_router, "create_valkey_client", fake_create_valkey_client)
    monkeypatch.setattr(risk_router, "RiskObservabilityService", _FakeService)
    monkeypatch.setattr(risk_router.DBPoolManager, "get_reader_pool", lambda: object())

    app = FastAPI()
    app.include_router(risk_router.router)
    client = TestClient(app)

    assert client.get("/risk/health").status_code == 200
    assert client.get("/risk/summary").status_code == 200
    latest = client.get("/risk/latest", params=[("assets", "BTCUSDT"), ("assets", "ETHUSDT")])
    assert latest.status_code == 200
    assert latest.json()["count"] == 2
    account = client.get("/risk/account")
    assert account.status_code == 200
    assert account.json()["snapshot"]["equity"] == 100.0
    positions = client.get("/risk/positions/open", params={"asset": "BTCUSDT"})
    assert positions.status_code == 200
    assert positions.json()["positions"][0]["asset"] == "BTCUSDT"
    status = client.get("/risk/status")
    assert status.status_code == 200
    assert status.json()["assets"][0]["asset"] == "BTCUSDT"


def test_api_app_risk_router_returns_503_on_service_error(monkeypatch) -> None:
    async def fake_create_valkey_client(config_mgr):
        return _FakeValkey()

    monkeypatch.setattr(risk_router, "create_valkey_client", fake_create_valkey_client)
    monkeypatch.setattr(risk_router, "RiskObservabilityService", _ErrorService)
    monkeypatch.setattr(risk_router.DBPoolManager, "get_reader_pool", lambda: object())

    app = FastAPI()
    app.include_router(risk_router.router)
    client = TestClient(app)

    response = client.get("/risk/account")
    assert response.status_code == 503
    assert response.json()["detail"] == "db unavailable"
