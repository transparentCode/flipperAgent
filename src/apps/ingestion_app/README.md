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
