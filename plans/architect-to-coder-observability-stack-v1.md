---
goal: Add OpenTelemetry + Grafana LGTM observability stack with end-to-end trace propagation through Valkey streams
stage: architect-to-coder
date_created: 2026-05-29
last_updated: 2026-05-29
owner: Quant Research Architect
status: Ready
tags: [handoff, infrastructure, observability, opentelemetry, grafana, tracing]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: Observability Stack (OTel + Grafana LGTM)

## 1. Objective

Instrument the entire flipperAgent pipeline with OpenTelemetry (traces, metrics, logs) and deploy a Grafana LGTM stack (Loki, Grafana, Tempo, Mimir/Prometheus) within the existing Docker Compose topology. The critical design goal is **end-to-end distributed tracing**: a single trace must follow a message from `ingestion_app` → `signal_app` → `strategy_app` → `risk_app` → `execution_app` → `portfolio_app` by propagating W3C `traceparent` headers through Valkey stream payloads.

## 2. Scope Boundaries

### In Scope
- Shared OTel bootstrap utility in `src/libs/common/telemetry/`
- W3C trace context injection into `valkey_encode()` and extraction from `valkey_decode()`
- `BaseStreamConsumer` instrumented with span creation and context extraction
- Per-app OTel initialization in each `main.py`
- RED metrics (Rate, Errors, Duration) per app + Valkey stream lag gauge
- OTel Collector, Tempo, Loki, Prometheus, Grafana added to `docker-compose.yml`
- Config files for each infrastructure component in `configs/observability/`
- Grafana dashboard provisioning (datasources + pipeline health dashboard)
- FastAPI auto-instrumentation for `api_app`
- OTel log bridge connecting existing `JsonFormatter` output to Loki

### Out of Scope (Non-Goals)
- Alerting rules (follow-up task after dashboards are validated)
- Custom Grafana plugins or advanced dashboard widgets
- Jaeger or Zipkin (Tempo is the sole trace backend)
- Application-level profiling (e.g., py-spy)
- Changes to business logic in any worker
- Persistent storage volumes for observability data (ephemeral 3-day retention is acceptable)
- SSL/TLS for observability inter-service communication (all on `flipper-net` bridge)

## 3. Affected Symbols, Modules, and Execution Flows

### Files Created (New)

| File | Purpose |
|------|---------|
| `src/libs/common/telemetry/__init__.py` | Package marker |
| `src/libs/common/telemetry/bootstrap.py` | Shared OTel TracerProvider + MeterProvider + LoggerProvider init |
| `src/libs/common/telemetry/propagation.py` | `inject_trace_context()` / `extract_trace_context()` helpers for Valkey payloads |
| `src/libs/common/telemetry/metrics.py` | Per-app metric instrument factories |
| `configs/observability/otel-collector.yaml` | OTel Collector pipeline config |
| `configs/observability/tempo.yaml` | Tempo config |
| `configs/observability/loki.yaml` | Loki config |
| `configs/observability/prometheus.yml` | Prometheus scrape config |
| `configs/observability/grafana/provisioning/datasources/datasources.yaml` | Grafana datasource provisioning |
| `configs/observability/grafana/provisioning/dashboards/dashboards.yaml` | Grafana dashboard provisioning config |
| `configs/observability/grafana/provisioning/dashboards/pipeline-health.json` | Pre-built pipeline health dashboard |

### Files Modified (Existing)

