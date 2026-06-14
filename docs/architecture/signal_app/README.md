# `signal_app` Architecture Metadata

This folder documents the validated modular `signal_app` shape that now sits
between ingestion and strategy.

## Files

- `catalog.yaml` — machine-readable signal metadata
- `overview.d2` — component and dependency map
- `io.d2` — focused contracts and data-flow view
- this file — scope and rendering notes

## Scope

This slice reflects the current validated signal behavior:

- bootstrap pair discovery from canonical asset manifest
- lifecycle subscription on `asset:lifecycle`
- per-pair worker supervision
- historical priming before live feature production
- gap re-prime with `DEGRADED` fallback on partial history
- feature and price-update publication
- clean worker teardown when removed streams disappear
- transient Valkey read-timeout retry without elevated error noise
- runtime status keys and observability routes
- on-demand feature snapshot path for research/debugging

## Canonical Relationship

- `ingestion_app` owns canonical lifecycle state
- `signal_app` reads `asset:*` and `asset:lifecycle`
- `signal_app` writes only signal-local runtime namespaces and output streams

## Rendering

If `d2` is installed locally:

```bash
d2 docs/architecture/signal_app/overview.d2 docs/architecture/signal_app/overview.svg
d2 docs/architecture/signal_app/io.d2 docs/architecture/signal_app/io.svg
```

Or use:

```bash
./scripts/render_d2.sh docs/architecture/signal_app/overview.d2
./scripts/render_d2.sh docs/architecture/signal_app/io.d2
```
