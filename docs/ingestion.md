# Ingestion

Production market-data ingestion is owned by `ingestion`, implemented by
`apps.ingestion_app`. It consumes Binance USD-M data, persists canonical
candles in `ingestion.candles`, records publication intent in
`ingestion.outbox`, and publishes bounded ingestion OHLCV streams.

The six production assets are ingestion-enabled and ingestion-owned. Decision
history is primed from Timescale and live Decision input uses only:

```text
stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}
```

The current downstream topology is Decision for the live stream, Timescale
history, manifests, and lifecycle notifications; Alert consumes lifecycle
notifications; and Risk consumes manifests and lifecycle notifications. There
is no current `src/apps/signal_app` package; the former Signal/Strategy runtime
is historical migration context only.

At startup, ingestion connects to Valkey, binds the manifest store, runs the
initial lifecycle reconciliation, starts the lifecycle reconciler, and only
then starts the outbox publisher. The ordering is implemented in
[`bootstrap.py`](../src/apps/ingestion_app/bootstrap.py:132) and is a current
operational dependency. The same module keeps explicit service construction
separate from its private `_LifespanResources` cleanup ledger, which closes the
controller, retention, publisher task, historical providers, DB pools, and
ConfigManager in that dependency order.

The asset create/patch API persists YAML atomically and replaces runtime
settings when the registered configuration directory is writable. The
production Compose deployment keeps the ingestion service `read_only: true`,
retains `./configs:/app/configs:ro`, and over-mounts only
`./configs/ingestion/assets:/app/configs/ingestion/assets:rw`. Therefore the
existing registered asset YAML directory remains the sole writable
configuration surface; global and other application configuration stay
read-only, and the existing atomic POST/PATCH persistence path is deployable.

Use the current operational procedures in
[`ingestion_operations.md`](ingestion_operations.md). The former
two-process legacy runtime, its ARQ jobs, legacy OHLCV table, and legacy
stream protocol were retired in N3B. Immutable migration evidence remains in
`plans/` and `artifacts/`.

The canonical implementation package is `apps.ingestion_app`.
