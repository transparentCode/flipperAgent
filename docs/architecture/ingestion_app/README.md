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

## Storage Policy

Current ingestion storage classes:

- canonical market history:
  - `ohlcv`
  - `open_interest`
  - `funding_rate`
  - compressed after `14 days`
  - retained for `180 days`
- rebuildable raw data:
  - `ticks`
  - compressed after `1 day`
  - retained for `30 days`
- rebuildable derived data:
  - `l2_depth_features`
  - compressed after `7 days`
  - retained for `90 days`

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

## Validation Modes

- fast repo validation:
  - focused pytest slices for storage bootstrap, cleanup, and websocket runtime transitions
- deep memory validation:
  - `scripts/qa/ingestion_runtime_memory_soak.py`
  - used instead of a heavyweight repeated-cycle unit test
- final infra validation:
  - deferred Docker/local-service pass for layer-by-layer verification and final signoff

## Layered Validation Checklist

- storage bootstrap:
  - schema init is idempotent
  - compression and retention policies are attached
- cleanup and purge:
  - removed assets clear Valkey runtime keys
  - removed assets purge Timescale symbol rows
  - purge completion events are emitted
- runtime websocket:
  - bootstrap promotes assets from warming to live on first valid payload
  - reconnect paths close and recreate transient Valkey clients safely
  - retry exhaustion emits terminal runtime events
- boundedness and memory:
  - stream caps come from `ingestion.streams.*`
  - long-run memory behavior is checked with `scripts/qa/ingestion_runtime_memory_soak.py`
- final infra pass:
  - bring up Docker/local Timescale + Valkey
  - verify layer-by-layer data movement before final signoff

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
