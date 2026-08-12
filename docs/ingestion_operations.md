# Ingestion operations

This runbook covers the current six-asset ingestion architecture. BTC, ETH, XRP,
SOL, BNB, and DOGE signal history and live signal input use ingestion. The
legacy ingestion runtime and its migration-era shadow paths were retired in
N3B; no production source fallback remains.

## Normal startup and health

```bash
docker compose up -d db broker
docker compose up -d ingestion
docker compose up -d signal-worker
curl -fsS http://127.0.0.1:8003/health/live
curl -fsS http://127.0.0.1:8003/health/ready
curl -fsS http://127.0.0.1:8003/runtime
```

The ingestion service uses port `8003`, depends on Timescale health, and does not have
a hard broker dependency. `/health/ready` reports runtime readiness; liveness
is independent of the runtime state.

The production source bindings are:

```yaml
signal:
  runtime:
    ohlcv_sources:
      BTCUSDT:
        source: ingestion
        venue: binance
        instrument_id: BTC-USDT-PERP
      ETHUSDT:
        source: ingestion
        venue: binance
        instrument_id: ETH-USDT-PERP
      XRPUSDT:
        source: ingestion
        venue: binance
        instrument_id: XRP-USDT-PERP
      SOLUSDT:
        source: ingestion
        venue: binance
        instrument_id: SOL-USDT-PERP
      BNBUSDT:
        source: ingestion
        venue: binance
        instrument_id: BNB-USDT-PERP
      DOGEUSDT:
        source: ingestion
        venue: binance
        instrument_id: DOGE-USDT-PERP
```

All six ingestion asset definitions are enabled and own their manifests/lifecycle.
Automatic source fallback is disabled; an ingestion failure is a manual-remediation
boundary.

## Runtime control and restart

```bash
curl -fsS -X POST http://127.0.0.1:8003/runtime/pause
curl -fsS -X POST http://127.0.0.1:8003/runtime/resume
curl -fsS -X POST http://127.0.0.1:8003/runtime/reconnect
docker compose restart ingestion
docker compose restart signal-worker
```

Pause before restarting the signal worker when it is important to prove that
no new OHLCV entries were delivered. A signal restart may publish a bootstrap
feature snapshot from Timescale history; that is not an OHLCV stream replay.
After a restart, verify the ingestion groups have `pending=0` and no unexpected tail
movement while ingestion is paused.

The ingestion signal workers use the normalized timestamp cursor in milliseconds to
ignore at-least-once duplicate candles. The persisted signal runtime status
currently reports `last_input_ts` in epoch seconds; do not compare those two
fields without converting units.

## Broker outage and return

Stop signal consumers first when certifying a broker outage:

```bash
docker compose stop signal-worker
docker compose stop broker
curl -fsS http://127.0.0.1:8003/health/live
curl -fsS http://127.0.0.1:8003/health/ready
# verify newly closed ingestion 1m candles and their pending outbox rows
docker compose start broker
curl -fsS http://127.0.0.1:8003/health/ready
docker compose up -d signal-worker
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

If published streams are lost, stop `signal-worker`, keep or restore Timescale,
bring up a clean Valkey, allow current pending outbox rows to drain, then start
the signal worker. All six workers prime from `ingestion.candles`; new groups are
created at `$`, intentionally skipping historical stream entries. Do not
delete published outbox history or assume it can be reconstructed automatically.

## Completed migration

BTC and the remaining five assets were backfilled, source-bound, and
operationally certified during N1/N2. The one-time preparation and cutover
scripts are retired. Immutable evidence remains in `plans/` and
`artifacts/`; normal operations do not repeat those migration stages.

If ingestion fails, stop signal/trading services and require explicit manual
remediation. There is no automatic source fallback.

## Shutdown

```bash
docker compose stop signal-worker ingestion broker
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

The guarded certification uses an isolated fixture identity and never drops a
production chunk containing another instrument. It proves old-published,
recent-published, and pending outbox behavior, then verifies that a normal
production run is a no-op for currently protected data:

```bash
.venv/bin/python scripts/certify_ingestion_retention_recovery_n2c.py

INGESTION_RUN_N2C_RETENTION=1 \
.venv/bin/python scripts/certify_ingestion_retention_recovery_n2c.py --execute
```

### Destructive Valkey data-loss recovery

Valkey is hot transport/state, not canonical history. Automatic replay of
already-published outbox rows is intentionally absent:

```text
AUTOMATIC_PUBLISHED_OUTBOX_REPLAY = false
PUBLISHED_OUTBOX_CLEANUP = N2C bounded seven-day retention
```

After total Valkey loss, stop signal/trading consumers, restore an empty
Valkey, start/reconcile ingestion so its six current manifests are rebuilt, and then
start signal workers. They prime all eight configured pairs from
`ingestion.candles`, create ingestion input groups at the current stream tail, emit
bootstrap feature/price outputs, and process future events. Do not replay
published outbox history or flush production DB0. N2C proves this procedure in
isolated logical Valkey DB15 (`redis://localhost:6380/15`) and flushes DB15 only.

The existing bounded stream transport remains approximately `MAXLEN 1000` per
ingestion lane. Pending outbox rows are different from historical replay: if a broker
outage happened before publication, those pending rows publish normally after
the broker returns.

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
container SIGTERM/SIGKILL failure. The same helper is used by `signal_app`
and `ingestion_app`.

For an operational certification (no writes other than normal application
activity, and no reset/flush/delete operation), use the guarded script:

```bash
.venv/bin/python scripts/certify_ingestion_observability_n1d.py

INGESTION_RUN_N1D_OBSERVABILITY=1 \
.venv/bin/python scripts/certify_ingestion_observability_n1d.py --execute
```

The certification checks collector-down startup and graceful shutdown,
collector-up Prometheus/Tempo/Loki/Grafana evidence, and collector loss while
Ingestion is live. It restores the named services to their pre-run state and leaves
Timescale as the authoritative durable system.
