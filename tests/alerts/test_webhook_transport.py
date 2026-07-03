from __future__ import annotations

import pytest
from aiohttp import web

from apps.alert_app.contracts import (
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
)
from apps.alert_app.notifications.transports.webhook import WebhookAlertTransport


def _incident() -> AlertIncidentRecord:
    return AlertIncidentRecord(
        incident_id="inc_webhook",
        dedupe_key="dedupe_webhook",
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
async def test_webhook_transport_posts_payload_with_headers(unused_tcp_port: int) -> None:
    received: dict[str, object] = {}

    async def _handler(request: web.Request) -> web.Response:
        received["authorization"] = request.headers.get("Authorization")
        received["custom"] = request.headers.get("X-Alert-App")
        received["payload"] = await request.json()
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/alerts/system", _handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()

    transport = WebhookAlertTransport()
    try:
        await transport.send(
            incident=_incident(),
            route_name="system_alerts",
            route_config={
                "destination": f"http://127.0.0.1:{unused_tcp_port}/alerts/system",
                "authorization_header": "Bearer test-secret",
                "headers": {"X-Alert-App": "flipperAgent"},
                "timeout_seconds": 5,
                "max_attempts": 1,
            },
        )
    finally:
        await runner.cleanup()

    assert received["authorization"] == "Bearer test-secret"
    assert received["custom"] == "flipperAgent"
    payload = received["payload"]
    assert isinstance(payload, dict)
    assert payload["incident_id"] == "inc_webhook"
    assert payload["severity"] == "critical"


@pytest.mark.asyncio
async def test_webhook_transport_retries_then_succeeds(unused_tcp_port: int) -> None:
    attempts = {"count": 0}

    async def _handler(_request: web.Request) -> web.Response:
        attempts["count"] += 1
        if attempts["count"] < 2:
            return web.Response(status=500, text="try again")
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/alerts/system", _handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()

    transport = WebhookAlertTransport()
    try:
        await transport.send(
            incident=_incident(),
            route_name="system_alerts",
            route_config={
                "destination": f"http://127.0.0.1:{unused_tcp_port}/alerts/system",
                "timeout_seconds": 5,
                "max_attempts": 2,
                "backoff_seconds": 0,
            },
        )
    finally:
        await runner.cleanup()

    assert attempts["count"] == 2
