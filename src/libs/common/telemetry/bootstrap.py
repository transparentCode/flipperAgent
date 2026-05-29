"""Shared OpenTelemetry bootstrap for all flipperAgent apps."""

from __future__ import annotations

import os
from typing import Optional

import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter


def init_telemetry(
    service_name: str,
    service_version: str = "0.1.0",
    otlp_endpoint: Optional[str] = None,
) -> tuple[trace.Tracer, metrics.Meter]:
    """Initialize OTel TracerProvider + MeterProvider.

    Call once at app startup (in main.py) before any instrumentation runs.

    Args:
        service_name: e.g. "ingestion_app", "signal_app"
        service_version: semver of the app
        otlp_endpoint: gRPC endpoint for OTel Collector.
            Falls back to OTEL_EXPORTER_OTLP_ENDPOINT env var,
            then "http://otel-collector:4317".

    Returns:
        (tracer, meter) tuple for the calling app to use.
    """
    endpoint = (
        otlp_endpoint
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or "http://otel-collector:4317"
    )

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
    })

    # --- Traces ---
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    # Debug: also print spans to stdout so they appear in docker logs
    if os.environ.get("OTEL_DEBUG"):
        tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)
    tracer = trace.get_tracer(service_name, service_version)

    # --- Metrics ---
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, insecure=True),
        export_interval_millis=15_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter(service_name, service_version)

    # --- Logs ---
    log_provider = LoggerProvider(resource=resource)
    log_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint, insecure=True))
    )
    otel_handler = LoggingHandler(
        level=logging.NOTSET,
        logger_provider=log_provider,
    )
    # Store the handler so it can be attached after configure_logging().
    # Don't add to root logger here — the namespace logger has propagate=False,
    # so root-level handlers never see app logs.
    global _otel_log_handler  # noqa: PLW0603
    _otel_log_handler = otel_handler

    return tracer, meter


# Module-level storage for the OTel log handler created by init_telemetry().
_otel_log_handler: LoggingHandler | None = None


def attach_otel_log_handler(namespace: str = "flipper_agent") -> None:
    """Attach the OTel LoggingHandler to the given namespace logger.

    Call this AFTER configure_logging() so the handler isn't cleared.
    """
    if _otel_log_handler is not None:
        logging.getLogger(namespace).addHandler(_otel_log_handler)
