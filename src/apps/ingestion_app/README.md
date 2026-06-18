# ingestion_app

This package contains the ingestion system runtime, worker jobs, control-plane
asset registry, provider adapters, and storage integration.

Primary slices:
- `control_plane/` manages asset registry persistence and mutation commands.
- `jobs/` runs scheduled backfill, top-up, cleanup, and depth tasks.
- `runtime/` manages per-asset websocket lifecycles and reconciliation.
- `storage/` owns schema bootstrap, writers, and janitorial cleanup.
- `adapters/` wraps exchange-specific REST and websocket integrations.

Public package surfaces:
- `apps.ingestion_app.control_plane`
- `apps.ingestion_app.runtime`
- `apps.ingestion_app.worker`
- `apps.ingestion_app.main`

Operational notes:
- canonical durable market history is stored in Timescale via `storage/schema.sql`
- stream boundedness is config-driven under `ingestion.streams.*`
- removed assets are purged from both Valkey runtime keys and Timescale symbol rows
- deep runtime memory checks are exercised via `scripts/qa/ingestion_runtime_memory_soak.py`

Current storage policy:
- `ohlcv`, `open_interest`, `funding_rate`: compressed after `14 days`, retained `180 days`
- `ticks`: compressed after `1 day`, retained `30 days`
- `l2_depth_features`: compressed after `7 days`, retained `90 days`

Validation split:
- fast unit/runtime checks live under `tests/ingestion/`
- deep repeated-cycle memory validation is intentionally deferred to the QA soak script
- Docker-backed layer-by-layer validation is deferred until local infra is brought up again
