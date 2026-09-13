# `ingestion_app` Architecture

This folder is the high-level and detailed architecture handoff for the current
canonical `ingestion_app` implementation. It retains the Phase 0 architecture
truth freeze while documenting the implemented P1A compiled-plan boundary, the
P1B deployment mount, the P1C recovery-closure boundary, the P1D historical-
provider quiescence fence, the P1E websocket watchdog, the Phase 2
controller-owned runtime state boundary, the Phase 3 neutral transport boundary,
the Phase 4 websocket responsibility decomposition, and the Phase 5 explicit
bootstrap resource ledger/final architecture freeze.

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
- `feature_map.md` — entry point -> owner -> durable effect -> regression map
- this file — narrative HLD and review guide

## Purpose

`ingestion_app` is the canonical market-data acquisition and normalization
service. It owns:

- typed provider/instrument/timeframe configuration;
- live Binance Futures websocket ingestion;
- Binance-native and CCXT historical providers;
- bounded causal gap recovery;
- canonical base-timeframe candle persistence (currently configured as `1m`);
- higher-timeframe aggregation from the configured base timeframe;
- transactional candle + outbox commits;
- bounded Valkey stream publication;
- canonical asset manifest/lifecycle projection;
- dynamic asset config create/patch with rollback when the registered config
  directory is writable;
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
asset under `configs/ingestion/assets/`. The current production asset set is
`BNB`, `BTC`, `DOGE`, `ETH`, `SOL`, and `XRP`; the set remains configuration-owned.

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
There is no delete endpoint. The application path supports this persistence only
when the registered directory is writable. Production Compose keeps the
container root and broad `./configs:/app/configs:ro` mount read-only, while
over-mounting only `./configs/ingestion/assets:/app/configs/ingestion/assets:rw`.
The registered asset directory remains the sole configuration authority; global
and other application configuration remains read-only.

### 2. Runtime controller and supervisor

`runtime/state.py` owns the shared runtime state contracts. `RuntimeController`
owns process-level desired state, composes the public `RuntimeSnapshot`, and
replaces supervisors when configuration changes. `RuntimeSupervisor` reports only
the observed state of its one current generation through an observed snapshot; it
has no desired-state policy or parked pause/resume loop. Bootstrap closes over the
composed live-provider IDs and application-owned historical-provider IDs to provide
a pure `compile_ingestion_plan()` seam. The controller compiles initial settings
once, validates candidate settings by compiling only, and passes the resulting
immutable `IngestionPlan` to a supervisor factory. Settings replacement compiles
the replacement before stopping the old generation.

Settings replacement and manual recovery take a `_RuntimeCheckpoint` containing
the last-known-good settings and compiled plan; `_stop_for_transition(operation)`
drains the old generation, awaits the composed historical-provider idle barrier,
checks post-stop quarantine, and only then detaches it. Reconnect retains its
deliberate no-rollback behavior. Cancellation restoration awaits the same barrier
before installing the exact checkpoint settings and compiled plan, and preserves
the caller cancellation after restoration.

`planning.py` compiles enabled assets into immutable, deterministically ordered
`LanePlan` values containing the live symbol, historical provider order, provider
symbols, target durations, and bounded lookback. `RuntimeSupervisor` consumes that
plan and runs the data plane; it no longer owns settings-to-lane compilation.
Pause is a controller operation that sets desired `PAUSED` and signals the current
generation to stop without waiting for provider quiescence. Resume awaits that
generation's cleanup and the P1D provider barrier, then installs and starts a fresh
generation only after the gates pass.
`_run_live_or_interruption_cycle` keeps stream-interruption conversion local while
the run loop has one common cancellation/deadline/ordinary failure boundary:

1. determine the latest closed base boundary;
2. perform bounded startup catch-up from Timescale state;
3. reconcile latest closed HTF buckets;
4. open the Binance websocket only after recovery closure completes;
5. commit each finalized base candle;
6. aggregate/reconcile affected HTFs;
7. recover detected interruptions before reconnecting.

Runtime states are `STARTING`, `RECOVERING`, `LIVE`, `STOPPED`, and `ERROR`.
Desired runtime state is `RUNNING` or `PAUSED`.

