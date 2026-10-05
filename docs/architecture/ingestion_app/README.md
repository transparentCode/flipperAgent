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

The application is composed in `bootstrap.py` as one FastAPI process. Internal
imports follow this dependency order; packages may import their own package or a
lower-numbered layer, while distinct packages in the same layer do not import
each other.

| Layer | Packages / modules |
| --- | --- |
| 0 | `domain`, `settings`, `transport` |
| 1 | `observability`, `planning` |
| 2 | `providers` (including `providers/binance_usdm`), `storage` |
| 3 | `publication` |
| 4 | `services` |
| 5 | `runtime` |
| 6 | `control` |
| 7 | `api` |
| 8 | `bootstrap`, `main` |

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

Startup base-history catch-up uses the largest configured target timeframe as
its minimum floor and extends that floor to `recovery.startup_history_days` when
configured. Production uses 120 days. The request-issuing missing-HTF-bucket
scan stays bounded by the largest target timeframe. Missing derived buckets older
than that, back to the startup history window, are rebuilt only from base candles
already stored; that step never triggers provider recovery and never blocks
startup. Both existence checks read only candle open times. Candle retention is
400 days, leaving at least 30 days beyond the largest configured Decision
history requirement.

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
2. perform bounded startup base-history catch-up from Timescale state, using the
   configured startup history floor (120 days in production) or the largest
   target timeframe when unset. A lane with no stored candle first probes its
   historical providers for the first closed candle inside that window and
   starts catch-up there (see "Lane history start"); a lane with a stored
   candle is not probed;
3. rebuild missing derived buckets older than the largest target timeframe, back
   to the startup history window, from base candles already stored (never
   requesting recovery); then reconcile latest closed HTF buckets and every
   missing closed bucket within the largest target timeframe;
   A lane whose history cannot be prepared (no closed candle in the window, or
   recovery exhausted for that lane) is excluded from this generation's live
   admission and repaired in the background; the other lanes continue (see
   "Lane fault isolation");
4. open the Binance websocket for the admitted lanes only after recovery
   closure completes;
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
Historical SDK calls remain in their adapter modules under
`providers/binance_usdm/`; `providers/binance_usdm/rest_decode.py` contains pure
row decoders. The Native and CCXT decoders deliberately retain
their different out-of-window invalid-value ordering and error contracts rather
than introducing a branching shared loop. `providers/binance_usdm/websocket.py`
remains the orchestration facade and builds one connection-scoped
`providers/binance_usdm/websocket_pump.py` per stream, which owns the queue,
failure state, and consumer/watchdog loop; `providers/binance_usdm/websocket_session.py`
owns the Binance SDK factory/subscription/stop lifecycle,
`providers/binance_usdm/websocket_bridge.py` owns the bounded callback-thread
bridge, and `providers/live_sequence.py` owns consumed sequence, recovery-range,
and causal liveness state. The existing
`providers/binance_usdm/websocket_decode.py` remains the distinct pure payload decoder
and receives the receive-time sampling seam only at finalized observation
construction. The pump retains one multiplexed connection and one consumer
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
`src/apps/ingestion_app/transport/ownership.py`. The historical REST adapters
share their lifecycle plumbing in
`src/apps/ingestion_app/providers/owned_historical.py`: the admission state, the
idle barrier behind `wait_until_idle()`, the rate-limit gate, and the `close()`
state machine. Provider adapters retain their own SDK request construction,
decoding, error classification, retry/fallback, exclusive-admission rule, and SDK
close call at the adapter boundary.

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

#### Where new code goes

A new venue-specific provider belongs under `providers/<venue>/` with one
explicit construction branch in `providers/factory.py`; this fixed deployment
does not build a provider registry or plugin-discovery mechanism.

An SDK-backed historical provider subclasses
`providers/owned_historical.OwnedHistoricalProvider`, which owns admission state,
the idle barrier, the rate-limit gate, and close. The adapter supplies its
request, error classification, decoding, admission rule, and close call.

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
and runtime metrics. `/health/ready` fails closed when the runtime is not started,
is in `ERROR`, or has remained outside `LIVE` for more than five minutes while
desired `RUNNING` with enabled assets; `/health/live` represents process liveness.

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
the same reconnect backoff and retries through normal DB-first startup catch-up.
When the exhausted request names its lane, the next preparation excludes that
lane instead of failing the whole runtime ("Lane fault isolation"). The
interruption recovery and the retry run in one foreground cycle at a time; the
only concurrent recovery work is the background repair of excluded lanes, which
touches only those lanes.
Only completed non-rate-limit provider-availability failures enter the bounded
provider retry/fallback path. Deterministic provider contract, market-data
validation, authentication/client, canonical, non-availability database, and
lifecycle failures fail closed. Storage availability errors use the supervisor's
bounded reconnect-backoff retry described below.

