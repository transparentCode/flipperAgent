from __future__ import annotations

from apps.alert_app.contracts import (
    AlertEventType,
    AlertIncidentRecord,
    AlertIncidentState,
    AlertSeverity,
    AlertSourceApp,
)
from apps.alert_app.notifications.transports.telegram import TelegramAlertTransport


def _incident() -> AlertIncidentRecord:
    return AlertIncidentRecord(
        incident_id="inc_telegram",
        dedupe_key="dedupe_telegram",
        event_type="lifecycle_event",
        source_app=AlertSourceApp.INGESTION,
        source_component="ingestion_control_plane",
        severity=AlertSeverity.WARNING,
        state=AlertIncidentState.OPEN,
        asset="ETHUSDT",
        timeframe="1m",
        title="Asset lifecycle PAUSE_ASSET for ETHUSDT",
        summary="ETHUSDT lifecycle changed to desired_state=PAUSED base_tf=1m",
        first_seen_at=1.0,
        last_seen_at=1.0,
        updated_at=1.0,
    )


def test_telegram_transport_uses_html_safe_formatting() -> None:
    transport = TelegramAlertTransport()

    message = transport._format_message(_incident(), parse_mode="HTML")

    assert "<b>WARNING</b>" in message
    assert "<code>ingestion</code>" in message
    assert "desired_state=PAUSED" in message
    assert "<code>asset</code> ETHUSDT" in message
    assert "<code>timeframe</code> 1m" in message


def test_telegram_transport_normalizes_markdown_to_html() -> None:
    transport = TelegramAlertTransport()

    assert transport._normalize_parse_mode("Markdown") == "HTML"
    assert transport._normalize_parse_mode("MarkdownV2") == "HTML"
    assert transport._normalize_parse_mode("HTML") == "HTML"


def test_telegram_transport_formats_health_incident_readably() -> None:
    transport = TelegramAlertTransport()
    incident = AlertIncidentRecord(
        incident_id="inc_health",
        dedupe_key="dedupe_health",
        event_type=AlertEventType.SYSTEM_HEALTH_BREACH,
        source_app=AlertSourceApp.INGESTION,
        source_component="health_check:ingestion_runtime",
        severity=AlertSeverity.CRITICAL,
        state=AlertIncidentState.OPEN,
        title="Health probe failed for ingestion_runtime",
        summary=(
            "No HTTP response from http://ingestion:8003/health/ready. "
            "Service may still be starting or unreachable."
        ),
        detail={
            "url": "http://ingestion:8003/health/ready",
            "error": "Cannot connect to host ingestion:8003 ssl:default [Connect call failed]",
        },
        first_seen_at=1.0,
        last_seen_at=1.0,
        updated_at=1.0,
    )

    message = transport._format_message(incident, parse_mode="HTML")

    assert "<b>Health probe failed for ingestion_runtime</b>" in message
    assert "No HTTP response from http://ingestion:8003/health/ready." in message
    assert "<code>probe</code> http://ingestion:8003/health/ready" in message
    assert "<code>cause</code> connection refused" in message
