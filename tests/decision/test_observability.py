from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from apps.decision_app.domain.contracts import InputReadCursor, LaneCommitWatermark
from apps.decision_app.domain.market_state import MarketSeriesKey, TimeframeGrid
from apps.decision_app.observability import (
    ALLOWED_METRIC_LABELS,
    DecisionObservability,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
DASHBOARD_FILE = (
    Path(__file__).parents[2]
    / "configs/observability/grafana/provisioning/dashboards/pipeline-health.json"
)


@dataclass
class _Instrument:
    callbacks: list[object] | None = None

    def __post_init__(self) -> None:
        self.records: list[tuple[float, dict[str, str]]] = []
        self.adds: list[tuple[float, dict[str, str]]] = []

    def record(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.records.append((value, attributes or {}))

    def add(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.adds.append((value, attributes or {}))


class _Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, _Instrument] = {}

    def create_observable_gauge(self, name: str, *, callbacks: list[object], **_kwargs):
        instrument = _Instrument(callbacks)
        self.instruments[name] = instrument
        return instrument

    def create_counter(self, name: str, **_kwargs):
        instrument = _Instrument()
        self.instruments[name] = instrument
        return instrument

    def create_histogram(self, name: str, **_kwargs):
        instrument = _Instrument()
        self.instruments[name] = instrument
        return instrument


class _Input:
    def __init__(self, cursors: dict[MarketSeriesKey, InputReadCursor]) -> None:
        self._cursors = cursors
        self.blocked_streams: dict[str, str] = {}

    def cursor_for(self, key: MarketSeriesKey) -> InputReadCursor:
        return self._cursors[key]


def _runtime(
    key: MarketSeriesKey,
    *,
    lane_id: str,
    lane_timeframe: str,
    latest_input: datetime | None,
    latest_watermark: datetime | None,
) -> SimpleNamespace:
    cursor = InputReadCursor(
        stream_key=f"stream:{key.asset}:{key.timeframe}",
        latest_market_as_of=latest_input,
    )
    lane = SimpleNamespace(
        lane=SimpleNamespace(
            asset=key.asset,
            decision_timeframe=lane_timeframe,
        ),
        status="LIVE",
        finalizer=SimpleNamespace(
            watermark=LaneCommitWatermark(
                lane_id=lane_id,
                latest_market_as_of=latest_watermark,
                last_disposition="published",
            )
        ),
    )
    return SimpleNamespace(
        input=_Input({key: cursor}),
        lanes={lane_id: lane},
    )


def _observations(meter: _Meter, name: str):
    callback = meter.instruments[name].callbacks[0]
    return tuple(callback(None))


def test_decision_metric_surface_uses_only_approved_labels() -> None:
    meter = _Meter()
    observation = DecisionObservability(
        meter=meter,
        timeframe_grid=TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(hours=1)},
        ),
        now_fn=lambda: BASE + timedelta(hours=2),
    )

    assert set(meter.instruments) == {
        "decision.service.state",
        "decision.active_lane_count",
        "decision.blocked_input_count",
        "decision.input.blocked",
        "decision.input.closed_interval_lag",
        "decision.lane.state",
        "decision.lane.watermark_closed_interval_lag",
        "decision.lane.last_disposition",
        "decision.input.records_total",
        "decision.input.market_latency_ms",
        "decision.input.canonical_event_latency_ms",
        "decision.poll.duration_ms",
        "decision.lane.evaluation_total",
        "decision.publication.total",
        "decision.rebuild.total",
        "decision.rebuild.duration_ms",
    }
    observation.set_service_state("RUNNING")
    for value in _observations(meter, "decision.service.state"):
        assert set(value.attributes or {}) <= ALLOWED_METRIC_LABELS
        assert value.attributes == {"state": "RUNNING"}


def test_closed_interval_lag_is_timeframe_aware_and_grows_while_stalled() -> None:
    meter = _Meter()
    now = [BASE + timedelta(hours=3, minutes=45)]
    grid = TimeframeGrid(
        alignment_origin=BASE,
        durations={"1h": timedelta(hours=1), "4h": timedelta(hours=4)},
    )
    observation = DecisionObservability(
        meter=meter,
        timeframe_grid=grid,
        now_fn=lambda: now[0],
    )
    hourly = MarketSeriesKey(
        asset="BTCUSDT", venue="binance", instrument_id="BTCUSDT", timeframe="1h"
    )
    four_hour = MarketSeriesKey(
        asset="ETHUSDT", venue="binance", instrument_id="ETHUSDT", timeframe="4h"
    )
    observation.replace_generation(
        runtime=_runtime(
            hourly,
            lane_id="BTCUSDT:momentum_1h",
            lane_timeframe="1h",
            latest_input=BASE + timedelta(hours=3),
            latest_watermark=BASE + timedelta(hours=3),
        ),
        input_series={hourly: object()},
    )
    assert _observations(meter, "decision.input.closed_interval_lag")[0].value == 0
    assert (
        _observations(meter, "decision.lane.watermark_closed_interval_lag")[0].value
        == 0
    )

    observation.replace_generation(
        runtime=_runtime(
            four_hour,
            lane_id="ETHUSDT:momentum_4h",
            lane_timeframe="4h",
            latest_input=BASE,
            latest_watermark=BASE,
        ),
        input_series={four_hour: object()},
    )
    assert _observations(meter, "decision.input.closed_interval_lag")[0].value == 0
    assert (
        _observations(meter, "decision.lane.watermark_closed_interval_lag")[0].value
        == 0
    )

    now[0] = BASE + timedelta(hours=7, minutes=45)
    assert _observations(meter, "decision.input.closed_interval_lag")[0].value == 1