| File | Change |
|------|--------|
| `src/libs/contracts/serialization.py` | `valkey_encode()` gains optional `inject_trace=True` param; `valkey_decode()` returns trace context alongside model |
| `src/libs/common/stream_consumer.py` | `process_message()` wrapper creates child span from extracted `traceparent`; adds duration histogram + error counter |
| `src/libs/common/logging/logger_utils.py` | `JsonFormatter` adds `trace_id` and `span_id` from OTel context; optional OTel LoggerProvider bridge |
| `src/apps/ingestion_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/signal_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/strategy_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/risk_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/execution_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/portfolio_app/main.py` | Call `init_telemetry()` at startup |
| `src/apps/api_app/app.py` | Add FastAPI OTel auto-instrumentation in `create_app()` |
| `src/apps/signal_app/signal_worker.py` | Inject trace context into `xadd` payloads |
| `src/apps/strategy_app/strategy_worker.py` | Inject trace context into `xadd` payloads |
| `src/apps/risk_app/risk_worker.py` | Inject trace context into `xadd` payloads |
| `src/apps/execution_app/execution_worker.py` | Inject trace context into `xadd` payloads |
| `src/apps/ingestion_app/orchestration/controller.py` | Inject trace context into `xadd` payloads |
| `docker-compose.yml` | Add 5 new services + `OTEL_EXPORTER_OTLP_ENDPOINT` env var to all app services |
| `pyproject.toml` | Add OTel dependencies |

### Execution Flows Affected
- **Primary pipeline**: ingestion → ohlcv stream → signal_app → features stream → strategy_app → signals stream → risk_app → orders stream → execution_app → fills stream → portfolio_app
- **Price heartbeat flow**: signal_app → price_update stream → risk_app (SL/TP)
- **API server**: FastAPI HTTP request handling (auto-instrumented)

## 4. OTel Bootstrap Pattern

### `src/libs/common/telemetry/bootstrap.py`

```python
"""Shared OpenTelemetry bootstrap for all flipperAgent apps."""

from __future__ import annotations

import os
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter


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

    return tracer, meter
```

### Per-App Initialization (e.g., `signal_app/main.py`)

Add **before** `configure_logging()`:

```python
from libs.common.telemetry.bootstrap import init_telemetry

tracer, meter = init_telemetry("signal_app")
```

The `tracer` and `meter` objects can be passed to workers or accessed via `trace.get_tracer("signal_app")` / `metrics.get_meter("signal_app")` anywhere.

### FastAPI Auto-Instrumentation (`api_app/app.py`)

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from libs.common.telemetry.bootstrap import init_telemetry

# In create_app(), after FastAPI() construction:
init_telemetry("api_app")
FastAPIInstrumentor.instrument_app(app)
```

## 5. Trace Propagation Through Valkey Streams

This is the most critical design decision. W3C `traceparent` must flow through Valkey stream messages so downstream consumers create child spans under the same trace.

### `src/libs/common/telemetry/propagation.py`

```python
"""W3C trace context propagation through Valkey stream payloads."""

from __future__ import annotations

from typing import Optional

from opentelemetry import context, trace
from opentelemetry.propagators.textmap import (
    CarrierT,
    Getter,
    Setter,
    TextMapPropagator,
)
from opentelemetry.propagate import get_global_textmap_propagator


# Key used in Valkey flat-map payloads to carry the traceparent header
TRACEPARENT_KEY = "_traceparent"
TRACESTATE_KEY = "_tracestate"


class DictSetter(Setter):
    def set(self, carrier: dict, key: str, value: str) -> None:
        carrier[key] = value


class DictGetter(Getter):
    def get(self, carrier: dict, key: str) -> Optional[list[str]]:
        val = carrier.get(key)
        if val is None:
            return None
        return [val]

    def keys(self, carrier: dict) -> list[str]:
        return list(carrier.keys())


_setter = DictSetter()
_getter = DictGetter()


def inject_trace_context(payload: dict[str, str]) -> dict[str, str]:
    """Inject current span's trace context into a Valkey payload dict.

    Adds `_traceparent` (and optionally `_tracestate`) keys.
    Safe to call even if no active span — will be a no-op.
    """
    get_global_textmap_propagator().inject(
        carrier=payload,
        setter=_setter,
    )
    # The propagator writes "traceparent" / "tracestate" keys.
    # Rename to underscore-prefixed to avoid collisions with model fields.
    if "traceparent" in payload:
        payload[TRACEPARENT_KEY] = payload.pop("traceparent")
    if "tracestate" in payload:
        payload[TRACESTATE_KEY] = payload.pop("tracestate")
    return payload