### Bootstrap resource ownership

`create_application()` keeps service construction explicit. The private
`_LifespanResources` value is only a cleanup ledger: it records the injected or
newly created `ConfigManager`, the DB-cleanup-required flag, app-owned historical
provider resources, the controller, the retention janitor/task, and the
publisher task. It is not a service container, dependency-injection registry, or
configuration authority.

The lifespan startup order remains:

```text
settings/provider validation
  -> DB pools and schema
  -> historical providers and one Binance websocket facade
  -> repository/services/recovery/controller/lifecycle/retention construction
  -> RuntimeController.start()
  -> app.state installation
  -> retention task and publisher task
```

The ledger closes resources in this exact order:

```text
RuntimeController.close()
  -> RetentionJanitor.stop() + retention task reap
  -> publisher connection-loop task reap
  -> historical providers in reverse construction order
  -> DBPoolManager.close_pools()
  -> ConfigManager.shutdown()
```

The DB cleanup flag is set before `init_db_pools()` so an initialization failure
still attempts DB cleanup. Provider-factory partial construction retains its own
close-on-failure behavior; the outer ledger takes ownership only after that
factory succeeds. Background tasks are recorded/started only after controller
startup succeeds, preserving the no-orphan partial-startup contract.

### 3. Providers and recovery

The live provider is `BinanceWebSocketManager`. Historical recovery is provider
pluggable through `HistoricalCandleProvider` and currently composes:

- `BinanceNativeHistoricalProvider`;
- `CCXTHistoricalProvider` for Binance USD-M futures.

`providers/factory.py` owns provider-reference validation and construction while
the bootstrap retains resource ownership and partial-construction cleanup.
Historical SDK calls remain in their adapter modules; `providers/binance_rest.py`
contains pure row decoders. The Native and CCXT decoders deliberately retain
their different out-of-window invalid-value ordering and error contracts rather
than introducing a branching shared loop. `runtime/websocket.py` remains the
orchestration facade: `runtime/websocket_session.py` owns the Binance SDK
factory/subscription/stop lifecycle, `runtime/websocket_bridge.py` owns the
bounded callback-thread bridge, and `runtime/websocket_sequence.py` owns
consumed sequence, recovery-range, and causal liveness state. The existing
`runtime/binance_websocket_decode.py` remains the distinct pure payload decoder
and receives the receive-time sampling seam only at finalized observation
construction. The facade retains one multiplexed connection and one consumer
loop; the sequence tracker derives the earliest causal per-lane silence deadline
from the connection anchor or the last consumed finalized close. A silent
half-open raises the existing recoverable interruption contract with reason
`websocket_silence_detected`; forming and duplicate finalized traffic do not
reset liveness, and no additional timeout/config authority is introduced.

`RecoveryEngine` performs bounded window paging, provider-order fallback,
per-lane locking, global concurrency limiting, retry/backoff, closed-candle
cutoffs, HTF follow-up reconciliation, and the recursive recovery closure.
The closure owns global identity deduplication and breadth-first follow-up
processing, dispatching deterministic chunks of at most `max_concurrency` while
the existing semaphore remains a second provider-work bound. Recovery requests
are explicit, UTC-aware, aligned ranges; they are not an unbounded replay
mechanism.

#### Transport deadlines and ownership

Provider attempt and websocket lifecycle deadlines are configuration-owned and
default to 30 seconds. A native REST attempt is executed through one owned
daemon wrapper worker and the SDK receives the same configured timeout as a
defense in depth. A CCXT attempt owns `load_markets`, symbol resolution, and the
raw request together under one bounded task. Websocket factory, subscription,
and stop operations use the same ownership boundary; native REST session close
and CCXT exchange close are bounded provider cleanup operations.

The neutral owned-call and historical admission/accounting mechanics live in
`src/apps/ingestion_app/transport/ownership.py`. Provider adapters retain their
own SDK request construction, decoding, error classification, retry/fallback,
and cleanup policy at the adapter boundary.