### Rate limiting

Binance native HTTP 418/429 and CCXT `RateLimitExceeded`/`DDoSProtection`
responses become `ProviderRateLimitedError` with a numeric `Retry-After` delay;
an unusable or missing header uses the fixed 60-second fallback. Each historical
provider instance keeps a monotonic in-memory gate and refuses new REST calls
until it opens. Recovery stops the current page immediately, without retrying or
falling through to the other adapter because both share the Binance IP limit.
The supervisor remains `RECOVERING` and waits for the greater of the normal
reconnect backoff and the reported delay; stop still cancels that wait. Other
4xx responses remain fatal. The gate is process-local and is not shared between
native and CCXT adapter instances.

Control cancellation during that repair is consumed as a runtime transition;
external cancellation propagates after the supervisor publishes `STOPPED`; a
typed transport deadline is latched as fatal `ERROR`; canonical conflicts,
invalid contracts, non-availability database failures, and other unclassified
non-exhaustion errors retain their error log and `ERROR` state. Storage
availability exceptions instead remain in `RECOVERING` and retry after the
configured reconnect backoff. These branches are characterized in the runtime
supervisor tests.

### Startup derived-history completeness

After bounded base-history catch-up, startup reconciles the latest closed bucket
for each configured HTF and checks every closed target bucket inside the startup
lookback (the largest target timeframe). Existing derived rows are left
untouched; missing rows are materialized only from complete canonical provider
base candles. Buckets whose base constituents are incomplete produce the
existing bounded recovery request, except a bucket that begins before the
lane's first stored base candle (see "Lane history start"). The `as_of` close
boundary prevents an open HTF bucket from being published.

When `recovery.startup_history_days` makes the startup history window longer than
that lookback, a separate step first rebuilds missing derived buckets that start
before the lookback, back to the start of the history window. It reads only the
stored open times of each target lane and of the base lane, and builds a bucket
only when every base candle it needs is already stored. It never issues a
recovery request and never blocks startup, so a bucket over a range whose base
candles are missing stays missing and needs manual recovery. This step is what
completes derived history after an interrupted deep catch-up.

### Lane history start

An instrument listed more recently than the startup history window has no
candles before its listing, so the first recovery page from the floor can never
be complete and the lane could never finish startup. Startup therefore applies
these rules:

- A lane with no stored candle is probed once per preparation cycle by
  `RecoveryEngine.find_history_start`: a one-candle (`limit=1`) request over
  `[startup floor, closed boundary)`. Providers are tried in lane order with the
  same attempt, backoff, rate-limit, and deadline handling as a recovery page;
  an empty answer moves on to the next provider, and a result is validated like
  a page (bounds, grid, closed at request start). The probe commits nothing,
  does not wait for REST finalization, and takes no lane lock. If no provider
  answers, it raises the usual provider-exhaustion error and startup retries.
- Catch-up starts at the first candle the probe found. When that candle is
  later than the startup floor, the supervisor logs one warning with the lane,
  the floor, the first candle time, and the difference between them. The probe
  result is trusted: if a provider wrongly reports a later first candle, the
  lane's history starts late and is not extended automatically; a manual
  `/runtime/recover` over the earlier range is the correction.
- If providers answered but none has a closed candle in the window, the lane is
  excluded with reason `no_closed_candle_in_window` and retried in the
  background (see "Lane fault isolation"); the other lanes go live. If every
  lane is in that state the preparation raises a provider-exhaustion error and
  the runtime retries every lane after the reconnect backoff, as before.
- A derived bucket that begins before the lane's first stored base candle (no
  base candle is stored before it) is neither built nor requested, because its
  missing leading candles do not exist. The rule relies on one lane's recovery
  requests being processed in ascending time order under the lane lock. A
  candle missing after the first stored one is still a gap: the follow-up
  request starts at the first stored candle.
- Any gap after a lane's first stored candle is repaired; if recovery is
  exhausted for that lane it is excluded with reason `recovery_exhausted` and
  retried in the background.
- A cold start stores base candles from exactly the startup floor, and derived
  history starts at the first grid start at or after it. A bucket that
  straddles the floor is no longer repaired backwards past the floor.

### Lane fault isolation

One instrument whose history cannot be prepared no longer holds every other
instrument out of live ingestion. State is scoped to one supervisor generation,
so reconnect, settings replacement, manual recovery and resume retry every lane.

