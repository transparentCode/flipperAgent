# `signal_app` Architecture Metadata

This folder is the `D2` architecture pilot for the signal layer migration.

It documents the target modular shape for `signal_app`, while preserving the
current production contracts used by downstream workers.

## Files

- `catalog.yaml` - machine-readable app metadata and migration scope
- `overview.d2` - human-facing component map
- `io.d2` - focused inputs, outputs, streams, and storage view
- this file - scope, assumptions, and rendering notes

## Scope

This slice documents:

- live OHLCV consumption from ingestion
- startup priming and gap recovery from TimescaleDB
- raw indicator, engineered feature, and regime feature stages
- Valkey enrichment reads for TradingView indices and derivatives
- `FeatureVector` and `PriceUpdate` publication contracts
- signal observability and future internal API surfaces
- offline and on-demand feature snapshot direction

## Non-Goals

- No immediate replacement of the current worker command.
- No runtime control plane until the v2 pipeline boundaries are validated.
- No change to `features:{asset}:{timeframe}` or `price_update:{asset}:{timeframe}`
  contracts during the first migration slice.

## Rendering

If `d2` is installed locally, render with:

```bash
d2 docs/architecture/signal_app/overview.d2 docs/architecture/signal_app/overview.svg
d2 docs/architecture/signal_app/io.d2 docs/architecture/signal_app/io.svg
```

Or use the repo helper:

```bash
./scripts/render_d2.sh docs/architecture/signal_app/overview.d2
./scripts/render_d2.sh docs/architecture/signal_app/io.d2
```

