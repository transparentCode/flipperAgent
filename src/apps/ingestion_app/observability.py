"""Small, bounded OpenTelemetry surface for ingestion."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest


def _timestamp_seconds(value: datetime | None) -> float:
    return 0.0 if value is None else value.timestamp()


class IngestionObservability:
    """Own the bounded ingestion metric instruments and application spans.

    The object deliberately keeps gauge state in memory.  Metric callbacks only
    read that state, so no database or broker operation is introduced into a
    hot path or into telemetry export.
    """

    def __init__(
        self,
        *,
        meter: metrics.Meter | None = None,
        tracer: trace.Tracer | None = None,
    ) -> None:
        self.meter = meter or metrics.get_meter("ingestion", "0.1.0")
        self.tracer = tracer or trace.get_tracer("ingestion", "0.1.0")
        self._lock = threading.Lock()
        self._runtime_live = False
        self._websocket_connected = False
        self._queue_utilization = 0.0
        self._base_last_close: dict[tuple[str, str], float] = {}
        self._outbox_pending = 0
        self._outbox_oldest = 0.0

        self.candle_commit_total = self.meter.create_counter(
            "ingestion.candle.commit_total",
            description="Canonical candle commit outcomes.",
        )
        self.candle_commit_duration_ms = self.meter.create_histogram(
            "ingestion.candle.commit.duration_ms",
            unit="ms",
            description="Canonical candle commit duration.",
        )
        self.base_last_close_timestamp_seconds = self.meter.create_observable_gauge(
            "ingestion.base.last_close_timestamp_seconds",
            callbacks=[self._observe_base_last_close],
            unit="s",
            description="Latest canonical base-candle close by lane.",
        )
        self.websocket_connected = self.meter.create_observable_gauge(
            "ingestion.websocket.connected",
            callbacks=[self._observe_websocket_connected],
            description="Whether the Binance websocket is connected.",
        )
        self.websocket_reconnect_total = self.meter.create_counter(
            "ingestion.websocket.reconnect_total",
            description="Successful websocket reconnects after the first connection.",
        )
        self.websocket_interruption_total = self.meter.create_counter(
            "ingestion.websocket.interruption_total",
            description="Websocket interruptions observed by the runtime.",
        )
        self.websocket_queue_utilization = self.meter.create_observable_gauge(
            "ingestion.websocket.queue_utilization",
            callbacks=[self._observe_queue_utilization],
            description="Fraction of the bounded websocket queue in use.",
        )
        self.recovery_total = self.meter.create_counter(
            "ingestion.recovery.total",
            description="Recovery request outcomes.",
        )
        self.recovery_duration_ms = self.meter.create_histogram(
            "ingestion.recovery.duration_ms",
            unit="ms",
            description="Recovery request duration.",
        )
        self.outbox_pending = self.meter.create_observable_gauge(
            "ingestion.outbox.pending",
            callbacks=[self._observe_outbox_pending],
            description="Current number of pending durable outbox events.",
        )
        self.outbox_oldest_pending_timestamp_seconds = (
            self.meter.create_observable_gauge(
                "ingestion.outbox.oldest_pending_timestamp_seconds",
                callbacks=[self._observe_outbox_oldest],
                unit="s",
                description="Oldest pending outbox occurred_at timestamp.",
            )
        )
        self.outbox_publish_total = self.meter.create_counter(
            "ingestion.outbox.publish_total",
            description="Durable outbox events successfully published.",
        )
        self.outbox_publish_failure_total = self.meter.create_counter(
            "ingestion.outbox.publish_failure_total",
            description="Outbox publication batches that failed.",
        )
        self.outbox_publish_batch_size = self.meter.create_histogram(
            "ingestion.outbox.publish_batch_size",
            unit="{event}",
            description="Number of events selected for an outbox batch.",
        )
        self.outbox_publish_duration_ms = self.meter.create_histogram(
            "ingestion.outbox.publish.duration_ms",
            unit="ms",
            description="Outbox publication batch duration.",
        )
        self.runtime_live = self.meter.create_observable_gauge(
            "ingestion.runtime.live",
            callbacks=[self._observe_runtime_live],
            description="Whether the ingestion runtime is LIVE.",
        )

    def _observe_base_last_close(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._base_last_close.items())
        return iter(
            Observation(
                timestamp,
                {"venue": venue, "instrument_id": instrument_id},
            )
            for (venue, instrument_id), timestamp in values
        )

    def _observe_websocket_connected(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = int(self._websocket_connected)
        return (Observation(value),)

    def _observe_queue_utilization(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = self._queue_utilization
        return (Observation(value),)

    def _observe_outbox_pending(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = self._outbox_pending
        return (Observation(value),)

    def _observe_outbox_oldest(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = self._outbox_oldest
        return (Observation(value),)

    def _observe_runtime_live(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = int(self._runtime_live)
        return (Observation(value),)

    def record_candle_commit(
        self,
        *,
        timeframe: str,
        source_type: str,
        outcome: Any,
        duration_ms: float,
    ) -> None:
        outcome_value = getattr(outcome, "value", outcome)
        if outcome_value not in {"inserted", "duplicate", "conflict"}:
            raise ValueError(f"unsupported candle commit outcome: {outcome_value}")
        attributes = {
            "timeframe": timeframe,
            "source_type": source_type,
            "outcome": outcome_value,
        }
        self.candle_commit_total.add(1, attributes)
        self.candle_commit_duration_ms.record(
            duration_ms,
            {"timeframe": timeframe, "source_type": source_type},
        )

    def record_base_last_close(self, lane: MarketLane, close_time: datetime) -> None:
        key = (lane.venue, lane.instrument_id)
        timestamp = close_time.timestamp()
        with self._lock:
            previous = self._base_last_close.get(key)
            if previous is None or timestamp > previous:
                self._base_last_close[key] = timestamp

    def set_websocket_connected(self, connected: bool) -> None:
        with self._lock:
            self._websocket_connected = bool(connected)

    def record_websocket_reconnect(self) -> None:
        self.websocket_reconnect_total.add(1)

    def record_websocket_interruption(self) -> None:
        self.websocket_interruption_total.add(1)

    def set_queue_utilization(self, qsize: int, maxsize: int) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        value = min(1.0, max(0.0, qsize / maxsize))
        with self._lock:
            self._queue_utilization = value

    def record_recovery(self, *, outcome: str, duration_ms: float) -> None:
        if outcome not in {"success", "failure"}:
            raise ValueError(f"unsupported recovery outcome: {outcome}")
        self.recovery_total.add(1, {"outcome": outcome})
        self.recovery_duration_ms.record(duration_ms)

    @contextmanager
    def recovery_span(self, request: RecoveryRequest) -> Iterator[Any]:
        """Trace one bounded recovery request without adding metric labels."""
        attributes = {
            "venue": request.lane.venue,
            "instrument_id": request.lane.instrument_id,
            "timeframe": request.lane.timeframe,
            "since": request.since.isoformat(),
            "until": request.until.isoformat(),
            "reason": request.reason,
        }
        with self.tracer.start_as_current_span(
            "ingestion.recovery",
            attributes=attributes,
        ) as span:
            yield span

    @contextmanager
    def outbox_publish_span(self, batch_size: int) -> Iterator[Any]:
        with self.tracer.start_as_current_span(
            "ingestion.outbox.publish_batch",
            attributes={"batch_size": batch_size},
        ) as span:
            yield span

    def set_outbox_state(
        self,
        *,
        pending: int,
        oldest_pending: datetime | None,
    ) -> None:
        if pending < 0:
            raise ValueError("pending must be non-negative")
        with self._lock:
            self._outbox_pending = pending
            self._outbox_oldest = _timestamp_seconds(oldest_pending)

    def record_outbox_insert(self, occurred_at: datetime) -> None:
        timestamp = occurred_at.timestamp()
        with self._lock:
            self._outbox_pending += 1
            if self._outbox_oldest == 0.0 or timestamp < self._outbox_oldest:
                self._outbox_oldest = timestamp

    def record_outbox_published(self) -> None:
        with self._lock:
            self._outbox_pending = max(0, self._outbox_pending - 1)
            if self._outbox_pending == 0:
                self._outbox_oldest = 0.0

    def record_publish_batch(
        self,
        *,
        batch_size: int,
        successful_publishes: int,
        duration_ms: float,
        failed: bool,
    ) -> None:
        self.outbox_publish_batch_size.record(batch_size)
        self.outbox_publish_total.add(successful_publishes)
        self.outbox_publish_duration_ms.record(duration_ms)
        if failed:
            self.outbox_publish_failure_total.add(1)

    def set_runtime_live(self, live: bool) -> None:
        with self._lock:
            self._runtime_live = bool(live)


__all__ = ["IngestionObservability"]
