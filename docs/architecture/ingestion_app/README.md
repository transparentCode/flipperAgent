# `ingestion_app` Architecture Metadata

This folder documents the validated ingestion control-plane and runtime shape.

## Files

- `catalog.yaml` — machine-readable ingestion metadata
- `overview.d2` — app/component relationship map
- `io.d2` — focused contracts, queues, streams, and persistence view
- this file — scope and rendering notes

## Scope

This slice reflects the current validated ingestion behavior:

- registry-backed asset lifecycle control
- canonical asset manifest publication to Valkey
- lifecycle stream fan-out for downstream apps
- runtime reconciliation and per-asset websocket orchestration
- REST gap-fill, purge, and scheduled ARQ jobs
- ingestion observability and scraper bridge routes
- TimescaleDB ownership and Valkey runtime contracts

## Key Contract Split

- canonical control-plane state lives under:
  - `asset:{symbol}`
  - `asset:{symbol}:tf:{timeframe}`
  - `asset:lifecycle`
- ingestion runtime/ops contracts remain separate:
  - `stream:control:ingestion`
  - `stream:events:ingestion`
  - `stream:ohlcv:{symbol}:{timeframe}`
  - `ingestion:state:{symbol}:{timeframe}`

## Rendering

If `d2` is installed locally:

```bash
d2 docs/architecture/ingestion_app/overview.d2 docs/architecture/ingestion_app/overview.svg
d2 docs/architecture/ingestion_app/io.d2 docs/architecture/ingestion_app/io.svg
```

Or use:

```bash
./scripts/render_d2.sh docs/architecture/ingestion_app/overview.d2
./scripts/render_d2.sh docs/architecture/ingestion_app/io.d2
```