def extract_trace_context(payload: dict[str, str]) -> context.Context:
    """Extract trace context from a Valkey payload dict.

    Returns an OTel Context that should be used as the parent for new spans.
    """
    # Rename underscore-prefixed keys back to standard names for the propagator
    carrier: dict[str, str] = {}
    if TRACEPARENT_KEY in payload:
        carrier["traceparent"] = payload[TRACEPARENT_KEY]
    if TRACESTATE_KEY in payload:
        carrier["tracestate"] = payload[TRACESTATE_KEY]
    return get_global_textmap_propagator().extract(
        carrier=carrier,
        getter=_getter,
    )
```

### Modification to `valkey_encode()` in `src/libs/contracts/serialization.py`

```python
def valkey_encode(model: BaseModel, *, inject_trace: bool = True) -> dict[str, str]:
    """Serialize a Pydantic model to a flat dict[str, str] suitable for Valkey XADD.
    
    If inject_trace=True (default), injects W3C traceparent into the payload.
    """
    payload: dict[str, str] = {}
    for key, value in model.model_dump().items():
        if value is None:
            payload[key] = _NONE_SENTINEL
        elif isinstance(value, Enum):
            payload[key] = str(value.value)
        elif isinstance(value, (dict, list)):
            payload[key] = _json.dumps(value)
        else:
            payload[key] = str(value)
    
    if inject_trace:
        try:
            from libs.common.telemetry.propagation import inject_trace_context
            inject_trace_context(payload)
        except ImportError:
            pass  # OTel not installed — graceful degradation
    
    return payload
```

### Modification to `valkey_decode()` in `src/libs/contracts/serialization.py`

No signature change needed. The `_traceparent` and `_tracestate` keys are automatically ignored by `valkey_decode()` because they are not in the model's `model_fields` — they pass through to `parsed` as extra keys, but `model_validate()` ignores unknown fields by default in Pydantic v2.

However, `BaseStreamConsumer` extracts the context **before** calling `valkey_decode()`. See next section.

### Modification to `BaseStreamConsumer` in `src/libs/common/stream_consumer.py`

```python
async def run(self) -> None:
    """Main consumer loop with error recovery and OTel tracing."""
    if not self.redis_client:
        logger.warning(f"No redis client for {self.stream_key} — consumer inactive")
        return

    logger.info(f"Listening to stream {self.stream_key} via XREADGROUP...")

    # --- Attempt OTel setup (graceful if not available) ---
    _tracer = None
    _msg_duration = None
    _msg_counter = None
    _error_counter = None
    try:
        from opentelemetry import trace as _trace, metrics as _metrics
        from libs.common.telemetry.propagation import extract_trace_context
        _tracer = _trace.get_tracer(__name__)
        _meter = _metrics.get_meter(__name__)
        _msg_duration = _meter.create_histogram(
            "stream.message.duration_ms",
            description="Time to process a single stream message",
            unit="ms",
        )
        _msg_counter = _meter.create_counter(
            "stream.message.processed_total",
            description="Total messages processed",
        )
        _error_counter = _meter.create_counter(
            "stream.message.error_total",
            description="Total message processing errors",
        )
    except ImportError:
        extract_trace_context = None

    # ... (PEL drain section unchanged) ...

    streams = {self.stream_key: ">"}

    while True:
        try:
            response = await self.redis_client.xreadgroup(...)
            if not response:
                continue

            for stream_name, messages in response:
                for message_id, data in messages:
                    try:
                        # --- Extract trace context and create child span ---
                        parent_ctx = None
                        if _tracer and extract_trace_context:
                            parent_ctx = extract_trace_context(data)
                        
                        span_ctx = parent_ctx if parent_ctx else None
                        
                        if _tracer:
                            import time as _time
                            _start = _time.monotonic()
                            with _tracer.start_as_current_span(
                                f"{self.stream_key}.process",
                                context=span_ctx,
                                attributes={
                                    "messaging.system": "valkey",
                                    "messaging.destination": self.stream_key,
                                    "messaging.message_id": message_id,
                                    "messaging.consumer_group": self.group_name,
                                },
                            ):
                                await self.process_message(message_id, data)
                            _elapsed = (_time.monotonic() - _start) * 1000
                            if _msg_duration:
                                _msg_duration.record(_elapsed, {"stream": self.stream_key})
                            if _msg_counter:
                                _msg_counter.add(1, {"stream": self.stream_key})
                        else:
                            await self.process_message(message_id, data)
                        
                        await self.redis_client.xack(
                            self.stream_key, self.group_name, message_id
                        )
                    except Exception:
                        if _error_counter:
                            _error_counter.add(1, {"stream": self.stream_key})
                        logger.exception(
                            f"Error processing message {message_id} from {self.stream_key}"
                        )
        except asyncio.CancelledError:
            logger.info(f"Consumer {self.consumer_name} cancelled")
            break
        except Exception:
            logger.exception(f"Stream read error on {self.stream_key}")
            await asyncio.sleep(1)