Provider admission is limited by `recovery.max_concurrency` without an
unbounded provider wait queue. Caller cancellation abandons the result but does
not release a slot until the worker or task actually finishes. A completed
`ProviderAvailabilityError` whose ownership is known to be released follows the
existing retry/fallback path; malformed responses, invalid metadata or symbols,
authentication/client errors, and lifecycle errors fail closed. If a deadline
expires while ownership is unresolved, or cleanup fails, the provider/lifecycle
is quarantined and the runtime remains in `ERROR`; later completion releases the
lease but never clears the sticky quarantine. The implementation does not claim
to hard-stop a running SDK operation or its own socket-manager thread. The
historical providers expose `wait_until_idle()` over their existing owned-call
tracking; the factory composes one bounded concurrent barrier over unique provider
objects. A generation transition waits at that barrier before reopening fresh
historical admission. A quiescence deadline raises typed
`TransportDeadlineExceeded`, quarantines the provider/controller, and never enters
availability retry/fallback. Barrier wait cancellation does not cancel the
underlying SDK operation, and barrier tasks are always awaited on failure. Closure
child tasks are created only for the current bounded chunk. A failure or
cancellation cleans up unfinished siblings before propagating the original
exception; later chunks are not started.

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

Production currently configures the base timeframe as `1m`; this is the current
configuration value, not an architectural invariant. Runtime logic derives the
effective base timeframe from configuration. Higher timeframes are derived
from canonical base candles using a continuous UTC calendar and explicit
alignment origin. Derived rows carry `source_type=derived` and
`source_timeframe` provenance.

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

This is the lifecycle authority consumed by `decision_app`, `alert_app`, and
`risk_app` through the shared manifest/lifecycle contracts. The persisted source
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

Asset API mutations change those files through `ConfigManager` when the
registered directory is writable; the runtime does not maintain an independent
mutable asset registry. Production Compose keeps the container root and broad
`./configs:/app/configs:ro` mount read-only, while over-mounting only
`./configs/ingestion/assets:/app/configs/ingestion/assets:rw`. The registered
asset directory is therefore the sole writable configuration surface and the
existing atomic POST/PATCH path is deployable; global and other application
configuration remain read-only (G1 closed by P1B).

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

## External Compatibility Matrix

These are the live downstream surfaces frozen for the refactor. The consumers
use the external schema/stream/manifest contracts; they do not import ingestion
implementation packages as their runtime integration boundary.

| Surface | Producer / authority | Current consumers | Phase 0 status |
| --- | --- | --- | --- |
| `ingestion.candles` | `ingestion` / Timescale canonical history | `decision_app` read-only canonical history adapter | frozen |
| `candle.committed` v1 streams: `stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}` | `ingestion` transactional outbox publisher | `decision_app` live input cursor/parser | frozen |
| `asset:{symbol}` and `asset:{symbol}:tf:{timeframe}` manifests | ingestion-owned Valkey projection | `decision_app` manifest gating; `risk_app` manifest availability/worker gating | frozen |
| `asset:lifecycle` | ingestion lifecycle projection | `decision_app` lifecycle reader; `alert_app` lifecycle consumer/normalizer; `risk_app` lifecycle watcher | frozen |
| ingestion control API | `ingestion_app` FastAPI routes | operator and control clients | frozen |

The live evidence is the Decision stream adapter and history repository
([`transport/ingestion.py`](../../../src/apps/decision_app/transport/ingestion.py),
[`storage/market_history.py`](../../../src/apps/decision_app/storage/market_history.py)),
the Decision lifecycle reader, and the Alert/Risk lifecycle consumers. There is
no current `src/apps/signal_app` package; former Signal/Strategy references are
historical and are not current ingestion consumers.

## Broker-bound startup ordering

The optional broker connection loop has a deliberate causal order in
[`bootstrap.py`](../../../src/apps/ingestion_app/bootstrap.py):

```text
broker connection
  -> bind manifest store
  -> initial lifecycle reconcile_all
  -> start lifecycle reconciler
  -> start OutboxPublisher
```

This ordering ensures that downstream runtime identity is reconciled before
candle publication begins on that connection cycle. It is not accurate to model
manifest projection and candle publication as fully independent broker loops.
The broker loop may retry while canonical Timescale/runtime work remains alive,
but a successful cycle preserves the ordering above.

## Failure and Recovery Contracts

### Broker unavailable

