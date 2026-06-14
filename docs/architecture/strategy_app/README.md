# `strategy_app` Architecture Metadata

This folder documents the validated `strategy_app` slice that consumes signal
features and publishes trade signals.

## Files

- `catalog.yaml` — machine-readable strategy metadata
- `overview.d2` — component and dependency map
- `io.d2` — focused contracts and runtime-state view
- this file — scope and rendering notes

## Scope

This slice reflects the current validated strategy behavior:

- bootstrap from canonical asset manifest
- lifecycle-driven worker creation and teardown
- pair-level pause/resume control keys
- feature consumption from `signal_app`
- model evaluation, scoring, selection, and signal publication
- strategy status and latest-signal observability routes

## Canonical Relationship

- `ingestion_app` owns canonical `asset:*` state
- `strategy_app` subscribes to `asset:lifecycle`
- `strategy_app` writes only strategy-local runtime and control keys plus `signals:*`

## Rendering

If `d2` is installed locally:

```bash
d2 docs/architecture/strategy_app/overview.d2 docs/architecture/strategy_app/overview.svg
d2 docs/architecture/strategy_app/io.d2 docs/architecture/strategy_app/io.svg
```

Or use:

```bash
./scripts/render_d2.sh docs/architecture/strategy_app/overview.d2
./scripts/render_d2.sh docs/architecture/strategy_app/io.d2
```