```

### XADD Side — Injecting Trace Context at Publish Points

Every `xadd` call that uses `valkey_encode()` already gets trace injection for free (via the `inject_trace=True` default). **No changes needed** at individual `xadd` call sites in signal_worker, strategy_worker, risk_worker, or execution_worker.

For the **ingestion controller** (`controller.py`) which uses `pipe.xadd()` inside a pipeline, ensure the payload dict is constructed via `valkey_encode()` or manually call `inject_trace_context(payload)` before adding to the pipeline.

### Trace Flow Diagram

```
ingestion_app                 signal_app                  strategy_app
┌──────────┐                ┌───────────┐               ┌──────────────┐
│ Span A   │─traceparent──▶│ Span B     │─traceparent──▶│ Span C       │
│ (root)   │  via XADD     │ (child A)  │  via XADD     │ (child A)    │
└──────────┘                └───────────┘               └──────────────┘
                                                               │
                                                               ▼ traceparent via XADD
                            ┌───────────┐               ┌──────────────┐
                            │ Span E    │◀─traceparent──│ Span D       │
                            │ (child A) │   via XADD    │ (child A)    │
                            └───────────┘               └──────────────┘
                          execution_app                   risk_app
                                │
                                ▼ traceparent via XADD
                          ┌───────────┐
                          │ Span F    │
                          │ (child A) │
                          └───────────┘
                         portfolio_app

All spans share Trace ID from Span A → visible as one waterfall in Tempo.
```

## 6. Metrics per App

### `src/libs/common/telemetry/metrics.py`

```python
"""Standard metric instruments for flipperAgent apps."""

from __future__ import annotations

from opentelemetry import metrics


def create_app_metrics(meter: metrics.Meter, app_name: str) -> dict:
    """Create standard RED metrics + stream-specific gauges.
    
    Returns a dict of instrument references keyed by name.
    """
    return {
        # Rate
        "messages_processed": meter.create_counter(
            f"{app_name}.messages.processed_total",
            description=f"Total messages processed by {app_name}",
        ),
        # Errors
        "messages_errored": meter.create_counter(
            f"{app_name}.messages.error_total",
            description=f"Total processing errors in {app_name}",
        ),
        # Duration
        "message_duration": meter.create_histogram(
            f"{app_name}.message.duration_ms",
            description=f"Message processing duration in {app_name}",
            unit="ms",
        ),
        # Stream lag (observable gauge — callback-based)
        # Registered separately per stream via create_stream_lag_gauge()
    }


