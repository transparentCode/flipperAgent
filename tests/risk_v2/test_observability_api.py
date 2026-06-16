from __future__ import annotations

import time

from fastapi.testclient import TestClient

from apps.risk_app.api.app import create_app
from apps.risk_app.observability.service import RiskObservabilityService
from libs.common.asset_manifest import AssetManifest
from libs.contracts.execution import OrderExecutionRequest
from libs.contracts.serialization import valkey_encode


class _FakeRedis:
    def __init__(self, streams=None) -> None:
        self.streams = streams or {}

    async def ping(self) -> bool:
        return True

    async def xrevrange(self, stream: str, count: int = 1):
        return list(self.streams.get(stream, []))[:count]


class _FakeConn:
    def __init__(self, fetchrow_results=None, fetch_results=None):
        self.fetchrow_results = list(fetchrow_results or [])
        self.fetch_results = list(fetch_results or [])

    async def fetchrow(self, query, *args):
        if "SELECT 1" in query:
            return {"ok": 1}
        if self.fetchrow_results:
            return self.fetchrow_results.pop(0)
        return None

    async def fetch(self, query, *args):
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []


class _AcquireCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        return None


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _AcquireCtx(self.conn)


class _FakeManifestStore:
    def __init__(self, manifests):
        self._manifests = list(manifests)

    async def list_assets(self):
        return list(self._manifests)


def test_risk_observability_service_health_summary_and_status() -> None:
    now = time.time()
    order = OrderExecutionRequest(
        asset="BTCUSDT",
        side="buy",
        size=0.25,
        order_type="market",
        timestamp=now - 2,
        requested_price=64000.0,
        idempotency_key="risk-1",
        stop_loss_price=62000.0,
        take_profit_price=68000.0,
        model_name="Trend",
        source_timeframe="1h",
    )
    conn = _FakeConn(
        fetchrow_results=[
            {
                "timestamp": now - 5,
                "balance": 10000.0,
                "equity": 10025.0,
                "unrealized_pnl": 15.0,
                "realized_pnl": 10.0,
                "drawdown_pct": 0.5,
                "peak_equity": 10100.0,
                "open_position_count": 1,
                "daily_pnl": 4.0,
            },
            {
                "timestamp": now - 5,
                "balance": 10000.0,
                "equity": 10025.0,
                "unrealized_pnl": 15.0,
                "realized_pnl": 10.0,
                "drawdown_pct": 0.5,
                "peak_equity": 10100.0,
                "open_position_count": 1,
                "daily_pnl": 4.0,
            },
        ],
        fetch_results=[
            [
                {
                    "asset": "BTCUSDT",
                    "direction": 1,
                    "entry_price": 63000.0,
                    "current_price": 64000.0,
                    "size": 0.25,
                    "unrealized_pnl": 250.0,
                    "entry_timestamp": now - 60,
                    "source_model": "Trend",
                    "source_timeframe": "1h",
                    "stop_loss_price": 62000.0,
                    "take_profit_price": 68000.0,
                    "trailing_stop_distance": None,
                    "original_size": 0.25,
                    "tp_levels": "[]",
                    "tp_portions": "[]",
                    "tp_levels_hit": "[]",
                    "original_stop_loss": None,
                    "trail_to_breakeven": False,
                }
            ],
            [
                {
                    "asset": "BTCUSDT",
                    "direction": 1,
                    "entry_price": 63000.0,
                    "current_price": 64000.0,
                    "size": 0.25,
                    "unrealized_pnl": 250.0,
                    "entry_timestamp": now - 60,
                    "source_model": "Trend",
                    "source_timeframe": "1h",
                    "stop_loss_price": 62000.0,
                    "take_profit_price": 68000.0,
                    "trailing_stop_distance": None,
                    "original_size": 0.25,
                    "tp_levels": "[]",
                    "tp_portions": "[]",
                    "tp_levels_hit": "[]",
                    "original_stop_loss": None,
                    "trail_to_breakeven": False,
                }
            ],
            [
                {
                    "asset": "BTCUSDT",
                    "direction": 1,
                    "entry_price": 63000.0,
                    "current_price": 64000.0,
                    "size": 0.25,
                    "unrealized_pnl": 250.0,
                    "entry_timestamp": now - 60,
                    "source_model": "Trend",
                    "source_timeframe": "1h",
                    "stop_loss_price": 62000.0,
                    "take_profit_price": 68000.0,
                    "trailing_stop_distance": None,
                    "original_size": 0.25,
                    "tp_levels": "[]",
                    "tp_portions": "[]",
                    "tp_levels_hit": "[]",
                    "original_stop_loss": None,
                    "trail_to_breakeven": False,
                }
            ],
        ],
    )
    service = RiskObservabilityService(
        _FakePool(conn),
        _FakeRedis(
            streams={
                "orders:BTCUSDT": [
                    (b"1-0", valkey_encode(order, inject_trace=False)),
                ]
            }
        ),
        manifest_store=_FakeManifestStore(
            [
                AssetManifest(
                    symbol="BTCUSDT",
                    publish_timeframes=["1h"],
                    timeframes=["1m", "1h"],
                    updated_at=now,
                )
            ]
        ),
    )

    client = TestClient(
        create_app(
            observability_service=service,
            redis_client=service.redis_client,
            db_pool=service.db_pool,
        )
    )

    health = client.get("/risk/health")
    assert health.status_code == 200
    assert health.json()["db_available"] is True
    assert health.json()["valkey_available"] is True

    summary = client.get("/risk/summary")
    assert summary.status_code == 200
    assert summary.json()["account"]["status"] == "ok"
    assert summary.json()["orders"]["ok_count"] == 1

    latest = client.get("/risk/latest")
    assert latest.status_code == 200
    latest_body = latest.json()
    assert latest_body["status"] == "ok"
    assert latest_body["items"][0]["asset"] == "BTCUSDT"
    assert latest_body["items"][0]["source_timeframe"] == "1h"

    account = client.get("/risk/account")
    assert account.status_code == 200
    assert account.json()["snapshot"]["equity"] == 10025.0

    positions = client.get("/risk/positions/open", params={"asset": "BTCUSDT"})
    assert positions.status_code == 200
    assert positions.json()["count"] == 1

    status = client.get("/risk/status")
    assert status.status_code == 200
    asset_status = status.json()["assets"][0]
    assert asset_status["asset"] == "BTCUSDT"
    assert asset_status["position_count"] == 1
    assert asset_status["latest_order"]["status"] == "ok"


