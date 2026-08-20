# Ingestion operations

This runbook covers the current canonical ingestion runtime. Ingestion owns the
canonical 1m feed plus derived 1h/4h publication for the retained Decision
routes. No legacy Signal/Strategy runtime remains in production.

## Normal startup and health

```bash
docker compose up -d db broker
docker compose up -d ingestion
curl -fsS http://127.0.0.1:8003/health/live
curl -fsS http://127.0.0.1:8003/health/ready
curl -fsS http://127.0.0.1:8003/runtime
```

The ingestion service uses port `8003`, depends on Timescale health, and does not have
a hard broker dependency. `/health/ready` reports runtime readiness; liveness
is independent of the runtime state.

Canonical production downstream routing is now:

```text
BTCUSDT:1h
BTCUSDT:4h
ETHUSDT:4h
```

Those routes are owned by Decision. Automatic source fallback remains disabled;
an ingestion failure is a manual-remediation boundary.

## Runtime control and restart

```bash
curl -fsS -X POST http://127.0.0.1:8003/runtime/pause
curl -fsS -X POST http://127.0.0.1:8003/runtime/resume
curl -fsS -X POST http://127.0.0.1:8003/runtime/reconnect
docker compose restart ingestion
```

If downstream certification is in progress, coordinate restarts with the active
Decision/Risk/Execution procedure. Ingestion itself remains the canonical writer
for `ingestion.candles` and `ingestion.outbox`.

## Broker outage and return

When certifying a broker outage, stop or isolate downstream consumers as required
by the specific certification:

```bash
docker compose stop broker
curl -fsS http://127.0.0.1:8003/health/live
curl -fsS http://127.0.0.1:8003/health/ready
# verify newly closed ingestion 1m candles and their pending outbox rows
docker compose start broker
curl -fsS http://127.0.0.1:8003/health/ready
```

Canonical Timescale commits must continue while Valkey is absent. The durable
outbox remains pending and the publisher drains it after Valkey returns. Do not
restart ingestion merely to recover the publisher.

## Valkey total-data-loss recovery

Valkey is non-authoritative. Automatic replay of rows already marked
`published_at` is absent:

```text
AUTOMATIC_PUBLISHED_OUTBOX_REPLAY = ABSENT
```

If published streams are lost, keep or restore Timescale, bring up a clean
Valkey, and allow current pending outbox rows to drain. Do not delete published
outbox history or assume it can be reconstructed automatically.

## Completed migration

BTC and the remaining five assets were backfilled, source-bound, and
operationally certified during N1/N2. The one-time preparation and cutover
scripts are retired. Immutable evidence remains in `plans/` and
`artifacts/`; normal operations do not repeat those migration stages.

If ingestion fails, stop downstream trading services and require explicit manual
remediation. There is no automatic source fallback.

## Shutdown

```bash
docker compose stop ingestion broker
```

Leave Timescale running and healthy unless a separate reviewed procedure says
otherwise. N2C retention is process-owned by `ingestion` and runs once at
startup, then once per day:

```yaml
retention:
  candle_days: 90
  published_outbox_days: 7
  cleanup_interval_seconds: 86400
  error_backoff_seconds: 60
  outbox_delete_batch_size: 10000
  outbox_max_batches_per_run: 100
```

Canonical candles are retained for at least 90 days by dropping only complete
Timescale chunks older than the cutoff. Published outbox rows are deleted in
bounded batches after seven days. Pending rows (`published_at IS NULL`) are
never deleted by age and remain durable publication intent until they publish.
The janitor is non-fatal, broker-independent, and stops before database pools
close. It does not add an API endpoint or a scheduler service.

The operational store is not an indefinite research archive. Research that
needs history older than the 90-day operating window must reacquire data from a
provider and freeze its own artifact.

### Retention certification

The historical N2C retention certification remains preserved in its immutable
artifact set. There is no live operator script for it in the Decision-only
runtime topology.

## Ingestion observability (N1D)

The checked-in Grafana dashboard is provisioned as **Ingestion Operations**
with UID `flipper-ingestion`. Start the existing observability profile when
the local stack is available:

```bash
docker compose --profile prod up -d tempo loki prometheus otel-collector grafana
open http://127.0.0.1:3001/d/flipper-ingestion
```

The OTel Collector is optional. It is not an `ingestion` Compose
dependency, and collector loss must not affect canonical commits, recovery,
runtime readiness, or publication into the durable outbox. Ingestion exports the
following bounded operational signals:

```text
ingestion_runtime_live
ingestion_websocket_connected
ingestion_websocket_reconnect_total
ingestion_websocket_interruption_total
ingestion_websocket_queue_utilization
ingestion_base_last_close_timestamp_seconds{venue,instrument_id}
ingestion_candle_commit_total{timeframe,source_type,outcome}
ingestion_candle_commit_duration_ms{timeframe,source_type}
ingestion_recovery_total{outcome}
ingestion_recovery_duration_ms
ingestion_outbox_pending
ingestion_outbox_oldest_pending_timestamp_seconds
ingestion_outbox_publish_total
ingestion_outbox_publish_failure_total
ingestion_outbox_publish_batch_size
ingestion_outbox_publish_duration_ms
```

`service_name=ingestion` is supplied by the OTel resource. Compose also sets
the standard `service.instance.id` resource attribute through
`OTEL_RESOURCE_ATTRIBUTES`, defaulting to `ingestion-local`. Override it
with `INGESTION_OTEL_INSTANCE_ID` when running more than one stable ingestion
replica; each replica must receive its own stable value. Do not encode instance
identity as a metric label in application code.

The only per-lane metric is the base freshness gauge; it is intentionally
limited to one series per active base lane. No event ID, open time, exception
text, or request ID is a metric label. Recovery lane/range details belong in
logs and the `ingestion.recovery` span; outbox batch details belong in the
`ingestion.outbox.publish_batch` span. There is no span per candle, HTF row,
queue operation, or stream entry.

Useful diagnostic queries/conditions are:

```promql
time() - ingestion_base_last_close_timestamp_seconds
(time() - ingestion_outbox_oldest_pending_timestamp_seconds{service_name="ingestion"}) * (ingestion_outbox_pending{service_name="ingestion"} > bool 0)
sum(increase(ingestion_candle_commit_total{outcome="conflict"}[1h]))
```

Investigate `runtime_live == 0`, a disconnected WebSocket, freshness older
than two configured base intervals, persistently high queue utilization,
recovery failures, any canonical conflict, or an increasing pending outbox /
oldest-pending age. The guarded oldest-pending expression explicitly renders
zero age when pending is zero and the actual age when pending is positive.
These are diagnostic conditions; N1D does not add an alerting service or
notification policy.

Telemetry shutdown is best effort and nonblocking. The shared helper detaches
the OTel log handler, removes exporter atexit callbacks, and performs provider
shutdown on a daemon thread so an unavailable collector cannot recreate a
container SIGTERM/SIGKILL failure.

The historical N1D observability certification also remains preserved in its
immutable artifact set. There is no live operator script for it in the
Decision-only runtime topology.