def create_stream_lag_callback(redis_client, stream_key: str, group_name: str):
    """Return an async callback that reads XPENDING to report stream lag."""
    async def _observe(options):
        try:
            info = await redis_client.xpending(stream_key, group_name)
            # info[0] = count of pending messages
            pending_count = info[0] if info else 0
            return [
                metrics.Observation(
                    pending_count,
                    {"stream": stream_key, "group": group_name},
                )
            ]
        except Exception:
            return []
    return _observe
```

### Per-App Metric Summary

| App | Key Metrics |
|-----|------------|
| **All apps** (via BaseStreamConsumer) | `stream.message.duration_ms`, `stream.message.processed_total`, `stream.message.error_total` |
| **ingestion_app** | `ingestion.candles_ingested_total`, `ingestion.ws_reconnect_total`, `ingestion.backfill_duration_ms` |
| **signal_app** | `signal.features_computed_total`, `signal.indicator_priming_duration_ms`, `signal.indicator_errors_total` |
| **strategy_app** | `strategy.signals_published_total`, `strategy.model_evaluation_duration_ms`, `strategy.selection_filtered_total` |
| **risk_app** | `risk.orders_published_total`, `risk.signals_rejected_total`, `risk.sl_tp_triggered_total` |
| **execution_app** | `execution.fills_published_total`, `execution.order_latency_ms`, `execution.paper_balance` |
| **portfolio_app** | `portfolio.equity_snapshots_total`, `portfolio.positions_active` (gauge) |
| **api_app** | Auto-instrumented by `FastAPIInstrumentor`: `http.server.duration`, `http.server.request.size`, `http.server.response.size` |
| **Stream lag** (all) | `stream.lag.pending_messages` (observable gauge per stream/group) |

## 7. Docker Compose Additions

### New Services in `docker-compose.yml`

```yaml
  # ---- Observability Stack ----

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.104.0
    command: ["--config=/etc/otel/config.yaml"]
    volumes:
      - ./configs/observability/otel-collector.yaml:/etc/otel/config.yaml:ro
    ports:
      - "127.0.0.1:4317:4317"   # gRPC OTLP receiver
      - "127.0.0.1:4318:4318"   # HTTP OTLP receiver
      - "127.0.0.1:8888:8888"   # Collector metrics
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.15'
    networks:
      - flipper-net

  tempo:
    image: grafana/tempo:2.5.0
    command: ["-config.file=/etc/tempo/config.yaml"]
    volumes:
      - ./configs/observability/tempo.yaml:/etc/tempo/config.yaml:ro
      - tempo-data:/var/tempo
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.1'
    networks:
      - flipper-net

  loki:
    image: grafana/loki:3.1.0
    command: ["-config.file=/etc/loki/config.yaml"]
    volumes:
      - ./configs/observability/loki.yaml:/etc/loki/config.yaml:ro
      - loki-data:/loki
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.1'
    networks:
      - flipper-net

  prometheus:
    image: prom/prometheus:v2.53.0
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=3d"
      - "--storage.tsdb.retention.size=50MB"
    volumes:
      - ./configs/observability/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.1'
    networks:
      - flipper-net

  grafana:
    image: grafana/grafana:11.1.0
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-flipper}
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - ./configs/observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - grafana-data:/var/lib/grafana
    depends_on:
      - tempo
      - loki
      - prometheus
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: '0.15'
    networks:
      - flipper-net
```

### New Volumes

```yaml
volumes:
  # ... existing ...
  tempo-data:
  loki-data:
  prometheus-data:
  grafana-data:
