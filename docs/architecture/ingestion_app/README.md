# `ingestion_app` Architecture

This folder is the high-level and detailed architecture handoff for the current
canonical `ingestion_app` implementation.

It answers four questions:

1. what the app owns;
2. how live and recovered market data become canonical candles;
3. how canonical state is persisted and published downstream; and
4. how runtime/config/lifecycle failures are contained.

## Files

- `catalog.yaml` — machine-readable architecture and contract inventory
- `overview.d2` — HLD component/dependency view
- `io.d2` — detailed data, storage, stream, and API contract view
- `lifecycle_sequence.d2` — startup, live, interruption/recovery, config mutation,
  and shutdown sequences
- this file — narrative HLD and review guide

## Purpose

`ingestion_app` is the canonical market-data acquisition and normalization
service. It owns:

- typed provider/instrument/timeframe configuration;
- live Binance Futures websocket ingestion;
- Binance-native and CCXT historical providers;
- bounded causal gap recovery;
- canonical 1m candle persistence;
- higher-timeframe aggregation from the configured base timeframe;
- transactional candle + outbox commits;
- bounded Valkey stream publication;
- canonical asset manifest/lifecycle projection;
- dynamic asset config create/patch with rollback;
- runtime pause/resume/reconnect/manual-recovery control;
- retention housekeeping and ingestion observability.

It does **not** own feature computation, strategy decisions, risk decisions,
execution, portfolio accounting, or alert policy.

## Canonical Naming Boundaries

The implementation package, active configuration, persisted storage, and
transport contracts use one canonical ingestion identity.

| Concern | Canonical identity |
| --- | --- |
| Python package | `apps.ingestion_app` |
| Active config directory | `configs/ingestion/` |
| Active config namespace | `ingestion` |
| Compose service | `ingestion` |
| Timescale schema | `ingestion` |
| Candle stream protocol | `stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}` |
| Manifest source authority | `ingestion` |
| OTEL / metric identity | `ingestion` |
| Candle event producer | `ingestion` |

These identities are one shared external contract across the Python package,
configuration, storage, transport, and downstream consumers.

## High-Level Architecture

The application is composed in `bootstrap.py` as one FastAPI process with six
cooperating layers.

### 1. Configuration and control plane

`settings.py` validates global/provider/timeframe settings plus one YAML file per
asset under `configs/ingestion/assets/`.

`api/routes.py` exposes:

- liveness/readiness;
- runtime snapshot;
- asset list/read/create/patch;
- provider inventory;
- runtime pause/resume/reconnect;
- bounded manual recovery.

`AssetConfigService` validates an asset mutation before writing its YAML file,
reloads the config through `ConfigManager`, swaps runtime settings atomically,
and rolls the file/runtime state back if the mutation fails or is cancelled.
There is no delete endpoint.

### 2. Runtime controller and supervisor

`RuntimeController` owns process-level desired state and replaces supervisors when
configuration changes.

`RuntimeSupervisor` resolves enabled assets into base-timeframe `MarketLane`s and
runs the data plane:

1. determine the latest closed base boundary;
2. perform bounded startup catch-up from Timescale state;
3. reconcile latest closed HTF buckets;
4. open the Binance websocket only after recovery closure completes;
5. commit each finalized base candle;
6. aggregate/reconcile affected HTFs;
7. recover detected interruptions before reconnecting.

Runtime states are `STARTING`, `RECOVERING`, `LIVE`, `STOPPED`, and `ERROR`.
Desired runtime state is `RUNNING` or `PAUSED`.

### 3. Providers and recovery

The live provider is `BinanceWebSocketManager`. Historical recovery is provider
pluggable through `HistoricalCandleProvider` and currently composes:

- `BinanceNativeHistoricalProvider`;
- `CCXTHistoricalProvider` for Binance USD-M futures.

`RecoveryEngine` performs bounded window paging, provider-order fallback,
per-lane locking, global concurrency limiting, retry/backoff, closed-candle
cutoffs, and HTF follow-up reconciliation. Recovery requests are explicit,
UTC-aware, aligned ranges; they are not an unbounded replay mechanism.

### 4. Canonicalization and Timescale persistence

Provider observations enter as immutable `CandleObservation` values and are
canonicalized to immutable `CanonicalCandle` values.

`CandleRepository` persists to:

- `ingestion.candles` — Timescale hypertable;
- `ingestion.outbox` — durable publication intents.

The primary candle identity is:

`(venue, instrument_id, timeframe, open_time)`.

A candle commit is classified as `INSERTED`, `DUPLICATE`, or `CONFLICT`.
Canonical candle insertion and outbox insertion are one database transaction, so
publication intent cannot be lost after a successful new candle commit.

### 5. HTF derivation and downstream publication

The configured base timeframe is `1m`. Higher timeframes are derived from
canonical base candles using a continuous UTC calendar and explicit alignment
origin. Derived rows carry `source_type=derived` and `source_timeframe` provenance.

