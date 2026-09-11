from __future__ import annotations

from apps.alert_app.contracts import (
    AlertEventType,
    AlertSeverity,
    AlertSourceApp,
    NormalizedAlertEvent,
)
from apps.execution_app.state import ExecutionFailureEvent
from libs.common.asset_manifest import AssetLifecycleEvent


def normalize_lifecycle_event(event: AssetLifecycleEvent) -> NormalizedAlertEvent:
    desired_state = str(event.desired_state).upper()
    enabled = bool(event.enabled)
    severity = AlertSeverity.INFO
    if desired_state in {"PAUSED", "STOPPED", "REMOVING"} or not enabled:
        severity = AlertSeverity.WARNING
    title = f"Asset lifecycle {event.command_type} for {event.symbol}"
    summary = (
        f"{event.symbol} lifecycle changed to desired_state={desired_state} "
        f"base_tf={event.base_timeframe}"
    )
    return NormalizedAlertEvent(
        event_id=event.event_id,
        event_type=AlertEventType.LIFECYCLE_EVENT,
        source_app=AlertSourceApp.INGESTION,
        source_component="ingestion_control_plane",
        severity=severity,
        asset=event.symbol,
        timeframe=event.base_timeframe,
        title=title,
        summary=summary,
        detail={
            "command_type": event.command_type,
            "event_type": event.event_type.value,
            "enabled": event.enabled,
            "desired_state": event.desired_state,
            "publish_timeframes": list(event.publish_timeframes),
            "timeframes": list(event.timeframes),
            "reason": event.reason,
            "request_id": event.request_id,
            "asset_version": event.asset_version,
            "timeframe_version": event.timeframe_version,
        },
        dedupe_key=f"lifecycle:{event.symbol}:{event.command_type}:{event.asset_version}",
        emitted_at=event.emitted_at,
    )


def normalize_execution_failure_event(
    event: ExecutionFailureEvent,
) -> NormalizedAlertEvent:
    title = f"Execution failure for {event.asset}"
    summary = (
        f"Execution consumer {event.consumer_name} failed for {event.asset}: "
        f"{event.error_type}"
    )
    return NormalizedAlertEvent(
        event_id=f"{event.asset}:{event.message_id}",
        event_type=AlertEventType.EXECUTION_FAILURE,
        source_app=AlertSourceApp.EXECUTION,
        source_component="execution_worker",
        severity=AlertSeverity.CRITICAL,
        asset=event.asset,
        timeframe=None,
        title=title,
        summary=summary,
        detail=event.model_dump(mode="json"),
        dedupe_key=(
            f"execution:{event.asset}:{event.error_type}:"
            f"{event.idempotency_key or event.message_id}"
        ),
        recovery_key=f"execution:{event.asset}",
        emitted_at=event.timestamp,
    )