```

### Environment Variable Addition to All App Services

Add to every app service (`worker-streams`, `signal-worker`, `strategy-worker`, `risk-worker`, `execution-worker`, `portfolio-worker`, `api-server`, `worker-queue`):

```yaml
    environment:
      # ... existing vars ...
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_SERVICE_NAME: <service_name>  # e.g. "ingestion_app"
```

### Resource Budget Summary

| Service | Memory | CPU |
|---------|--------|-----|
| otel-collector | 256 MB | 0.15 |
| tempo | 256 MB | 0.1 |
| loki | 256 MB | 0.1 |
| prometheus | 256 MB | 0.1 |
| grafana | 256 MB | 0.15 |
| **Total** | **1280 MB** | **0.6 cores** |

Within the agreed ~700 MB–1.4 GB RAM / 0.5–0.7 CPU budget.

## 8. Config Files

### `configs/observability/otel-collector.yaml`

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024

exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write

  loki:
    endpoint: http://loki:3100/loki/api/v1/push

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [otlp/tempo]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheusremotewrite]
    logs:
      receivers: [otlp]
      processors: [batch]
      exporters: [loki]
```

### `configs/observability/tempo.yaml`

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces
    wal:
      path: /var/tempo/wal

compactor:
  compaction:
    block_retention: 72h  # 3-day retention

metrics_generator:
  registry:
    external_labels:
      source: tempo
  storage:
    path: /var/tempo/generator/wal
```

### `configs/observability/loki.yaml`

```yaml
auth_enabled: false

server:
  http_listen_port: 3100

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

limits_config:
  retention_period: 72h  # 3-day retention

schema_config:
  configs:
    - from: "2024-01-01"
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

compactor:
  working_directory: /loki/compactor
  retention_enabled: true
```

### `configs/observability/prometheus.yml`

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

remote_write:
  - url: http://localhost:9090/api/v1/write

scrape_configs:
  - job_name: "otel-collector"
    static_configs:
      - targets: ["otel-collector:8888"]

  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

Note: Prometheus receives metrics from OTel Collector via remote-write. The scrape configs are for Prometheus's own metrics and the collector's self-metrics. App metrics flow through OTLP → Collector → Prometheus remote-write.

### `configs/observability/grafana/provisioning/datasources/datasources.yaml`

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    editable: false
    jsonData:
      tracesToLogs:
        datasourceUid: loki
        tags: ["service.name"]
        mappedTags: [{ key: "service.name", value: "service_name" }]
        mapTagNamesEnabled: true
        filterByTraceID: true
      nodeGraph:
        enabled: true

  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    editable: false
    jsonData:
      derivedFields:
        - datasourceUid: tempo
          matcherRegex: '"trace_id":"(\w+)"'
          name: TraceID
          url: "$${__value.raw}"
```

### `configs/observability/grafana/provisioning/dashboards/dashboards.yaml`

```yaml
apiVersion: 1

providers:
  - name: "flipperAgent"
    orgId: 1
    folder: "flipperAgent"
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards
      foldersFromFilesStructure: false
```

### Dashboard JSON (`pipeline-health.json`)

The coder should create a Grafana dashboard JSON with these panels:

1. **Pipeline Message Rate** — `sum(rate(stream_message_processed_total[5m])) by (service_name)` — timeseries
2. **Pipeline Error Rate** — `sum(rate(stream_message_error_total[5m])) by (service_name)` — timeseries
3. **Message Processing Latency (p50/p95/p99)** — histogram quantiles from `stream_message_duration_ms` — timeseries
4. **Stream Lag (Pending Messages)** — `stream_lag_pending_messages` by stream — gauge panel
5. **Active Traces** — Tempo search panel — table
6. **Recent Logs** — Loki log panel filtered by `{service_name=~".+"}` — logs panel
7. **Per-App Status** — stat panels showing last-1m processed count per app

The dashboard JSON is ~300-400 lines; generate it programmatically or use Grafana's export feature after manual creation. The key requirement is that it is **provisioned automatically** when Grafana starts.

## 9. Existing Code Modifications — Detail

### `src/libs/common/logging/logger_utils.py`

Modify `JsonFormatter.format()` to inject OTel trace/span IDs when available:

```python
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        for field in DEFAULT_CONTEXT_FIELDS:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        # Inject OTel trace context if available
        try:
            from opentelemetry import trace as _trace
            span = _trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.trace_id:
                log_data["trace_id"] = format(ctx.trace_id, "032x")
                log_data["span_id"] = format(ctx.span_id, "016x")
        except ImportError:
            pass
                
        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)
            
        return json.dumps(log_data)
```

This enables **Loki → Tempo** trace correlation: click a trace_id in Loki logs to jump to the Tempo waterfall.

### `docker-compose.yml` — App Service Environment Changes

For each app service, add `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`:

```yaml
  worker-streams:  # ingestion_app
    environment:
      # ... existing ...
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
      OTEL_SERVICE_NAME: ingestion_app
    depends_on:
      # ... existing ...
      otel-collector:
        condition: service_started
```

Repeat for all 7 app services (`worker-streams`, `signal-worker`, `strategy-worker`, `risk-worker`, `execution-worker`, `portfolio-worker`, `api-server`).

## 10. Dependencies

Add to `pyproject.toml` under `[project.dependencies]`:

```toml
    # OpenTelemetry
    "opentelemetry-api>=1.25.0",
    "opentelemetry-sdk>=1.25.0",
    "opentelemetry-exporter-otlp-proto-grpc>=1.25.0",
    "opentelemetry-instrumentation-fastapi>=0.46b0",
```

Note: `grpcio` is pulled in transitively by the OTLP gRPC exporter.

## 11. Phased Rollout

### Phase 1: Infrastructure + Bootstrap (no app changes)
1. Create `configs/observability/` directory and all config files
2. Add 5 observability services to `docker-compose.yml`
3. Add new volumes
4. Create `src/libs/common/telemetry/` package with `bootstrap.py`, `propagation.py`, `metrics.py`
5. Add OTel dependencies to `pyproject.toml`
6. Rebuild Docker image
7. **Validate**: `docker compose up`, Grafana reachable at `:3000`, datasources provisioned

### Phase 2: Tracing + Propagation (core instrumentation)
1. Modify `valkey_encode()` to inject trace context
2. Modify `BaseStreamConsumer.run()` to extract context and create spans
3. Add `init_telemetry()` calls to all 7 app `main.py` files
4. Add `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_SERVICE_NAME` env vars to Docker Compose
5. Add FastAPI auto-instrumentation to `api_app`
6. **Validate**: Trigger ingestion, see end-to-end trace in Tempo waterfall

### Phase 3: Metrics + Logs + Dashboards
1. Add per-app custom metrics (counters/histograms from metrics table above)
2. Modify `JsonFormatter` to inject OTel trace/span IDs
3. Create and provision the Grafana dashboard JSON
4. Wire stream lag observable gauges
5. **Validate**: Dashboard shows live data, Loki logs link to Tempo traces

### Phase 4: Hardening
1. Add `depends_on: otel-collector` to all app services
2. Test graceful degradation: stop OTel Collector, verify apps still run without errors
3. Test PEL drain with tracing enabled
4. Add health checks for observability services
5. Update `docs/docker_topology.md` with observability architecture

## 12. Acceptance Criteria

- [ ] `docker compose up` starts all 5 observability services without errors
- [ ] Grafana accessible at `localhost:3000` with Prometheus, Tempo, Loki datasources auto-provisioned
- [ ] Triggering a pipeline run (ingestion → portfolio) produces a single trace visible in Tempo with spans for each app
- [ ] Trace waterfall shows correct parent-child relationships across all 6 pipeline stages
- [ ] `stream.message.processed_total` and `stream.message.duration_ms` metrics visible in Prometheus/Grafana
- [ ] Structured JSON logs in Loki include `trace_id` and `span_id` fields
- [ ] Clicking `trace_id` in Loki navigates to the corresponding Tempo trace
- [ ] Pipeline health dashboard loads with real data
- [ ] Stopping the OTel Collector does NOT crash any app (graceful degradation)
- [ ] Total observability stack resource usage ≤ 1.4 GB RAM, ≤ 0.7 CPU cores
- [ ] All existing tests pass unchanged (OTel import guarded with `try/except ImportError`)