The outbox publisher reads unpublished rows in order and publishes them to:

`stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}`

using bounded approximate `MAXLEN` streams. Only after a successful `XADD` is the
row marked `published_at`.

Semantics are intentionally **at least once** across the Valkey boundary. A broker
outage does not invalidate canonical ingestion: unpublished rows remain durable
and drain when the publisher reconnects. Already-published rows are not
historically replayed automatically after destructive broker loss; consumers
recover historical state from Timescale.

### 6. Asset lifecycle, retention, and observability

For assets with `owns_manifest_lifecycle=true`, the lifecycle reconciler projects
current configuration to canonical Valkey manifests:

- `asset:{symbol}`;
- `asset:{symbol}:tf:{timeframe}`;
- `asset:lifecycle`.

This is the lifecycle authority consumed by downstream apps. The persisted source
value remains `ingestion`.

`RetentionJanitor` is deliberately non-authoritative. It deletes only old
**published** outbox rows in bounded batches and drops candle chunks older than the
configured candle retention horizon. Pending outbox rows are not retention
candidates. Janitor failure is logged/retried and does not make canonical ingestion
unhealthy.

`IngestionObservability` records commit, websocket, recovery, outbox, base-candle,
and runtime metrics. `/health/ready` fails closed when the runtime is not started or
is in `ERROR`; `/health/live` represents process liveness.

## Data Ownership and Source-of-Truth Rules

### Configuration truth

`configs/ingestion/global.yaml` and `configs/ingestion/assets/*.yaml` are the
configuration source of truth for enabled assets, providers, timeframes, calendar,
runtime, publication, recovery, and retention parameters.

Asset API mutations change those files through `ConfigManager`; the runtime does
not maintain an independent mutable asset registry.

### Candle truth

Timescale `ingestion.candles` is canonical historical OHLCV truth. Valkey is a
bounded transport/state layer, not historical authority.

### Publication truth

`ingestion.outbox` is the durable bridge between canonical database commit and
Valkey publication. Pending rows are recoverable publication work; `published_at`
marks completion of that work.

### Lifecycle truth

For configured owned assets, the ingestion config is authoritative and Valkey
asset manifests/lifecycle events are its runtime projection for downstream apps.

## Failure and Recovery Contracts

### Broker unavailable

Canonical candle writes continue because the publisher connection loop is
independent of the runtime controller. Outbox rows remain pending until Valkey is
available again.

### Websocket interruption

The live provider raises `LiveStreamInterrupted` with bounded recovery requests.
The supervisor enters `RECOVERING`, closes the missing range using historical
providers, waits the configured reconnect backoff, then starts a fresh live cycle.

### Database unavailable

Canonical writes and recovery fail closed. Readiness reflects runtime failure; the
system does not acknowledge a candle that was not durably committed.

### Canonical conflict

A same-key candle with different canonical content is `CONFLICT` and is treated as
a fatal live-path data-quality error. It is not silently overwritten.

### Dynamic config failure

Candidate settings are validated before runtime replacement. Disk/runtime mutation
is rolled back on failure or cancellation. Lifecycle reconciliation is marked dirty
only after a successful config/runtime change.

### Shutdown

The application first closes the runtime controller, then retention, then the
outbox/lifecycle publisher task, then provider resources and DB pools. Certification
uses an explicit pause-and-drain sequence before stopping the process when it needs
to prove a zero-pending terminal state; normal durability does not depend on that
certification-specific quiescence rule.

## Key Invariants

- all timestamps are timezone-aware UTC;
- timeframe alignment comes from config, not implicit wall-clock assumptions;
- base candles are provider sourced; HTFs are derived from base candles;
- no HTF is published without complete constituent coverage;
- canonical conflicts never become silent updates;
- pending outbox rows survive broker failure;
- published outbox cleanup never deletes pending rows;
- recovery is bounded and cancellation-aware;
- one lane recovery is serialized by lane lock;
- enabled runtime assets are config driven;
- downstream historical recovery reads Timescale rather than assuming Valkey is a
  replay log;
- lifecycle ownership is explicit per asset.

## Downstream Contracts

`signal_app` consumes the configured ingestion OHLCV streams and reads Timescale for
startup/gap priming. It also consumes `asset:lifecycle` and canonical asset
manifests.

Other downstream apps consume signal outputs; they do not bypass ingestion's
canonical candle/storage contract.

## Rendering

If `d2` is installed:

```bash
d2 docs/architecture/ingestion_app/overview.d2 docs/architecture/ingestion_app/overview.svg
d2 docs/architecture/ingestion_app/io.d2 docs/architecture/ingestion_app/io.svg
d2 docs/architecture/ingestion_app/lifecycle_sequence.d2 docs/architecture/ingestion_app/lifecycle_sequence.svg
```

Or use `scripts/render_d2.sh` for each D2 source.