Canonical candle writes continue because the publisher connection loop is
independent of the runtime controller. Outbox rows remain pending until Valkey is
available again.

### Websocket interruption

The live provider raises `LiveStreamInterrupted` with bounded recovery requests.
Close, error, malformed, gap, overflow, and causal silence interruptions all use
the same recovery-range construction. For silence, the watchdog evaluates the
earliest lane deadline across the subscriptions, gives already-admitted queue or
bridge work one bounded event-loop opportunity, then recomputes overdue lanes.
The watchdog uses the evaluation timestamp for the recovery range and never
converts pause, stop, or outer cancellation into a silence interruption.
The supervisor enters `RECOVERING`, closes the missing range using historical
providers, waits the configured reconnect backoff, then starts a fresh live cycle.
If every configured provider completes its bounded attempts but the page remains
incomplete, `RecoveryExhaustedError` keeps the supervisor in `RECOVERING`. It waits
the same reconnect backoff and retries through normal DB-first startup catch-up;
only one bounded recovery cycle is active, so retries do not accumulate work.
Only completed provider-availability failures enter the bounded provider
retry/fallback path. Deterministic provider contract, market-data validation,
authentication/client, canonical, database, and lifecycle failures fail closed.

Control cancellation during that repair is consumed as a runtime transition;
external cancellation propagates after the supervisor publishes `STOPPED`; a
typed transport deadline is latched as fatal `ERROR`; canonical conflicts,
invalid contracts, database failures, and other non-exhaustion errors retain their
error log and `ERROR` state. These branches are characterized in the runtime
supervisor tests.

An unresolved websocket factory, subscription, or stop deadline, or a failed
transport cleanup, is a fatal transport condition with an operation-specific
diagnostic. The controller synchronizes that state before pause, resume,
reconnect, replacement, recovery, or close gates, so a quarantined supervisor
cannot be replaced or hidden by a late cleanup callback.

### Database unavailable

Canonical writes and recovery fail closed. Readiness reflects runtime failure; the
system does not acknowledge a candle that was not durably committed.

### Canonical conflict

A same-key candle with different canonical content is `CONFLICT` and is treated as
a fatal live-path data-quality error. It is not silently overwritten.

### Dynamic config failure

Candidate settings are validated before runtime replacement. When the config path
is writable, disk/runtime mutation is rolled back on failure or cancellation and
lifecycle reconciliation is marked dirty only after a successful config/runtime
change. The production Compose deployment supplies the narrow writable asset
directory described in Configuration truth; the application-level mutation and
rollback contract is unchanged.

### Shutdown

The application cleanup ledger first closes the runtime controller, then stops
and reaps retention, reaps the outbox/lifecycle publisher task, closes historical
providers in reverse resource order, closes DB pools, and finally shuts down the
ConfigManager. Controller/provider/DB cleanup failures retain their existing
logging/isolation behavior, and no new shutdown retry framework is introduced.
Certification uses an explicit pause-and-drain sequence before stopping the
process when it needs to prove a zero-pending terminal state; normal durability
does not depend on that certification-specific quiescence rule.

## Key Invariants

- all timestamps are timezone-aware UTC;
- timeframe alignment comes from config, not implicit wall-clock assumptions;
- base candles are provider sourced; HTFs are derived from base candles;
- no HTF is published without complete constituent coverage;
- canonical conflicts never become silent updates;
- pending outbox rows survive broker failure;
- published outbox cleanup never deletes pending rows;
- recovery is bounded and cancellation-aware;
- provider and websocket lifecycle deadlines are finite, configuration-owned,
  and default to 30 seconds;
- transport ownership and admission remain held until actual SDK/task cleanup;
- unresolved deadline or cleanup state is sticky quarantine and keeps readiness
  failed;
- completed provider-availability failures alone use bounded retry/fallback;
  deterministic provider contract failures fail closed;
- one lane recovery is serialized by lane lock;
- enabled runtime assets are config driven;
- downstream historical recovery reads Timescale rather than assuming Valkey is a
  replay log;
- lifecycle ownership is explicit per asset.

## Downstream Contracts