## 13. Validation Checklist

- [ ] No OTel import at module level in hot paths — all guarded with `try/except ImportError`
- [ ] `valkey_encode(inject_trace=False)` available for test/offline contexts
- [ ] `_traceparent` / `_tracestate` keys do not collide with any Pydantic model field names (verified: no model uses underscore-prefixed fields)
- [ ] `valkey_decode()` ignores unknown keys (`model_validate` with Pydantic v2 extras="ignore" default)
- [ ] 3-day retention configured for Tempo, Loki, and Prometheus
- [ ] No secrets or credentials exposed through traces or metrics
- [ ] Docker Compose health checks exist for db and broker (pre-existing); observability services use `service_started` (no health check needed — apps retry OTel export)
- [ ] Grafana admin password set via `GRAFANA_ADMIN_PASSWORD` env var, not hardcoded

## 14. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| OTel SDK adds latency to message processing | Low — BatchSpanProcessor is async, <1ms overhead per message | Benchmark before/after; `inject_trace=False` escape hatch |
| `grpcio` wheel build on ARM/slim images | Medium — can cause Docker build failure | Pin `grpcio` binary wheel version or add build-essential to builder stage |
| Collector down → log/trace loss | Low — apps unaffected, data lost until collector restarts | Acceptable for dev; production would add Kafka buffer |
| Pydantic model validation with extra `_traceparent` key | Low — Pydantic v2 ignores extra fields by default | Verified: `model_config` not set to `extra="forbid"` in any pipeline model |
| Trace context lost in RiskWorker's custom `run()` override | Medium — RiskWorker has its own loop, not using `BaseStreamConsumer.run()` | Must instrument RiskWorker's custom loop separately (see affected flows) |

## 15. RiskWorker Special Case

`RiskWorker` in `src/apps/risk_app/risk_worker.py` **overrides `run()`** with its own dual-stream loop (signal streams + price update streams). It does NOT delegate to `BaseStreamConsumer.run()`. The trace extraction and span creation must be duplicated in RiskWorker's custom loop:

```python
# In RiskWorker.run(), for each message in both loops:
parent_ctx = extract_trace_context(payload)
with tracer.start_as_current_span(
    "risk.process_signal",  # or "risk.process_price_update"
    context=parent_ctx,
    attributes={...},
):
    # existing processing logic
```

This is the highest-risk integration point — test carefully.

## 16. Architecture Tradeoffs

### Chosen: OTel Collector as central hub
**Pro**: Single point of config for routing; apps only need one endpoint; can add/remove backends without app changes.
**Con**: Single point of failure for telemetry (not for apps — graceful degradation).
**Rejected alternative**: Direct export from apps to backends — harder to manage, 3 endpoints per app, no centralized batching.

### Chosen: `_traceparent` in Valkey payload (underscore prefix)
**Pro**: No model changes needed; Pydantic ignores it; no schema migration.
**Con**: Slightly pollutes the stream payload with non-business data.
**Rejected alternative**: Separate Valkey hash per trace — too complex, race conditions with stream ordering.

### Chosen: Prometheus (pull/remote-write) over Mimir
**Pro**: Simpler, lower resource usage, sufficient for single-node dev deployment.
**Con**: No multi-tenancy, no long-term storage.
**Rejected alternative**: Grafana Mimir — overkill for a single-pipeline dev/research stack.

### Chosen: Grafana anonymous viewer access
**Pro**: Zero-friction dashboard access for local dev.
**Con**: No auth for dev mode.
**Rejected alternative**: Full auth — unnecessary complexity for local development.
