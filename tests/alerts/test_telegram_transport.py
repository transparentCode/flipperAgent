from __future__ import annotations

from apps.alert_app.contracts import (
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
    assert "<code>ingestion_app</code>" in message
    assert "desired_state=PAUSED" in message
    assert "<code>asset</code> ETHUSDT" in message
    assert "<code>timeframe</code> 1m" in message


def test_telegram_transport_normalizes_markdown_to_html() -> None:
    transport = TelegramAlertTransport()

    assert transport._normalize_parse_mode("Markdown") == "HTML"
    assert transport._normalize_parse_mode("MarkdownV2") == "HTML"
    assert transport._normalize_parse_mode("HTML") == "HTML"