`decision_app` directly parses the configured ingestion OHLCV streams, reads
canonical history from Timescale for startup/gap priming, and consumes
ingestion-owned manifests/lifecycle notifications. `alert_app` consumes and
normalizes `asset:lifecycle`. `risk_app` consumes canonical asset manifests and
`asset:lifecycle` for runtime availability and worker/listener gating.

There is no current `src/apps/signal_app` consumer. Other downstream apps do not
bypass ingestion's canonical candle/storage contract.

## Phase 1 known gaps (remaining; P1A closed G2; P1B closed G1; P1C closed G4; P1D closed G3; P1E closed G5)

| Gap | Live source evidence | Phase 0 disposition |
| --- | --- | --- |
| G6 — lifecycle versions are constant | `services/asset_lifecycle.py:88-100` | Record `asset_version=1` and `timeframe_version=1`; no lifecycle migration. |
| G7 — duplicate lifecycle-ID helpers | `services/asset_lifecycle.py:48-64`; `libs/common/asset_manifest.py:131-139` | Record the differing formulas; no consolidation. |

P1A closed G2 by moving settings-to-lane/runtime compilation into the pure
`planning.py` compiler. Candidate validation no longer constructs a supervisor or
changes observability, and cancellation checkpoints retain the compiled plan
alongside settings. The direct regression is anchored in
`tests/ingestion/runtime/test_controller.py`.

P1B closed G1 at the deployment boundary without changing the mutation
algorithm. The ingestion service remains root-read-only and retains the broad
read-only `/app/configs` mount; only the existing registered
`/app/configs/ingestion/assets` directory is over-mounted read-write, so the
existing atomic POST/PATCH YAML path is usable in normal Compose deployment.

P1C closed G4 by moving sorted global deduplication, breadth-first follow-up
closure, and bounded chunk dispatch into `RecoveryEngine`. `RuntimeSupervisor`
now submits startup, HTF, interruption, and manual recovery requests through
`recover_closure(requests, plan=self.plan)`; the raw single-request `recover()`
primitive, lane lock, semaphore, provider ordering, and failure categories are
unchanged.

P1D closed G3 by making historical-provider ownership release an explicit
generation-transition fence. Binance-native and CCXT providers expose
`wait_until_idle()` over their owned-call/admission state; the factory composes
one bounded barrier, and the controller crosses it before fresh admission on
resume, reconnect, settings replacement, recovery, and cancellation rollback.
A quiescence deadline is a typed fatal transport condition with sticky provider
quarantine; it is not availability retry/fallback.

P1E closed G5 by bounding the existing multiplexed websocket consumer wait with
one causal per-lane deadline calculation. The deadline is
`last_close + 2 * timeframe_duration`, where an unprogressed lane uses the
connection anchor. Only accepted finalized progress moves a lane deadline;
forming and duplicate messages do not. At a deadline, already-admitted queue or
bridge work is observed through one bounded snapshot before the overdue lanes
are recomputed. A remaining overdue lane raises
`websocket_silence_detected`, uses the existing recovery-range helper, and
preserves cancellation and existing close/error/gap/overflow precedence. No
per-lane task, timer, connection, config field, or external contract was added.

## Approved future direction (later phases not implemented)

The planned bootstrap/resource cleanup is implemented and frozen by Phase 5.
Neutral transport ownership, websocket responsibility decomposition,
controller/supervisor state clarification, and the ordered bootstrap cleanup
ledger are implemented boundaries in this checkout. P1A through P1E and Phases
2 through 5 change internal runtime composition, deployment mounting, recovery
orchestration, generation fencing, transport ownership, websocket responsibility,
and lifecycle cleanup without changing configuration, schemas, external
contracts, or the existing runtime state machine. G6 lifecycle-version changes
and G7 lifecycle-event-ID consolidation remain explicitly open/deferred.

## Rendering

If `d2` is installed:

```bash
d2 docs/architecture/ingestion_app/overview.d2 docs/architecture/ingestion_app/overview.svg
d2 docs/architecture/ingestion_app/io.d2 docs/architecture/ingestion_app/io.svg
d2 docs/architecture/ingestion_app/lifecycle_sequence.d2 docs/architecture/ingestion_app/lifecycle_sequence.svg
```

Or use `scripts/render_d2.sh` for each D2 source.
