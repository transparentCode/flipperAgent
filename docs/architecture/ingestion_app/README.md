# `ingestion_app` Architecture Metadata

This folder is the high-level architecture handoff for `ingestion_app`. It is
meant to answer one question before LLD review: **what this app owns, how data
and control move through it, and which contracts downstream apps can rely on.**

## Files

- `catalog.yaml` — machine-readable app metadata
- `overview.d2` — component and dependency map
- `io.d2` — contract-level streams, keys, jobs, and storage map
- `lifecycle_sequence.d2` — add/resume, pause/stop, and remove lifecycle sequences
- this file — narrative overview and review guide

## Purpose

`ingestion_app` is the market-data control plane and live-ingestion runtime.
It owns:

- asset lifecycle control for exchange/provider-backed assets
- canonical asset manifest publication to Valkey
- lifecycle fan-out for downstream apps
- live websocket candle ingestion
- historical gap-fill and top-up jobs
- removal purge and storage cleanup
- ingestion runtime observability

It does **not** own downstream feature computation, strategy evaluation,
portfolio logic, or alert policy decisions.

## Review Lens

This doc distinguishes between:

- current implemented behavior
- required architectural contract
- recommended near-term addition

That split matters because ingestion cannot leave canonical truth, idempotency,
candle finality, parity, and failure handling implicit.

## Runtime Shape

At a high level, the app is split into four layers:

- **Ingress / control**
  - operator-facing routes under `api_app`
  - validates asset changes and persists desired state
- **Canonical state publication**
  - writes canonical asset keys
  - emits normalized lifecycle events
  - emits runtime control commands for the reconciler
- **Runtime execution**
  - reconciles desired state into running per-asset websocket runtimes
  - performs backfill-before-live and resume-before-live flows
  - publishes closed candles for downstream consumers
- **Async recovery / cleanup**
  - runs ARQ jobs for gap-fill, purge, top-up, and depth polling
  - emits operator-facing outcome events

## Entrypoints

- `src/apps/ingestion_app/main.py`
  - launches the ingestion runtime process
- `src/apps/ingestion_app/runtime/app.py`
  - process-local runtime app and reconciler lifespan
- `src/apps/ingestion_app/worker.py`
  - ARQ worker for async jobs
- `src/apps/api_app/routers/ingestion.py`
  - operator and internal orchestration API surface

## Core Responsibilities

### 1. Asset lifecycle ownership

`ingestion_app` is the only writer of canonical asset lifecycle state.

It accepts runtime mutations like:

- add / upsert asset
- patch asset metadata
- pause asset
- stop asset
- resume asset
- remove asset
- batch variants of the above

### 2. Canonical manifest publication

It materializes desired/effective asset state into Valkey under canonical keys:

- `asset:{symbol}`
- `asset:{symbol}:tf:{timeframe}`

And publishes lifecycle events via:

- `asset:lifecycle`

This is the cross-app contract used by `signal_app` and `strategy_app`.

### 3. Runtime orchestration

The runtime reconciler reads the effective asset catalog, compares it to active
runtime handles, and decides whether to:

- start an asset runtime
- stop an asset runtime
- keep an asset runtime as-is
- dispatch removal purge work

Per-asset live runtime startup flows through:

- storage/bootstrap readiness
- initial gap-fill / historical priming
- websocket launch
- first valid live payload
- promotion from warming/resuming to live

### 4. Live market-data publication

The websocket pipeline owns:

- consuming live exchange candle feeds
- persisting canonical bars into TimescaleDB
- writing runtime state / liveness
- publishing closed candles to downstream stream consumers

The main downstream hot-path stream is:

- `stream:ohlcv:{symbol}:{timeframe}`

### 5. Recovery, cleanup, and async operations

Async jobs cover:

- REST gap-fill before/after websocket gaps
- candle top-up
- depth polling / feature persistence
- storage purge for removed assets

These jobs are intentionally separate from the hot websocket path.

## Explicit Architectural Contracts