- Foreground preparation (`_prepare_live_connection`) excludes a lane when the
  history-start probe finds no closed candle, or when a `RecoveryExhaustedError`
  that is not a `RecoveryRateLimitedError` names a lane being prepared (the
  error carries `lane`). It logs a WARNING with the lane, reason and next retry
  time and prepares the remaining lanes with no sleep between passes. Rate
  limits, storage outages, `TransportDeadlineExceeded`, conflicts and any error
  without a lane are not lane faults and behave as before. If no lane is left
  the exclusions are cleared and the last error is raised, which is the
  previous all-lanes-faulty behaviour.
- The websocket subscribes only to admitted lanes; an observation for another
  lane is rejected as an unknown lane.
- After the stream is created, one background task retries each excluded lane
  every 60 seconds (a longer rate-limit delay is honoured) using the same
  preparation as startup. It still commits the base candles and complete
  derived buckets it can fetch. A storage outage or exhaustion only
  reschedules the lane; any other error, including a transport deadline, is
  stored and raised by the live loop after its next observation, with today's
  fatal handling. The task is cancelled and awaited before the stream closes
  and so never overlaps foreground preparation.
- When a lane is repaired the live loop ends cleanly after its next processed
  observation and the next cycle starts at once (no reconnect backoff) and
  admits the lane. A lane whose hole has aged out of the lookback window is
  admitted as before.
- Faults during interruption recovery or a live follow-up use the existing
  recoverable path; the next preparation excludes the lane.
- `/runtime` lists `excluded_lanes` (venue, instrument_id, reason, detail,
  excluded_since, next_retry_at, UTC). The observable gauge
  `ingestion.lane.excluded` (0/1 by venue and instrument_id) covers every
  planned lane. `last_error` semantics are unchanged.

### Manual recovery

The API rejects a manual recovery `since` older than the configured candle
retention with HTTP 422. If an ordinary manual recovery fails after the active
generation has stopped, the controller restores the saved runtime checkpoint
using a fresh generation; a previously paused runtime remains paused. A typed
transport deadline or quarantine remains fatal and is not rolled back.

An unresolved websocket factory, subscription, or stop deadline, or a failed
transport cleanup, is a fatal transport condition with an operation-specific
diagnostic. The controller synchronizes that state before pause, resume,
reconnect, replacement, recovery, or close gates, so a quarantined supervisor
cannot be replaced or hidden by a late cleanup callback.

### Database unavailable

Storage availability errors keep the runtime in `RECOVERING` and retry the
normal live-connection preparation after the configured reconnect backoff. Other
database errors, including constraint and data errors, remain fatal and keep the
runtime in `ERROR`.

### Readiness

`/health/ready` returns 503 with reason `runtime_not_live` after the runtime has
remained outside `LIVE` for more than five minutes when desired state is
`RUNNING` and at least one asset is enabled. This delay does not apply while
paused, with no enabled assets, or before the five-minute threshold is exceeded.
Existing not-started and `ERROR` readiness failures remain unchanged. While some
lanes are excluded (see "Lane fault isolation") readiness stays 200 but reports
`status: "degraded"` instead of `"ready"`.

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

**Validation boundaries.** Data is validated where it enters the application:
configuration in `settings.py`, HTTP request bodies in `api/routes.py`, provider
payloads in the REST and websocket decoders and
`_validate_provider_observations`, and database rows where they are read back.
The domain dataclasses and the plan dataclasses (`LanePlan`, `IngestionPlan`)
enforce their own invariants on top of that. Modules inside `ingestion_app` do
not re-check each other's argument types or settings that `IngestionSettings`
has already validated.

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
| G6 — lifecycle versions are constant | `control/asset_lifecycle.py:88-100` | Record `asset_version=1` and `timeframe_version=1`; no lifecycle migration. |
| G7 — duplicate lifecycle-ID helpers | `control/asset_lifecycle.py:48-64`; `libs/common/asset_manifest.py:131-139` | Record the differing formulas; no consolidation. |

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

Render the canonical SVGs from the repository root with:

```bash
./scripts/render_d2.sh docs/architecture/ingestion_app/overview.d2 docs/architecture/ingestion_app/overview.svg
./scripts/render_d2.sh docs/architecture/ingestion_app/io.d2 docs/architecture/ingestion_app/io.svg
./scripts/render_d2.sh docs/architecture/ingestion_app/lifecycle_sequence.d2 docs/architecture/ingestion_app/lifecycle_sequence.svg
```