def test_generation_replacement_removes_retired_input_and_lane_series() -> None:
    meter = _Meter()
    observation = DecisionObservability(
        meter=meter,
        timeframe_grid=TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(hours=1)},
        ),
        now_fn=lambda: BASE + timedelta(hours=2),
    )
    btc = MarketSeriesKey(
        asset="BTCUSDT", venue="binance", instrument_id="BTCUSDT", timeframe="1h"
    )
    eth = MarketSeriesKey(
        asset="ETHUSDT", venue="binance", instrument_id="ETHUSDT", timeframe="1h"
    )
    observation.replace_generation(
        runtime=_runtime(
            btc,
            lane_id="BTCUSDT:momentum_1h",
            lane_timeframe="1h",
            latest_input=BASE,
            latest_watermark=BASE,
        ),
        input_series={btc: object()},
    )
    observation.replace_generation(
        runtime=_runtime(
            eth,
            lane_id="ETHUSDT:momentum_1h",
            lane_timeframe="1h",
            latest_input=BASE,
            latest_watermark=BASE,
        ),
        input_series={eth: object()},
    )

    input_labels = {
        tuple(item.attributes.items())
        for item in _observations(meter, "decision.input.blocked")
    }
    lane_labels = {
        tuple(item.attributes.items())
        for item in _observations(meter, "decision.lane.state")
    }
    assert (("asset", "ETHUSDT"), ("timeframe", "1h")) in input_labels
    assert all("BTCUSDT" not in str(labels) for labels in input_labels)
    assert (
        ("lane", "ETHUSDT:momentum_1h"),
        ("asset", "ETHUSDT"),
        ("timeframe", "1h"),
        ("state", "LIVE"),
    ) in lane_labels
    assert all("BTCUSDT" not in str(labels) for labels in lane_labels)


def test_all_input_dispositions_and_latency_are_recorded_without_transport_labels() -> (
    None
):
    meter = _Meter()
    observation = DecisionObservability(
        meter=meter,
        timeframe_grid=TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(hours=1)},
        ),
        now_fn=lambda: BASE + timedelta(minutes=2),
    )
    key = MarketSeriesKey(
        asset="BTCUSDT", venue="binance", instrument_id="BTCUSDT", timeframe="1h"
    )
    for disposition in (
        "INSERTED",
        "DUPLICATE",
        "ALREADY_REPRESENTED",
        "RECONSTRUCTION_REQUIRED",
        "CONFLICT",
        "MALFORMED",
    ):
        observation.record_input_result(
            SimpleNamespace(
                disposition=disposition,
                series_key=key,
                market_as_of=BASE,
                event=None,
            ),
            accepted_at=BASE + timedelta(minutes=2),
        )
    outcomes = {
        attrs["outcome"]
        for _value, attrs in meter.instruments["decision.input.records_total"].adds
    }
    assert outcomes == {
        "INSERTED",
        "DUPLICATE",
        "ALREADY_REPRESENTED",
        "RECONSTRUCTION_REQUIRED",
        "CONFLICT",
        "MALFORMED",
    }
    assert meter.instruments["decision.input.market_latency_ms"].records
    assert all(
        set(attributes) <= ALLOWED_METRIC_LABELS
        for _value, attributes in meter.instruments["decision.input.records_total"].adds
    )


def test_callbacks_read_cache_only_after_runtime_has_been_discarded() -> None:
    meter = _Meter()
    observation = DecisionObservability(
        meter=meter,
        timeframe_grid=TimeframeGrid(
            alignment_origin=BASE,
            durations={"1h": timedelta(hours=1)},
        ),
        now_fn=lambda: BASE + timedelta(hours=2),
    )
    key = MarketSeriesKey(
        asset="BTCUSDT", venue="binance", instrument_id="BTCUSDT", timeframe="1h"
    )
    observation.replace_generation(
        runtime=_runtime(
            key,
            lane_id="BTCUSDT:momentum_1h",
            lane_timeframe="1h",
            latest_input=BASE,
            latest_watermark=BASE,
        ),
        input_series={key: object()},
    )
    observation._inputs = {key: observation._inputs[key]}
    assert _observations(meter, "decision.input.closed_interval_lag")
    assert _observations(meter, "decision.lane.state")


def test_pipeline_dashboard_is_dynamic_and_matches_decision_surface() -> None:
    dashboard = json.loads(DASHBOARD_FILE.read_text(encoding="utf-8"))
    serialized = json.dumps(dashboard, sort_keys=True)
    assert "stream_lag_pending_messages" not in serialized
    assert "decision_generation_id" not in serialized
    for lane_id in (
        "BTCUSDT:momentum_1h",
        "BTCUSDT:momentum_4h",
        "ETHUSDT:momentum_4h",
    ):
        assert lane_id not in serialized
    variable_names = {
        variable["name"]
        for variable in dashboard["templating"]["list"]
        if variable.get("type") == "query"
    }
    assert {"decision_lane", "decision_asset", "decision_timeframe"} <= variable_names
    assert "decision_lane_state" in serialized
    assert "decision_input_closed_interval_lag" in serialized
    assert "decision_input_market_latency_ms" in serialized
    assert "decision_input_canonical_event_latency_ms" in serialized
