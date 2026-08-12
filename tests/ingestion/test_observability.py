from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID, Resource

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.observability import IngestionObservability
from scripts.certify_ingestion_observability_n1d import (
    OLDEST_PENDING_AGE_EXPRESSION,
)


class _Instrument:
    def __init__(self, name: str, *, callbacks=None) -> None:
        self.name = name
        self.callbacks = callbacks or []
        self.add_calls: list[tuple[object, dict | None]] = []
        self.record_calls: list[tuple[object, dict | None]] = []

    def add(self, value, attributes=None) -> None:
        self.add_calls.append((value, attributes))

    def record(self, value, attributes=None) -> None:
        self.record_calls.append((value, attributes))


class _Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, _Instrument] = {}

    def _create(self, name: str, **kwargs):
        instrument = _Instrument(name, callbacks=kwargs.get("callbacks"))
        self.instruments[name] = instrument
        return instrument

    create_counter = _create
    create_histogram = _create
    create_observable_gauge = _create


class _Span:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[Exception] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value

    def record_exception(self, exc: Exception) -> None:
        self.exceptions.append(exc)


class _Tracer:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, object], _Span]] = []

    @contextmanager
    def start_as_current_span(self, name: str, *, attributes):
        span = _Span()
        self.spans.append((name, attributes, span))
        yield span


def test_instruments_use_required_names_and_bounded_commit_attributes() -> None:
    meter = _Meter()
    observability = IngestionObservability(meter=meter, tracer=_Tracer())

    observability.record_candle_commit(
        timeframe="1m",
        source_type="provider",
        outcome="conflict",
        duration_ms=2.5,
    )

    commit = meter.instruments["ingestion.candle.commit_total"]
    assert commit.add_calls == [
        (
            1,
            {
                "timeframe": "1m",
                "source_type": "provider",
                "outcome": "conflict",
            },
        )
    ]
    assert set(meter.instruments) == {
        "ingestion.candle.commit_total",
        "ingestion.candle.commit.duration_ms",
        "ingestion.base.last_close_timestamp_seconds",
        "ingestion.websocket.connected",
        "ingestion.websocket.reconnect_total",
        "ingestion.websocket.interruption_total",
        "ingestion.websocket.queue_utilization",
        "ingestion.recovery.total",
        "ingestion.recovery.duration_ms",
        "ingestion.outbox.pending",
        "ingestion.outbox.oldest_pending_timestamp_seconds",
        "ingestion.outbox.publish_total",
        "ingestion.outbox.publish_failure_total",
        "ingestion.outbox.publish_batch_size",
        "ingestion.outbox.publish.duration_ms",
        "ingestion.runtime.live",
    }


def test_gauges_track_freshness_queue_runtime_and_outbox_state() -> None:
    meter = _Meter()
    observability = IngestionObservability(meter=meter, tracer=_Tracer())
    close_time = datetime(2026, 8, 11, 12, 1, tzinfo=UTC)
    lane = MarketLane("binance", "S0000-USDT-PERP", "1m")

    observability.record_base_last_close(lane, close_time)
    observability.set_queue_utilization(500, 1000)
    observability.set_runtime_live(True)
    observability.set_outbox_state(
        pending=2,
        oldest_pending=close_time - timedelta(minutes=2),
    )

    freshness = tuple(
        meter.instruments["ingestion.base.last_close_timestamp_seconds"].callbacks[0](
            None
        )
    )
    assert freshness[0].value == close_time.timestamp()
    assert freshness[0].attributes == {
        "venue": "binance",
        "instrument_id": "S0000-USDT-PERP",
    }
    assert (
        meter.instruments["ingestion.websocket.queue_utilization"]
        .callbacks[0](None)[0]
        .value
        == 0.5
    )
    assert meter.instruments["ingestion.runtime.live"].callbacks[0](None)[0].value == 1
    assert (
        meter.instruments["ingestion.outbox.pending"].callbacks[0](None)[0].value == 2
    )

    observability.record_outbox_published()
    observability.record_outbox_insert(close_time)
    assert (
        meter.instruments["ingestion.outbox.pending"].callbacks[0](None)[0].value == 2
    )


def test_recovery_and_publication_spans_keep_lane_data_out_of_metrics() -> None:
    meter = _Meter()
    tracer = _Tracer()
    observability = IngestionObservability(meter=meter, tracer=tracer)
    request = RecoveryRequest(
        lane=MarketLane("binance", "S0000-USDT-PERP", "1m"),
        since=datetime(2026, 8, 11, 12, tzinfo=UTC),
        until=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        reason="runtime_catchup",
    )

    with observability.recovery_span(request):
        pass
    observability.record_recovery(outcome="success", duration_ms=4.0)
    with observability.outbox_publish_span(3) as span:
        span.set_attribute("successful_publishes", 2)

    assert tracer.spans[0][0] == "ingestion.recovery"
    assert tracer.spans[0][1]["instrument_id"] == "S0000-USDT-PERP"
    assert tracer.spans[1][0] == "ingestion.outbox.publish_batch"
    assert tracer.spans[1][2].attributes["successful_publishes"] == 2
    assert meter.instruments["ingestion.recovery.total"].add_calls == [
        (1, {"outcome": "success"})
    ]


def test_fastapi_instrumentation_excludes_health_routes() -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    from apps.ingestion_app.api.app import create_app

    with patch.object(FastAPIInstrumentor, "instrument_app") as instrument_app:
        create_app()

    instrument_app.assert_called_once()
    assert instrument_app.call_args.kwargs["excluded_urls"] == r"/health/(live|ready)$"


def test_ingestion_compose_uses_standard_stable_otel_instance_identity(
    monkeypatch,
) -> None:
    compose = yaml.safe_load(
        (Path(__file__).parents[2] / "docker-compose.yml").read_text(encoding="utf-8")
    )
    environment = compose["services"]["ingestion"]["environment"]
    assert (
        environment["OTEL_RESOURCE_ATTRIBUTES"]
        == "service.instance.id=${INGESTION_OTEL_INSTANCE_ID:-ingestion-local}"
    )

    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "service.instance.id=ingestion-test",
    )
    resource = Resource.create(
        {
            "service.name": "ingestion",
            "service.version": "0.1.0",
        }
    )
    assert resource.attributes[SERVICE_INSTANCE_ID] == "ingestion-test"


def test_oldest_pending_dashboard_expression_masks_empty_backlog() -> None:
    dashboard = json.loads(
        (
            Path(__file__).parents[2]
            / "configs/observability/grafana/provisioning/dashboards/ingestion.json"
        ).read_text(encoding="utf-8")
    )
    panel = next(
        panel
        for panel in dashboard["panels"]
        if panel["title"] == "Oldest Pending Outbox Age"
    )
    expression = panel["targets"][0]["expr"]
    assert expression == OLDEST_PENDING_AGE_EXPRESSION
    assert "> bool 0" in expression

    def displayed_age(now: float, oldest: float, pending: int) -> float:
        return (now - oldest) * (1 if pending > 0 else 0)

    assert displayed_age(1_000, 0, 0) == 0
    assert displayed_age(1_000, 900, 2) == 100
