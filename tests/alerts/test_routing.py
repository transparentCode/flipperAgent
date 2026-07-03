from __future__ import annotations

from apps.alert_app.contracts import (
    AlertEventType,
    AlertSeverity,
    AlertSourceApp,
    NormalizedAlertEvent,
)
from apps.alert_app.rules.routing import resolve_routes_for_event


def test_resolve_routes_for_execution_event() -> None:
    event = NormalizedAlertEvent(
        event_id="evt_1",
        event_type=AlertEventType.EXECUTION_FAILURE,
        source_app=AlertSourceApp.EXECUTION,
        source_component="execution_worker",
        severity=AlertSeverity.CRITICAL,
        asset="BTCUSDT",
        timeframe=None,
        title="Execution failure",
        summary="execution failed",
        dedupe_key="dedupe_1",
        emitted_at=1.0,
    )
    routes = resolve_routes_for_event(event)
    assert "system_alerts" in routes
    assert "execution_alerts" not in routes