### Canonical truth ownership

This must be single-owner.

**Decision**

- `TimescaleDB.ingestion_assets` is the durable canonical asset registry
- Valkey canonical asset keys are the runtime projection and stream layer

Meaning:

- persistent lifecycle writes land in the registry first
- Valkey `asset:{symbol}` and `asset:{symbol}:tf:{timeframe}` are derived
  projection state
- durable recovery must be able to rebuild Valkey projection from registry

**Rule**

There must never be two independently mutable truths for lifecycle state.

### Lifecycle idempotency

Lifecycle mutations must converge safely under replay.

Examples:

- repeated `UPSERT`
- repeated `RESUME`
- repeated batch submissions
- replayed control messages after reconnect/restart

**Required identifiers**

- `request_id`
- `command_id`
- `asset_version`
- `timeframe_version`

**Convergence rule**

Equivalent repeated commands must not:

- create duplicate runtimes
- enqueue duplicate backfill work
- publish conflicting lifecycle state

### Websocket reconnect and recovery rules

These are normal cases, not edge cases.

Required rules:

- websocket disconnect
  - runtime degrades or warms
  - reconnects
  - backfills missing closed intervals before returning live
- process restart
  - rebuilds desired runtime set from durable registry
  - restores projection state
  - re-primes before live
- late candle arrival
  - must obey explicit closed-candle ordering rules
- duplicate closed candle
  - dedupe by `(symbol, timeframe, open_timestamp)`
- REST versus websocket conflict
  - resolve by explicit source-precedence policy
  - correction path must be observable

### Candle finalization contract

Downstream semantics depend on this.

**Recommended default**

- downstream apps consume closed candles only
- forming candles are optional and must be explicitly provisional

**Default trigger rule**

- `signal_app` and `strategy_app` trigger on closed-candle publication by
  default

**Required semantic marker**

Every candle event should have explicit finality such as:

- `provisional`
- `closed`
- optionally `corrected_closed`

### Backtest / live parity

The ingestion layer should preserve parity between:

- historical candles used in research/backtest
- live candles seen by downstream strategy consumers

Parity should hold for:

- timeframe alignment
- close timestamp convention
- candle finality semantics
- duplicate correction policy
- source precedence and repair behavior

If parity cannot hold, the divergence point must be explicit and observable.

## State Domains

The app deliberately separates three state domains.

### Canonical control-plane state

Authoritative, cross-app, durable enough for bootstrap:

- `asset:{symbol}`
- `asset:{symbol}:tf:{timeframe}`
- `asset:lifecycle`

### Ingestion runtime / ops state

Operational and app-owned:

- `stream:control:ingestion`
- `stream:events:ingestion`
- `ingestion:state:{symbol}:{timeframe}`

### Durable market history

Owned in TimescaleDB:

- `ingestion_assets`
- `ohlcv`
- `ticks`
- `open_interest`
- `funding_rate`
- `l2_depth_features`

## Control Flow

### Asset mutation path

1. Request enters `api_app` ingestion router
2. `IngestionControlService` persists desired state
3. control-plane publisher:
   - syncs canonical manifest keys
   - emits `asset:lifecycle`
   - emits `stream:control:ingestion`
   - emits accepted/operator events
4. runtime reconciler consumes the change and converges the live runtime

### Live data path

1. runtime reconciler starts asset runtime
2. bootstrap primes/backs fills required history
3. websocket pipeline connects to exchange
4. closed candles persist to TimescaleDB
5. closed candles publish to `stream:ohlcv:{symbol}:{timeframe}`
6. downstream apps consume independently

### Remove path

1. asset desired state becomes `REMOVING`
2. runtime reconciler stops live runtime
3. purge job is enqueued
4. job clears owned runtime keys and Timescale rows
5. outcome event is published

## Runtime Guarantees

Current intended guarantees:

