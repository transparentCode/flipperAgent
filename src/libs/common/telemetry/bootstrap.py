"""Shared OpenTelemetry bootstrap for all flipperAgent apps."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional
from collections.abc import Mapping

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

from libs.common.paths import PROJECT_ROOT, get_logs_dir

_OTEL_INTERNAL_LOGGER_NAMES = (
    "opentelemetry",
    "opentelemetry.sdk",
    "opentelemetry.exporter",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto.grpc",
    "grpc",
    "grpc._channel",
)
_OTEL_INTERNAL_DEFAULTS = {
    "enabled": True,
    "level": "WARNING",
    "file": "logs/otel-internal.log",
    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
}


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_level(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return default
    normalized = str(value).strip().upper()
    return logging.getLevelNamesMapping().get(normalized, default)


def _resolve_otel_internal_log_path(value: object) -> Path:
    if value in (None, ""):
        return get_logs_dir(create=True) / "otel-internal.log"
    candidate = Path(str(value))
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def _otel_internal_logging_settings(
    overrides: Mapping[str, object] | None = None,
) -> dict[str, object]:
    overrides = overrides or {}
    env_enabled = os.environ.get("OTEL_INTERNAL_LOG_ENABLED")
    env_level = os.environ.get("OTEL_INTERNAL_LOG_LEVEL")
    env_file = os.environ.get("OTEL_INTERNAL_LOG_FILE")
    env_format = os.environ.get("OTEL_INTERNAL_LOG_FORMAT")

    return {
        "enabled": overrides.get(
            "enabled",
            env_enabled if env_enabled is not None else _OTEL_INTERNAL_DEFAULTS["enabled"],
        ),
        "level": overrides.get(
            "level",
            env_level if env_level is not None else _OTEL_INTERNAL_DEFAULTS["level"],
        ),
        "file": overrides.get(
            "file",
            env_file if env_file is not None else _OTEL_INTERNAL_DEFAULTS["file"],
        ),
        "format": overrides.get(
            "format",
            env_format if env_format is not None else _OTEL_INTERNAL_DEFAULTS["format"],
        ),
    }


def _clear_otel_internal_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, "_flipper_otel_internal", False):
            continue
        logger.removeHandler(handler)
        handler.close()


def _configure_otel_internal_logging(overrides: Mapping[str, object] | None = None) -> None:
    settings = _otel_internal_logging_settings(overrides)
    enabled = _coerce_bool(settings["enabled"], True)

    for logger_name in _OTEL_INTERNAL_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        _clear_otel_internal_handlers(logger)

        if not enabled:
            logger.propagate = True
            continue

        handler = logging.FileHandler(_resolve_otel_internal_log_path(settings["file"]))
        handler._flipper_otel_internal = True  # type: ignore[attr-defined]
        handler.setLevel(_coerce_level(settings["level"], logging.WARNING))
        handler.setFormatter(logging.Formatter(str(settings["format"])))
        logger.addHandler(handler)
        logger.setLevel(min(logger.level, logging.WARNING) if logger.level else logging.WARNING)
        logger.propagate = False


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
    _configure_otel_internal_logging()

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
