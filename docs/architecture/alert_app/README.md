# `alert_app` Architecture Metadata

This folder is the architecture handoff for `alert_app`. It captures the
implemented MVP shape, the contracts it consumes, the state it owns, and the
validated notification/runtime flows.

## Files

- `catalog.yaml` — machine-readable app metadata
- `overview.d2` — component and dependency map
- `io.d2` — contracts, streams, keys, storage, and transport map
- this file — narrative scope and review guide

## Scope

`alert_app` is the operational alerting sidecar for the flipperAgent pipeline.
It consumes operational facts from other apps, converts them into normalized
alert events and incidents, and routes outbound notifications.

Current validated scope includes:

- lifecycle event consumption from `asset:lifecycle`
- execution failure stream consumption from `execution:failures:{asset}`
- reconciler-driven freshness detection for signal and strategy
- reconciler-driven scraper job failure/recovery detection
- reconciler-driven health check breach/recovery detection
- incident dedupe, renotify, ack, resolve, and silence management
- webhook and Telegram delivery
- internal alert observability/API routes

## Ownership Boundaries

`alert_app` owns:

- normalized alert policy
- incident lifecycle and hot/cold state
- notification routing and transport dispatch
- dedupe / renotify / route burst throttling
- synthetic health and freshness reconciliation

`alert_app` does **not** own:

- canonical asset lifecycle state
- exchange/runtime business logic from upstream apps
- log scraping as the primary alert input
- downstream risk or execution decisions

## Runtime Shape

At a high level the app has four runtime pieces:

- **Stream consumers**
  - lifecycle and execution failure streams
- **Synthetic reconciler**
  - scans signal/strategy runtime hashes, scraper jobs, and configured health endpoints
- **Incident engine**
  - dedupe, open/update/resolve, hot-state projection, SQL durability
- **Notification dispatcher**
  - rate-limit, retry, and send via webhook/Telegram

## Entrypoints

- `src/apps/alert_app/main.py`
  - launches the runtime worker process
- `src/apps/alert_app/runtime/runner.py`
  - wires consumers, reconciler, incident service, and dispatcher
- `src/apps/alert_app/api/main.py`
  - serves the internal FastAPI observability/control API
- `src/apps/alert_app/observability/service.py`
  - powers health, incidents, routes, silences, and notification views

## Validated Contracts

### Consumed

- `asset:lifecycle`
- `execution:failures:{asset}`
- `signal:status:{asset}:{tf}`
- `strategy:status:{asset}:{tf}`
- `scraper:job:{job_id}`
- configured HTTP health surfaces such as:
  - `ingestion:8003/health/ready`
  - `scraper-service:8081/health`
  - with per-check startup grace from `alerts.health_checks.*.startup_grace_seconds`

### Produced / Owned

- incident hot keys and summary projection in Valkey
- alert incident / delivery / silence rows in Postgres
- outbound webhook and Telegram notifications
- internal API under `/alerts/*`

## Validated Behaviors

The current implementation is backed by local and Docker validation for:

- incident list/detail/ack/resolve/silence-delete flows
- execution failure incident creation
- signal freshness breach + recovery
- scraper job failure incident creation
- route rate limiting and transport retry behavior
- Telegram HTML-safe formatting
- startup grace for health probes to suppress cold-start noise
- clearer operator-facing health probe wording for Telegram/webhook payloads

## Deferred / Near-Term Follow-ups

These are intentionally left for later, not missing by accident:

- richer multi-step escalation ladders beyond renotify + burst throttling
- more source-specific alert feeds from `risk_app` / `portfolio_app`
- Slack transport
- broader live Docker proofs for health breach toggling across more services

## Rendering

If `d2` is installed locally:

```bash
./scripts/render_d2.sh docs/architecture/alert_app/overview.d2
./scripts/render_d2.sh docs/architecture/alert_app/io.d2
```