- ingestion is the only writer of canonical asset lifecycle state
- pause/stop do not require downstream apps to mutate ingestion canonical state
- resume promotes back to live only after required recovery work completes
- removed assets are purged from owned runtime state and storage
- downstream apps consume canonical lifecycle and live candle streams, but do not
  control ingestion internals directly

## Failure and Quality Contracts

### Data quality validator

Before publishing downstream closed candles, the architecture should assume a
validation layer exists in websocket and recovery paths.

Validator responsibilities:

- timeframe-boundary timestamp alignment
- OHLC consistency
- non-negative volume
- duplicate closed-candle conflict detection
- missing-interval detection
- source-precedence aware correction handling

This can stay internal to runtime/job modules, but the contract should be
architecturally explicit.

### Failure sink / DLQ

`stream:events:ingestion` is the operator event stream, but it should not be
the only failure sink long term.

Recommended additions:

- `stream:dlq:ingestion`
- or durable storage such as `ingestion_failures`

Use cases:

- non-recoverable job failures
- repeated gap-fill failures
- conflicting candle correction events
- validator rejects needing operator action

Silent ingestion failure is a first-class risk.

## Observability Expectations

The architecture should explicitly model an observability plane.

Recommended surfaces:

- Prometheus metrics
- Grafana dashboards
- Loki or structured logs
- future alert consumer

Important metrics:

- `ws_connected`
- `last_candle_lag_seconds`
- `gap_fill_pending_count`
- `failed_jobs_count`
- `duplicate_candle_count`
- `runtime_restarts_total`
- `candle_publish_latency_ms`

## Downstream Safety Chain

Current direct downstream consumers:

- `signal_app`
- `strategy_app`

Target trading chain:

- `ingestion_app -> signal_app -> strategy_app -> risk_app -> execution_app`

Safety rule:

- `strategy_app` must not bypass `risk_app` to place live orders

## Storage Policy

Current storage classes:

- canonical market history
  - `ohlcv`
  - `open_interest`
  - `funding_rate`
  - compressed after `14 days`
  - retained for `180 days`
- rebuildable raw data
  - `ticks`
  - compressed after `1 day`
  - retained for `30 days`
- rebuildable derived data
  - `l2_depth_features`
  - compressed after `7 days`
  - retained for `90 days`

## What Is Implemented Now

Current architecture coverage reflected by this doc set:

- registry-backed lifecycle control
- canonical manifest keys and lifecycle stream
- runtime reconciler and per-asset runtime handles
- websocket ingestion and closed-candle publication
- gap-fill / purge / depth / top-up jobs
- ingestion status, events, ops-summary, and scraper bridge routes
- Timescale retention/compression bootstrap

## What Still Needs Hardening

Explicit review items still needing formalization:

- lifecycle command/event idempotency identifiers
- REST vs websocket source-precedence policy
- candle finality and provisional-candle contract
- DLQ or durable failure sink
- validator contract before downstream candle publication
- parity checklist for historical versus live candle semantics

## What Is Intentionally Deferred

Not owned here yet:

- alert policy engine
- downstream strategy/risk semantics
- frontend-oriented API aggregation
- cross-app incident response workflows beyond emitted events

## Review Order

For high-level review, read in this order:

1. `docs/architecture/ingestion_app/overview.d2`
2. `docs/architecture/ingestion_app/io.d2`
3. `docs/architecture/ingestion_app/catalog.yaml`
4. `src/apps/ingestion_app/README.md`

Then move into LLD/code in this order:

1. `src/apps/ingestion_app/control_plane/service.py`
2. `src/apps/ingestion_app/runtime/reconciler.py`
3. `src/apps/ingestion_app/runtime/bootstrap.py`
4. `src/apps/ingestion_app/runtime/websocket.py`
5. `src/apps/ingestion_app/jobs/`

## Validation Modes

- focused repo validation
  - pytest slices for storage bootstrap, cleanup, and runtime transitions
- deep runtime boundedness validation
  - `scripts/qa/ingestion_runtime_memory_soak.py`
- final infra validation
  - Docker/local Valkey + Timescale layer-by-layer verification

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
