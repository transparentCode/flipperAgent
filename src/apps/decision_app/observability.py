"""Bounded OpenTelemetry metrics for the Decision runtime."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Observation

from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from libs.contracts.decision import require_utc

_LOGGER = logging.getLogger(__name__)

ALLOWED_METRIC_LABELS = frozenset({"lane", "asset", "timeframe", "outcome", "state"})
INPUT_DISPOSITIONS = frozenset(
    {
        "INSERTED",
        "DUPLICATE",
        "ALREADY_REPRESENTED",
        "RECONSTRUCTION_REQUIRED",
        "CONFLICT",
        "MALFORMED",
    }
)
LANE_EVALUATION_OUTCOMES = frozenset({"SIGNAL", "NO_SIGNAL", "BLOCKED", "INVALID"})
PUBLICATION_OUTCOMES = frozenset(
    {"PUBLISHED", "ALREADY_IDENTICAL", "CONFLICT", "FAILED"}
)


def observe_best_effort(
    callback: Callable[..., Any], /, *args: Any, **kwargs: Any
) -> None:
    """Invoke one production telemetry hook without making it authoritative.

    ``DecisionObservability`` remains strict when called directly.  Runtime
    integration uses this boundary so exporter/instrument failures cannot
    change input, evaluation, publication, or lifecycle behavior.  Catching
    ``Exception`` deliberately leaves cancellation and other control-flow
    exceptions untouched.
    """

    try:
        callback(*args, **kwargs)
    except Exception:  # noqa: BLE001
        try:
            _LOGGER.warning("Decision observability hook failed", exc_info=True)
        except Exception:  # noqa: BLE001, S110
            # Logging is also non-authoritative; a broken handler must not
            # turn a telemetry failure into a runtime failure.
            pass


def _timestamp_seconds(value: datetime | None) -> float:
    return 0.0 if value is None else value.timestamp()


def _labels(
    *,
    lane: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
    outcome: str | None = None,
    state: str | None = None,
) -> dict[str, str]:
    values = {
        key: value
        for key, value in {
            "lane": lane,
            "asset": asset,
            "timeframe": timeframe,
            "outcome": outcome,
            "state": state,
        }.items()
        if value is not None
    }
    if not set(values) <= ALLOWED_METRIC_LABELS:  # pragma: no cover - defensive
        raise ValueError("Decision metric labels exceed the approved label set")
    return values


def _duration_ms(start: datetime, end: datetime) -> float:
    return max(0.0, (end - start).total_seconds() * 1000.0)


@dataclass(frozen=True, slots=True)
class _InputGaugeState:
    key: MarketSeriesKey
    latest_market_as_of: datetime | None
    blocked: bool


@dataclass(frozen=True, slots=True)
class _LaneGaugeState:
    lane_id: str
    asset: str
    timeframe: str
    state: str
    latest_market_as_of: datetime | None
    last_disposition: str | None


class DecisionObservability:
    """Own bounded Decision metrics without querying runtime resources in callbacks.

    The runtime calls ``replace_generation`` and ``refresh_runtime`` at existing
    lifecycle boundaries.  Observable callbacks only read the lock-protected
    snapshots and perform local timeframe arithmetic.
    """

    def __init__(
        self,
        *,
        meter: metrics.Meter | None = None,
        timeframe_grid: TimeframeGrid,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(timeframe_grid, TimeframeGrid):
            raise TypeError("timeframe_grid must be TimeframeGrid")
        self.meter = meter or metrics.get_meter("decision", "0.1.0")
        self._grid = timeframe_grid
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._service_state = "STARTING"
        self._inputs: dict[MarketSeriesKey, _InputGaugeState] = {}
        self._lanes: dict[str, _LaneGaugeState] = {}

        self.service_state = self.meter.create_observable_gauge(
            "decision.service.state",
            callbacks=[self._observe_service_state],
            description="Current Decision service state.",
        )
        self.active_lane_count = self.meter.create_observable_gauge(
            "decision.active_lane_count",
            callbacks=[self._observe_active_lane_count],
            description="Number of active Decision lanes in the current generation.",
        )
        self.blocked_input_count = self.meter.create_observable_gauge(
            "decision.blocked_input_count",
            callbacks=[self._observe_blocked_input_count],
            description="Number of blocked canonical Decision inputs.",
        )
        self.input_blocked = self.meter.create_observable_gauge(
            "decision.input.blocked",
            callbacks=[self._observe_input_blocked],
            description="Whether one current canonical Decision input is blocked.",
        )
        self.input_closed_interval_lag = self.meter.create_observable_gauge(
            "decision.input.closed_interval_lag",
            callbacks=[self._observe_input_lag],
            unit="{interval}",
            description="Closed timeframe intervals behind for a Decision input.",
        )
        self.lane_state = self.meter.create_observable_gauge(
            "decision.lane.state",
            callbacks=[self._observe_lane_state],
            description="Current exact LiveLaneStatus for a Decision lane.",
        )
        self.lane_watermark_closed_interval_lag = self.meter.create_observable_gauge(
            "decision.lane.watermark_closed_interval_lag",
            callbacks=[self._observe_lane_watermark_lag],
            unit="{interval}",
            description="Closed timeframe intervals behind for a lane watermark.",
        )
        self.lane_last_disposition = self.meter.create_observable_gauge(
            "decision.lane.last_disposition",
            callbacks=[self._observe_lane_last_disposition],
            description="Last committed effect disposition for a Decision lane.",
        )

        self.input_records_total = self.meter.create_counter(
            "decision.input.records_total",
            description="Direct Decision input record dispositions.",
        )
        self.input_market_latency_ms = self.meter.create_histogram(
            "decision.input.market_latency_ms",
            unit="ms",
            description="Canonical market close to Decision input acceptance.",
        )
        self.input_canonical_event_latency_ms = self.meter.create_histogram(
            "decision.input.canonical_event_latency_ms",
            unit="ms",
            description="Canonical event creation to Decision input acceptance.",
        )
        self.poll_duration_ms = self.meter.create_histogram(
            "decision.poll.duration_ms",
            unit="ms",
            description="One bounded Decision market poll duration.",
        )
        self.lane_evaluation_total = self.meter.create_counter(
            "decision.lane.evaluation_total",
            description="Decision lane policy outcomes.",
        )
        self.publication_total = self.meter.create_counter(
            "decision.publication.total",
            description="Decision publication acknowledgement outcomes.",
        )
        self.rebuild_total = self.meter.create_counter(
            "decision.rebuild.total",
            description="Decision generation rebuild outcomes.",
        )
        self.rebuild_duration_ms = self.meter.create_histogram(
            "decision.rebuild.duration_ms",
            unit="ms",
            description="Decision generation rebuild duration.",
        )

    def replace_generation(
        self,
        *,
        runtime: Any,
        input_series: Mapping[MarketSeriesKey, Any],
    ) -> None:
        """Replace all current-generation gauge identities atomically."""

        if not isinstance(input_series, Mapping):
            raise TypeError("input_series must be a mapping")
        inputs = {
            key: _InputGaugeState(
                key=key,
                latest_market_as_of=None,
                blocked=False,
            )
            for key in input_series
        }
        if any(not isinstance(key, MarketSeriesKey) for key in inputs):
            raise TypeError("input_series keys must be MarketSeriesKey values")
        lanes: dict[str, _LaneGaugeState] = {}
        for lane_id, live_lane in runtime.lanes.items():
            plan = live_lane.lane
            lanes[lane_id] = _LaneGaugeState(
                lane_id=lane_id,
                asset=plan.asset,
                timeframe=plan.decision_timeframe,
                state=live_lane.status,
                latest_market_as_of=None,
                last_disposition=None,
            )
        with self._lock:
            self._inputs = inputs
            self._lanes = lanes
        self.refresh_runtime(runtime)

    def clear_generation(self) -> None:
        """Remove retired generation input/lane series from observable gauges."""

        with self._lock:
            self._inputs = {}
            self._lanes = {}

    def refresh_runtime(self, runtime: Any) -> None:
        """Copy bounded runtime state into the callback-only gauge cache."""

        blocked_streams = runtime.input.blocked_streams
        with self._lock:
            inputs = {
                key: _InputGaugeState(
                    key=state.key,
                    latest_market_as_of=runtime.input.cursor_for(
                        key
                    ).latest_market_as_of,
                    blocked=runtime.input.cursor_for(key).stream_key in blocked_streams,
                )
                for key, state in self._inputs.items()
            }
            lanes = {
                lane_id: _LaneGaugeState(
                    lane_id=lane_id,
                    asset=state.asset,
                    timeframe=state.timeframe,
                    state=live_lane.status,
                    latest_market_as_of=live_lane.finalizer.watermark.latest_market_as_of,
                    last_disposition=live_lane.finalizer.watermark.last_disposition,
                )
                for lane_id, state in self._lanes.items()
                for live_lane in (runtime.lanes.get(lane_id),)
                if live_lane is not None
            }
            self._inputs = inputs
            self._lanes = lanes

    def set_service_state(self, state: str) -> None:
        if not isinstance(state, str) or not state.strip():
            raise ValueError("Decision service state must be non-empty")
        with self._lock:
            self._service_state = state

    def record_input_result(
        self,
        result: Any,
        *,
        accepted_at: datetime | None = None,
    ) -> None:
        disposition = getattr(result, "disposition", None)
        if disposition not in INPUT_DISPOSITIONS:
            raise ValueError(f"unsupported input disposition: {disposition}")
        series_key = getattr(result, "series_key", None)
        attributes = _labels(
            asset=None if series_key is None else series_key.asset,
            timeframe=None if series_key is None else series_key.timeframe,
            outcome=disposition,
        )
        self.input_records_total.add(1, attributes)
        accepted = require_utc(
            accepted_at or self._now_fn(),
            field_name="accepted_at",
        )
        market_as_of = getattr(result, "market_as_of", None)
        if market_as_of is not None:
            self.input_market_latency_ms.record(
                _duration_ms(
                    require_utc(market_as_of, field_name="market_as_of"), accepted
                ),
                _labels(
                    asset=None if series_key is None else series_key.asset,
                    timeframe=None if series_key is None else series_key.timeframe,
                    outcome=disposition,
                ),
            )
        event = getattr(result, "event", None)
        occurred_at = None if event is None else event.occurred_at
        if occurred_at is not None:
            self.input_canonical_event_latency_ms.record(
                _duration_ms(
                    require_utc(occurred_at, field_name="occurred_at"), accepted
                ),
                _labels(
                    asset=None if series_key is None else series_key.asset,
                    timeframe=None if series_key is None else series_key.timeframe,
                    outcome=disposition,
                ),
            )

    def _lane_identity_labels(self, lane_id: str) -> dict[str, str]:
        if not isinstance(lane_id, str) or not lane_id.strip():
            raise ValueError("lane_id must be non-empty")
        with self._lock:
            lane = self._lanes.get(lane_id)
        return _labels(
            lane=lane_id,
            asset=None if lane is None else lane.asset,
            timeframe=None if lane is None else lane.timeframe,
        )

    def record_lane_evaluation(self, *, lane_id: str, outcome: str) -> None:
        if outcome not in LANE_EVALUATION_OUTCOMES:
            raise ValueError(f"unsupported lane evaluation outcome: {outcome}")
        self.lane_evaluation_total.add(
            1,
            _labels(**self._lane_identity_labels(lane_id), outcome=outcome),
        )

    def record_publication(self, *, lane_id: str, outcome: str) -> None:
        if not isinstance(outcome, str) or outcome not in PUBLICATION_OUTCOMES:
            raise ValueError(f"unsupported publication outcome: {outcome}")
        self.publication_total.add(
            1,
            _labels(**self._lane_identity_labels(lane_id), outcome=outcome),
        )

    def record_poll_duration(self, duration_ms: float) -> None:
        self.poll_duration_ms.record(max(0.0, float(duration_ms)))

    def record_rebuild(self, *, outcome: str, duration_ms: float) -> None:
        if outcome not in {"success", "failure"}:
            raise ValueError("rebuild outcome must be success or failure")
        self.rebuild_total.add(1, _labels(outcome=outcome))
        self.rebuild_duration_ms.record(
            max(0.0, float(duration_ms)), _labels(outcome=outcome)
        )

    def _observe_service_state(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            state = self._service_state
        return (Observation(1, _labels(state=state)),)

    def _observe_active_lane_count(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = len(self._lanes)
        return (Observation(value),)

    def _observe_blocked_input_count(
        self,
        _options: CallbackOptions,
    ) -> tuple[Observation, ...]:
        with self._lock:
            value = sum(state.blocked for state in self._inputs.values())
        return (Observation(value),)

    def _observe_input_blocked(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._inputs.values())
        return iter(
            Observation(
                int(state.blocked),
                _labels(asset=state.key.asset, timeframe=state.key.timeframe),
            )
            for state in values
        )

    def _observe_input_lag(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._inputs.values())
        now = require_utc(self._now_fn(), field_name="now_fn result")
        observations = []
        for state in values:
            lag = self._closed_interval_lag(
                timeframe=state.key.timeframe,
                latest_market_as_of=state.latest_market_as_of,
                now=now,
            )
            if lag is not None:
                observations.append(
                    Observation(
                        lag,
                        _labels(asset=state.key.asset, timeframe=state.key.timeframe),
                    )
                )
        return iter(observations)

    def _observe_lane_state(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._lanes.values())
        return iter(
            Observation(
                1,
                _labels(
                    lane=lane.lane_id,
                    asset=lane.asset,
                    timeframe=lane.timeframe,
                    state=lane.state,
                ),
            )
            for lane in values
        )

    def _observe_lane_watermark_lag(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._lanes.values())
        now = require_utc(self._now_fn(), field_name="now_fn result")
        observations = []
        for lane in values:
            lag = self._closed_interval_lag(
                timeframe=lane.timeframe,
                latest_market_as_of=lane.latest_market_as_of,
                now=now,
            )
            if lag is not None:
                observations.append(
                    Observation(
                        lag,
                        _labels(
                            lane=lane.lane_id,
                            asset=lane.asset,
                            timeframe=lane.timeframe,
                        ),
                    )
                )
        return iter(observations)

    def _observe_lane_last_disposition(
        self,
        _options: CallbackOptions,
    ) -> Iterator[Observation]:
        with self._lock:
            values = tuple(self._lanes.values())
        return iter(
            Observation(
                1,
                _labels(
                    lane=lane.lane_id,
                    asset=lane.asset,
                    timeframe=lane.timeframe,
                    outcome=lane.last_disposition,
                ),
            )
            for lane in values
            if lane.last_disposition is not None
        )

    def _closed_interval_lag(
        self,
        *,
        timeframe: str,
        latest_market_as_of: datetime | None,
        now: datetime,
    ) -> int | None:
        if latest_market_as_of is None:
            return None
        expected = self._grid.expected_closed_cutoff(timeframe, now)
        if latest_market_as_of >= expected:
            return 0
        duration = self._grid.duration(timeframe)
        return max(0, int((expected - latest_market_as_of) // duration))


__all__ = [
    "ALLOWED_METRIC_LABELS",
    "INPUT_DISPOSITIONS",
    "LANE_EVALUATION_OUTCOMES",
    "PUBLICATION_OUTCOMES",
    "DecisionObservability",
    "observe_best_effort",
]
