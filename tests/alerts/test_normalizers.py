from __future__ import annotations

from apps.alert_app.runtime.normalizers import (
    normalize_execution_failure_event,
    normalize_ingestion_runtime_event,
    normalize_lifecycle_event,
)
from apps.execution_app.state import ExecutionFailureEvent
from libs.common.asset_manifest import AssetLifecycleEvent, AssetLifecycleEventType
from libs.contracts.ingestion import IngestionEventType, IngestionRuntimeEvent


def test_normalize_lifecycle_event() -> None:
    event = AssetLifecycleEvent(
        event_id="evt_1",
        event_type=AssetLifecycleEventType.ASSET_PAUSED,
        command_id="cmd_1",
        command_type="PAUSE_ASSET",
        symbol="btcusdt",
        base_timeframe="1m",
        publish_timeframes=["1m", "1h"],
        timeframes=["1m", "1h"],
        enabled=True,
        desired_state="PAUSED",
        requested_by="api_app",
        emitted_at=1.0,
    )
    normalized = normalize_lifecycle_event(event)
    assert normalized.asset == "BTCUSDT"
    assert normalized.severity.value == "warning"
    assert normalized.event_type.value == "lifecycle_event"


def test_normalize_ingestion_runtime_event() -> None:
    event = IngestionRuntimeEvent(
        event_id="evt_2",
        event_type=IngestionEventType.RUNTIME_RETRY_EXHAUSTED,
        symbol="ETHUSDT",
        timeframe="1h",
        severity="critical",
        detail={"reason": "timeout", "disconnect_count": 5, "threshold": 5},
        emitted_at=2.0,
    )
    normalized = normalize_ingestion_runtime_event(event)
    assert normalized is not None
    assert normalized.asset == "ETHUSDT"
    assert normalized.timeframe == "1h"
    assert normalized.severity.value == "critical"
    assert normalized.event_type.value == "ingestion_runtime_failure"
    assert normalized.title == "Ingestion retry exhausted for ETHUSDT 1h"
    assert normalized.summary == "Ingestion runtime retry exhausted for ETHUSDT 1h; disconnect count 5/5"


def test_normalize_ingestion_gap_fill_enqueue_failure_event() -> None:
    event = IngestionRuntimeEvent(
        event_id="evt_3",
        event_type=IngestionEventType.GAP_FILL_ENQUEUE_FAILED,
        symbol="BTCUSDT",
        timeframe="1m",
        severity="error",
        detail={"error": "redis unavailable"},
        emitted_at=3.0,
    )
    normalized = normalize_ingestion_runtime_event(event)
    assert normalized is not None
    assert normalized.event_type.value == "ingestion_gap_fill_failure"
    assert normalized.severity.value == "error"
    assert normalized.title == "Ingestion gap-fill enqueue failed for BTCUSDT 1m"
    assert normalized.summary == "Gap-fill recovery could not be queued for BTCUSDT 1m: redis unavailable"


def test_normalize_ingestion_runtime_event_returns_none_for_success_events() -> None:
    for event_type in (
        IngestionEventType.COMMAND_ACCEPTED,
        IngestionEventType.GAP_FILL_COMPLETED,
        IngestionEventType.ASSET_PURGE_COMPLETED,
    ):
        event = IngestionRuntimeEvent(
            event_id="evt_success",
            event_type=event_type,
            symbol="ETHUSDT",
            timeframe="1h",
            severity="info",
            detail={"asset_count": 6},
            emitted_at=2.0,
        )
        assert normalize_ingestion_runtime_event(event) is None


def test_normalize_execution_failure_event() -> None:
    event = ExecutionFailureEvent(
        asset="SOLUSDT",
        stream="orders:SOLUSDT",
        consumer_group="execution_app_group",
        consumer_name="execution_worker_SOLUSDT",
        message_id="123-0",
        idempotency_key="idem_1",
        timestamp=3.0,
        error_type="TimeoutError",
        error_message="network timeout",
        order_side="buy",
        order_size=1.0,
        requested_price=150.0,
        order_type="market",
    )
    normalized = normalize_execution_failure_event(event)
    assert normalized.asset == "SOLUSDT"
    assert normalized.severity.value == "critical"
    assert normalized.event_type.value == "execution_failure"
    assert normalized.detail["error_type"] == "TimeoutError"