def test_risk_api_routes_forward_params_and_raise_on_service_errors() -> None:
    class _FakeService:
        async def health(self):
            return {"status": "ok"}

        async def summary(self):
            return {"account": {"status": "ok"}, "orders": {"status": "ok"}, "positions": {"status": "ok"}}

        async def latest_orders(self, *, assets=None):
            assert assets == ["BTCUSDT", "ETHUSDT"]
            return {"status": "ok", "count": 2, "items": [{"asset": "BTCUSDT"}, {"asset": "ETHUSDT"}]}

        async def account_snapshot(self):
            return {"status": "error", "error": "db unavailable"}

        async def open_positions(self, *, asset=None):
            assert asset == "BTCUSDT"
            return {"status": "ok", "count": 1, "positions": [{"asset": asset}]}

        async def status(self):
            return {"status": "ok", "count": 1, "assets": [{"asset": "BTCUSDT"}]}

    client = TestClient(create_app(observability_service=_FakeService()))

    latest = client.get("/risk/latest", params=[("assets", "BTCUSDT"), ("assets", "ETHUSDT")])
    assert latest.status_code == 200
    assert latest.json()["count"] == 2

    positions = client.get("/risk/positions/open", params={"asset": "BTCUSDT"})
    assert positions.status_code == 200
    assert positions.json()["positions"][0]["asset"] == "BTCUSDT"

    account = client.get("/risk/account")
    assert account.status_code == 503
    assert account.json()["detail"] == "db unavailable"
