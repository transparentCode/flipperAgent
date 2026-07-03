from __future__ import annotations

from apps.alert_app.incidents.repository import _row_to_incident


def test_row_to_incident_decodes_json_strings() -> None:
    incident = _row_to_incident(
        {
            "incident_id": "inc_1",
            "dedupe_key": "dedupe_1",
            "event_type": "execution_failure",
            "source_app": "execution_app",
            "source_component": "execution_worker",
            "severity": "critical",
            "state": "open",
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "title": "failure",
            "summary": "failure summary",
            "detail": '{"error":"timeout","attempt":2}',
            "occurrence_count": 1,
            "route_names": '["ops_alerts","system_alerts"]',
            "first_seen_at": 1.0,
            "last_seen_at": 2.0,
            "last_notified_at": 2.0,
            "acknowledged_at": None,
            "resolved_at": None,
            "updated_at": 2.0,
        }
    )

    assert incident.detail == {"error": "timeout", "attempt": 2}
    assert incident.route_names == ["ops_alerts", "system_alerts"]
