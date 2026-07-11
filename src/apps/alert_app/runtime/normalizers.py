from __future__ import annotations

from typing import Any

from apps.alert_app.contracts import (
    AlertEventType,
    AlertSeverity,
    AlertSourceApp,
    NormalizedAlertEvent,
)
from apps.execution_app.state import ExecutionFailureEvent
from libs.common.asset_manifest import AssetLifecycleEvent
from libs.contracts.ingestion import IngestionEventType, IngestionRuntimeEvent


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


def normalize_ingestion_runtime_event(event: IngestionRuntimeEvent) -> NormalizedAlertEvent | None:
    mapped_type = {
        IngestionEventType.GAP_FILL_FAILED: AlertEventType.INGESTION_GAP_FILL_FAILURE,
        IngestionEventType.GAP_FILL_ENQUEUE_FAILED: AlertEventType.INGESTION_GAP_FILL_FAILURE,
        IngestionEventType.ASSET_PURGE_FAILED: AlertEventType.INGESTION_PURGE_FAILURE,
        IngestionEventType.RUNTIME_RETRY_EXHAUSTED: AlertEventType.INGESTION_RUNTIME_FAILURE,
    }.get(event.event_type)
    if mapped_type is None:
        return None
    severity = _severity_from_value(event.severity)
    title, summary = _ingestion_runtime_copy(event)
    return NormalizedAlertEvent(
        event_id=event.event_id,
        event_type=mapped_type,
        source_app=AlertSourceApp.INGESTION,
        source_component="ingestion_runtime",
        severity=severity,
        asset=event.symbol,
        timeframe=event.timeframe,
        title=title,
        summary=summary,
        detail=dict(event.detail),
        dedupe_key=(
            f"ingestion:{event.event_type.value}:{event.symbol}:"
            f"{event.timeframe or 'na'}:{_detail_fingerprint(event.detail)}"
        ),
        recovery_key=f"ingestion:{event.event_type.value}:{event.symbol}:{event.timeframe or 'na'}",
        emitted_at=event.emitted_at,
    )


def _ingestion_runtime_copy(event: IngestionRuntimeEvent) -> tuple[str, str]:
    symbol_ref = f"{event.symbol}{' ' + event.timeframe if event.timeframe else ''}"
    detail = dict(event.detail)

    if event.event_type == IngestionEventType.GAP_FILL_FAILED:
        failed_assets = detail.get("failed_assets") or []
        failed_count = len(failed_assets)
        title = f"Ingestion gap fill failed for {event.symbol}"
        summary = (
            f"Gap fill failed for {event.symbol}{' ' + event.timeframe if event.timeframe else ''}; "
            f"{failed_count} asset(s) failed"
        )
        return title, summary

    if event.event_type == IngestionEventType.GAP_FILL_ENQUEUE_FAILED:
        error = detail.get("error") or "unknown enqueue error"
        title = f"Ingestion gap-fill enqueue failed for {symbol_ref}"
        summary = f"Gap-fill recovery could not be queued for {symbol_ref}: {error}"
        return title, summary

    if event.event_type == IngestionEventType.RUNTIME_RETRY_EXHAUSTED:
        disconnect_count = detail.get("disconnect_count")
        threshold = detail.get("threshold")
        if disconnect_count is not None and threshold is not None:
            summary = (
                f"Ingestion runtime retry exhausted for {symbol_ref}; "
                f"disconnect count {disconnect_count}/{threshold}"
            )
        else:
            summary = f"Ingestion runtime retry exhausted for {symbol_ref}"
        return f"Ingestion retry exhausted for {symbol_ref}", summary

    if event.event_type == IngestionEventType.ASSET_PURGE_FAILED:
        error = detail.get("error")
        title = f"Ingestion asset purge failed for {symbol_ref}"
        summary = (
            f"Asset purge failed for {symbol_ref}: {error}"
            if error
            else f"Asset purge failed for {symbol_ref}"
        )
        return title, summary

    title = f"Ingestion {event.event_type.value} for {event.symbol}"
    summary = (
        f"Ingestion runtime emitted {event.event_type.value} "
        f"for {event.symbol}{' ' + event.timeframe if event.timeframe else ''}"
    )
    return title, summary


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


def _detail_fingerprint(detail: dict[str, Any]) -> str:
    if not detail:
        return "no_detail"
    keys = sorted(str(key) for key in detail.keys())
    return "|".join(keys)


def _severity_from_value(value: str) -> AlertSeverity:
    normalized = str(value).lower().strip()
    try:
        return AlertSeverity(normalized)
    except ValueError:
        return AlertSeverity.WARNING
