# `ingestion_app` Architecture Metadata

This folder is the first `D2` pilot for repo architecture metadata.

It focuses only on `ingestion_app` and keeps three concerns separate:

- `catalog.yaml` — machine-readable metadata source for the app
- `overview.d2` — human-facing diagram for quick review
- `io.d2` — focused inputs/outputs/contracts view
- this file — scope, assumptions, and rendering notes

## Scope

This first slice documents:

- major `ingestion_app` features
- internal runtime components
- ingestion-facing API control and observability surfaces
- the scraper bridge used for on-demand external data pulls
- external dependencies
- Valkey streams and ARQ jobs
- TimescaleDB tables owned or touched by the app
- app-level inputs and outputs
- component-level IO contracts

It does **not** yet generate `D2` from YAML. The diagram is hand-authored from the catalog so we can agree on the shape first.

## Rendering

If `d2` is installed locally, render with:

```bash
d2 docs/architecture/ingestion_app/overview.d2 docs/architecture/ingestion_app/overview.svg
d2 docs/architecture/ingestion_app/io.d2 docs/architecture/ingestion_app/io.svg
```

Or use the repo helper:

```bash
./scripts/render_d2.sh docs/architecture/ingestion_app/overview.d2
./scripts/render_d2.sh docs/architecture/ingestion_app/io.d2
```

The current rendered output lives at `docs/architecture/ingestion_app/overview.svg`.
The IO-focused rendered output lives at `docs/architecture/ingestion_app/io.svg`.

## Review Intent

The goal of this first pass is to validate:

- whether the metadata categories are right
- whether per-app drilldown is useful
- whether stream/table ownership is represented clearly enough

Once this structure looks good, we can apply the same pattern to `scraper_app`, `signal_app`, and the rest of the pipeline.
