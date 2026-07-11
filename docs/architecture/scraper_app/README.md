# `scraper_app` Architecture Metadata

This folder is the architecture handoff for `scraper_app`. It captures the
current internal scraper service shape, the provider workers that feed it, the
cache and job contracts it owns, and the places where the code has outgrown the
older `docs/tv_scraper.md` note.

## Files

- `catalog.yaml` — machine-readable app metadata
- `overview.d2` — component and dependency map
- `io.d2` — cache keys, job keys, storage, and consumer map
- this file — narrative scope and review guide

## Scope

`scraper_app` is the browser-backed data acquisition boundary for external
provider surfaces that are not part of the exchange websocket/runtime loop.

Current validated scope includes:

- internal FastAPI service for health, cached reads, live fetches, and async jobs
- TradingView provider support for:
  - index OHLCV snapshots
  - derivative single-value series such as open interest and funding rate
- CoinGlass provider support for liquidation heatmap snapshots
- async job dedupe, persistence, and recovery using Valkey-backed job records
- periodic TradingView worker publication into Valkey and TimescaleDB
- shared browser runtime for Patchright/Chromium session reuse and cookie loading
- offline research CLI entrypoints for TradingView and CoinGlass

## Ownership Boundaries

`scraper_app` owns:

- browser-based provider acquisition logic
- provider-specific cache publication in Valkey
- async scrape job lifecycle for on-demand requests
- internal synchronous and asynchronous scraper API surfaces
- periodic TradingView refresh jobs

`scraper_app` does **not** own:

- canonical asset lifecycle or ingestion runtime state
- downstream feature computation or strategy decisions
- alert policy decisions
- default pipeline orchestration for every provider worker

## Runtime Shape

At a high level the app has four runtime pieces:

- **Internal API**
  - `/health`, `/latest/*`, `/fetch/sync`, and `/jobs/*`
- **Service layer**
  - `ScraperFetchService` for live fetches and cache reads
  - `ScraperJobService` for deduped async execution and recovery
- **Provider workers**
  - TradingView ARQ worker for scheduled cache/database refresh
  - CoinGlass ARQ worker implemented in code, but not composed by default
- **Browser runtime**
  - shared Patchright/Chromium lifecycle and cookie normalization

## Entrypoints

- `src/apps/scraper_app/api/main.py`
  - launches the internal FastAPI scraper service
- `src/apps/scraper_app/api/app.py`
  - wires fetch/job services and recovers pending jobs from Valkey
- `src/apps/scraper_app/providers/tradingview/worker.py`
  - scheduled TradingView worker for index and derivatives refresh
- `src/apps/scraper_app/providers/coinglass/worker.py`
  - scheduled CoinGlass heatmap worker
- `src/apps/scraper_app/cli.py`
  - offline research fetch CLI

## Validated Contracts

### Consumed

- TradingView chart/websocket pages plus session cookies
- CoinGlass heatmap pages/API payloads plus session cookies
- Valkey for cache state and async job persistence
- TimescaleDB writer pool for:
  - `tv_index_ohlcv`
  - `open_interest`
  - `funding_rate`
- `api_app` bridge calls under `/ingestion/scraper/*`

### Produced / Owned

- `index:latest:{short_name}`
- `derivatives:latest:{asset}:oi`
- `derivatives:latest:{asset}:funding`
- `coinglass:latest:liquidation_heatmap:{exchange}:{short_name}`
- `scraper:job:{job_id}`
- `scraper:job:result:{job_id}`
- internal API under:
  - `/health`
  - `/latest/tradingview/ohlcv`
  - `/latest/tradingview/series`
  - `/latest/coinglass/heatmap`
  - `/fetch/sync`
  - `/jobs`

## Current Deployment Notes

The codebase now distinguishes between:

- `scraper-service`
  - FastAPI internal service on port `8081`
- `scraper-tradingview`
  - ARQ worker for scheduled TradingView refresh

The CoinGlass worker exists in code, tests, and config, but it is not currently
wired into the default `docker-compose.yml` as a separate service.

## Deferred / Near-Term Follow-ups

These are intentional follow-ups, not accidental omissions:

- add a first-class CoinGlass worker service to the default Docker stack
- formalize provider-specific failure/event streams if alerting needs more than health probing
- decide whether on-demand live CoinGlass fetches should also persist a durable history sink

## Rendering

If `d2` is installed locally:

```bash
./scripts/render_d2.sh docs/architecture/scraper_app/overview.d2
./scripts/render_d2.sh docs/architecture/scraper_app/io.d2
```
