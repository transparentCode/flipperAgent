# ingestion_app_v2

Temporary mirror package for phased refactoring of `apps.ingestion_app`.

Rules for this migration:
- `apps.ingestion_app` remains the live/stable path until parity is proven.
- `apps.ingestion_app_v2` is the refactor target.
- Migrate one slice at a time with focused tests.
- Prefer compatibility facades during migration, then collapse paths later.

Phase 1 covers:
- `control_plane/`
- `models/asset_registry.py`

