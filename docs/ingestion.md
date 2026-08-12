# Ingestion

Production market-data ingestion is owned by `ingestion`, implemented by
`apps.ingestion_app`. It consumes Binance USD-M data, persists canonical
candles in `ingestion.candles`, records publication intent in
`ingestion.outbox`, and publishes bounded ingestion OHLCV streams.

The six production assets are ingestion-enabled and ingestion-owned. Signal history is
primed from Timescale and live signal input uses only:

```text
stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}
```

Use the current operational procedures in
[`ingestion_operations.md`](ingestion_operations.md). The former
two-process legacy runtime, its ARQ jobs, legacy OHLCV table, and legacy
stream protocol were retired in N3B. Immutable migration evidence remains in
`plans/` and `artifacts/`.

The canonical implementation package is `apps.ingestion_app`.
