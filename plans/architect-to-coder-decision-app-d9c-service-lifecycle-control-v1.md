---
goal: Wrap approved D9A startup and D9B bounded live transactions in the real decision_app ASGI service lifecycle, manifest-driven runtime generation rebuilds, control plane, graceful shutdown, and bounded runtime observability without adding PriceRelay, cutover, or new model semantics
stage: architect-to-coder
date_created: 2026-08-14
last_updated: 2026-08-14
owner: quant-orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d9c, service, lifecycle, fastapi, runtime, control]
---

# Architect-to-coder — `decision_app` D9C service / lifecycle / control

## 1. Starting point

Use only the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Approved before D9C:

```text
D0–D8
D7A SR adapter
D9A startup / restart reconstruction
D9B bounded direct-input / live signal transaction
```

D7B remains deferred to the parallel model-refactor stream.

The approved hot path is already frozen and must remain authoritative:

```text
D9A STARTUP_READY
        ↓
D9B direct XREAD
        ↓
canonical BarStore / InputReadCursor
        ↓
causal lane view
        ↓
D6 prepare_live
        ↓
D8 policy
        ↓
NO_SIGNAL
or
SIGNAL -> exact-ID signal publication
        ↓
D8 finalizer
        ↓
state + LaneCommitWatermark
        ↓
latest-state checkpoint
```

D9C wraps this proven primitive in the application/service shell. It must not redesign the primitive.

Do not commit, merge, push, switch branches, reset, restore, or modify the primary checkout.

---

# 2. Objective

Implement a real long-running **ASGI-owned decision service** with:

```text
FastAPI lifespan
    ↓
load strict decision config
init DB pools + checkpoint schema
create one Valkey client
capture lifecycle tail
build D9A startup generation
build D9B live runtime
    ↓
DecisionService
    ├─ market poll loop
    │    └─ approved D9B poll_once()
    ├─ lifecycle notification loop
    │    └─ asset:lifecycle direct XREAD
    ├─ bounded runtime-generation rebuild
    ├─ pause/resume/reconnect control
    └─ cached bounded status / health
    ↓
FastAPI control plane
```

D9C must prove the app can own, start, supervise, rebuild, pause, resume, and gracefully stop the already-approved D9A/D9B runtime without changing market/decision semantics.

---

# 3. Hard non-goals

Do **not** implement in D9C:

```text
PriceRelay
price_update:* publication
PriceRelay gap / catch-up semantics
risk_app changes
execution_app changes
signal_app / strategy_app changes
D7B Momentum refactor/integration
new model plugins
new quantitative parameters
portfolio allocation
shadow parity
resource certification
production cutover
legacy retirement
Docker/Compose decision service registration
production decision asset YAML invented for testing
production authoritative signal publication during validation
hot graph mutation
runtime asset/lane config mutation API
live model training
consumer groups for market input
market-input PEL replay
persistent InputReadCursor table
signal outbox
durable decision journal
generic supervisor framework
actor/task per lane
generic event bus
workflow/DAG engine
```

Do not add `main.py` merely to invent an HTTP port. The repository currently has no authoritative decision-service port assignment and no approved production decision asset/lane YAML. D9C certifies the ASGI application factory/lifespan/service directly. Process/Compose registration is a later integration step once those facts are explicit.

---

# 4. Selected service architecture

Use one small service owner, conceptually:

```text
DecisionService
  current_generation
  desired_state
  service_state
  generation_number
  stop_event
  transition_lock
  market_task
  lifecycle_task
  rebuild_requested
  latest_poll_result
  latest lifecycle cursor/event evidence
  last_error
  timestamps
```

Do not build an ingestion-style general-purpose supervisor/controller hierarchy.

D9C needs only:

```text
one service object
one market-loop task
one lifecycle-notification task
one asyncio lock for generation/control transitions
```

No task/process per asset or lane.

The D9B `LiveDecisionRuntime` remains the lane owner and live-transaction primitive.

---

# 5. Runtime generation boundary

Introduce one small immutable/runtime-owned generation shape if useful, conceptually:

```text
DecisionRuntimeGeneration
  generation_id
  created_at
  startup: DecisionStartupResult
  live_runtime: LiveDecisionRuntime
```

A generation is constructed fully before it replaces the prior generation.

The generation owns no DB pools or Valkey client; those are process resources owned by the FastAPI lifespan/bootstrap.

A generation rebuild means:

```text
current market polling stops at a bounded poll boundary
        ↓
run D9A again using current durable checkpoint + canonical DB + current manifests
        ↓
construct fresh D9B runtime from STARTUP_READY result
        ↓
install new generation atomically
        ↓
resume market polling
```

No historical trading decision is republished during generation rebuild because D9A replay is publication-suppressed.

Do not mutate D9B lane internals to emulate lifecycle transitions.

---

# 6. Production decision composition

D9C is the first phase that needs one explicit production composition seam.

Add a small module such as:

```text
src/apps/decision_app/composition.py
```

It should construct the explicit approved catalogs/policies needed by D9A/D9B.

Current approved production model surface is intentionally narrow:

```text
PluginCatalog:
  SR_MODEL_SPEC only

RuntimePluginCatalog:
  SRDecisionPlugin only

FeatureCatalog:
  SR_ATR_DEFINITION only

DecisionPolicyCatalog:
  passthrough@1
  priority@1

DataSourceCatalog:
  empty in D9C

DataPolicy:
  explicit empty concepts in D9C
```

Do not auto-discover/import plugins.

Do not register unfinished/refactor-pending models.

When D7B or later adapters are approved, this explicit composition can be extended deliberately.

## 6.1 Feature policy

Build the existing D4 `FeaturePolicy` from `DecisionGlobalSettings.feature_policy`.

If no feature policy is configured:

```text
name/version may use one explicit app-owned empty policy identity
allowed_features = ()
```

Do **not** silently enable every registered feature.

A configured SR lane that requires ATR without operator feature permission must continue to fail closed.

## 6.2 External data

D9C must not invent DataResolver physical sources.

Use the approved empty `DataSourceCatalog` / empty concept policy until a model with reviewed external-data demand is integrated.

---

# 7. D9B runtime settings become actually wired

D9B added strict config ownership:

```text
decision.live_input.batch_size
decision.live_input.block_ms

decision.signal_publication.stream_maxlen
decision.signal_publication.stream_approximate
```

D9C must prove these values are used in production composition rather than repeated defaults.

Generation construction must pass:

```text
LiveDecisionRuntime(
  batch_size=config.global_settings.live_input.batch_size,
  block_ms=config.global_settings.live_input.block_ms,
  ...
)

ValkeySignalPublisher(
  stream_maxlen=config.global_settings.signal_publication.stream_maxlen,
  stream_approximate=config.global_settings.signal_publication.stream_approximate,
  ...
)
```

Add a non-default test fixture proving wiring, e.g. values different from `10/1000/1000/True`.

Do not add new retry/concurrency/worker-count settings in D9C.

For service-loop error pacing, reuse the configured positive `live_input.block_ms` duration. The real service composition may require `block_ms > 0`; D9B unit primitives may continue allowing `0` where already supported for tests.

---

# 8. Process resource ownership

FastAPI lifespan/bootstrap owns exactly:

```text
ConfigManager
DB pools
one Valkey client
AssetManifestStore
CanonicalMarketHistoryRepository
CheckpointRepository
production composition/catalogs
DecisionService
```

Use existing shared connection helpers:

```text
init_db_pools(config_manager)
DBPoolManager.get_reader_pool()
DBPoolManager.get_writer_pool()
create_valkey_client(config_manager)
```

DB ownership:

```text
reader pool
  -> ingestion.candles / canonical PIT history

writer pool
  -> decision.state_checkpoints only
```

Call the already-approved explicit decision checkpoint schema bootstrap against the writer pool before D9A starts.

Do not write into canonical ingestion tables.

Do not add a DB proxy service.

On shutdown, close owned resources in reverse order and always call:

```text
DBPoolManager.close_pools()
ConfigManager.shutdown()
Valkey client aclose()
```

Use existing `bind_logger` conventions. If needed, add exactly one shared enum value:

```text
SystemComponent.DECISION_ENGINE
```

Do not reuse `SIGNAL_APP` or `STRATEGY_ENGINE` as the new service identity.

---

# 9. Lifecycle notification reader

D9C must consume ingestion lifecycle changes, but manifests remain the authority.

Use:

```text
asset:lifecycle
```

and shared:

```text
AssetLifecycleEvent
AssetManifestStore
```

## 9.1 Direct cursor only

Use direct `XREAD`; no consumer group / PEL is required for decision lifecycle notifications.

Reason:

```text
lifecycle stream = change notification
asset/timeframe manifests = authoritative current state
```

A restart can always recapture the current lifecycle tail and then read current manifests.

Do not reuse old signal/strategy consumer-group runner machinery.

## 9.2 Initial race-free attachment

Initial application construction must use this order:

```text
create Valkey client
capture current asset:lifecycle tail ID once
then run D9A startup / manifest reads
then start lifecycle XREAD strictly after captured lifecycle ID
```

If lifecycle stream does not exist at capture:

```text
cursor = 0-0
```

never `$`.

This handles an event created during D9A startup: the manifest read sees current state and the later direct read can replay the notification idempotently.

## 9.3 Notification semantics

For a valid event:

```text
source/requested_by must be compatible with ingestion authority
symbol is the manifest asset code (e.g. BTC)
```

Only events for configured decision `manifest_asset` values require action.

Unconfigured asset events are ignored after advancing the lifecycle notification cursor.

Do not derive or create decision assets from lifecycle events.

Do not trust the event payload as final state. The event only requests a reconciliation; D9A rebuild reads current asset/timeframe manifests again.

## 9.4 Malformed lifecycle event

Lifecycle differs from market input: the lifecycle event is non-authoritative notification metadata.

If one lifecycle record is undecodable/malformed:

```text
record bounded degraded evidence
advance lifecycle notification cursor past that message
request a full current-manifest reconciliation/rebuild
```

Do not let one bad notification permanently wedge the lifecycle reader.

Do not apply this rule to canonical market streams; D9B market fail-closed semantics remain unchanged.

---

# 10. Lifecycle transition behavior

The decision graph remains static and restart-owned.

Lifecycle events never add/remove model bindings or timeframes.

For a configured manifest asset:

```text
LIVE / RESUMED
PAUSED
STOPPED
REMOVING
```

all trigger **current-manifest generation reconciliation**, not hot lane mutation.

D9A already owns authoritative manifest gating, including required D3/D4 timeframes.

Therefore the generation after rebuild naturally contains:

```text
manifest LIVE + all required TFs LIVE
  -> STARTUP_READY lane runtimes

manifest PAUSED/STOPPED/REMOVING or required TF not LIVE
  -> lane INACTIVE / not scheduled
```

This is the selected D9C lifecycle implementation.

No new runtime state machine per asset.

## 10.1 Transaction boundary

Do not cancel a D9B transaction in the middle because a lifecycle event arrives.

Lifecycle change becomes effective at the next bounded poll boundary:

```text
current D9B poll/transaction finishes
        ↓
service sees lifecycle rebuild request
        ↓
no next market poll starts
        ↓
D9A/D9B generation rebuild
```

If the current transaction committed before the lifecycle event was applied, it remains committed.

This is analogous to the already-approved valid-prefix failure ordering: completed external/state side effects are not rolled back by later control evidence.

---

# 11. DecisionService states

Use a small service state vocabulary only; do not build a generic state framework.

Recommended:

```text
STARTING
RUNNING
PAUSED
REBUILDING
DEGRADED
ERROR
STOPPING
STOPPED
```

Desired operator state only needs:

```text
RUNNING
PAUSED
```

Meanings:

```text
STARTING
  resources/generation not yet installed

RUNNING
  market loop active

PAUSED
  operator pause; no market poll; lifecycle watcher still alive

REBUILDING
  D9A/D9B generation replacement in progress; old generation not polled

DEGRADED
  generation/loop exists, but one or more lanes/transport conditions require attention

ERROR
  no safe generation/continuation available

STOPPING / STOPPED
  shutdown states
```

Do not overload D1 lane-state vocabulary for process lifecycle.

---

# 12. Market loop

The market loop owns only orchestration around existing D9B:

```text
while not stop:
    if desired PAUSED:
        wait/yield; do not market poll
        continue

    if rebuild requested:
        rebuild before next poll
        continue

    result = await current_generation.live_runtime.poll_once()
    cache bounded result
    classify service-level continuation/rebuild conditions
```

Do not duplicate D9B input parsing, scheduling, policy, publication, or checkpoint logic.

## 12.1 Transport interruption

If `poll_once()` raises a pure input/Valkey transport error:

```text
record DEGRADED + last_error
wait one configured live_input.block_ms interval
retry from the same in-memory InputReadCursor
```

Do not roll back cursors or lane watermarks.

Valkey client/library may reconnect underneath the existing client.

If the resumed market stream is no longer causally continuous, D9B's canonical gap checks will surface `RECONSTRUCTION_REQUIRED`.

Do not build a socket-retry framework.

## 12.2 Automatic rebuild classification

One automatic generation rebuild is appropriate for causal reconstruction conditions such as:

```text
InputRecordResult.RECONSTRUCTION_REQUIRED
lane status RECONSTRUCTION_REQUIRED from pending-trigger overrun / causal gap
```

Do not auto-loop indefinitely.

After one rebuild attempt:

```text
success -> install generation, RUNNING
failure -> DEGRADED/ERROR, no unsafe polling of old generation
```

Do **not** automatically rebuild forever on:

```text
canonical CONFLICT
market MALFORMED
policy/model INVALID
publication conflict/failure HALTED
checkpoint durability HALTED
```

Those are operator-visible faults. Manual reconnect/rebuild remains available.

Unrelated lanes may have continued up to the bounded rebuild boundary; no state rollback.

---

# 13. Global pause / resume

Add service controls:

```text
pause()
resume()
reconnect()
```

Protect control/generation transitions with one `asyncio.Lock`.

## 13.1 pause()

`pause()` must wait for any current bounded market transaction to finish before returning.

After it returns:

```text
desired_state = PAUSED
service_state = PAUSED
no new D9B market poll begins
lifecycle watcher remains alive
```

It is acceptable that input is not consumed while globally paused; resume performs full D9A reconstruction from durable canonical history/checkpoints, so stale state continuation is impossible.

Do not add an input-only pause mode in D9C.

## 13.2 resume()

Never resume the old generation directly after a pause interval.

Resume must:

```text
re-read current config/manifests
run D9A reconstruction
construct fresh D9B generation
install it
set desired RUNNING
```

Historical decisions remain suppressed during replay.

## 13.3 reconnect()

`reconnect()` is a **safe runtime generation rebuild**, not a low-level socket hack.

It must:

```text
finish current bounded transaction
suspend old generation polling
run fresh D9A startup/reconstruction
construct fresh D9B runtime
install on success
```

If rebuild fails, do not resume unsafe old generation automatically.

---

# 14. Graceful shutdown

Shutdown must favor transaction completion over cancellation.

Lifespan shutdown:

1. set service desired stop / stop event;
2. stop starting new market polls;
3. allow the current bounded D9B poll/transaction to finish;
4. stop/cancel the lifecycle notification wait task;
5. await service market task completion;
6. close Valkey;
7. close DB pools;
8. shut down ConfigManager.

Do not immediately cancel a possible in-flight signal publication/finalization just because lifespan shutdown began.

If cancellation is unavoidable due outer ASGI process cancellation, preserve existing D9B `CancelledError` behavior and rely on D9A restart reconstruction / exact signal IDs. Do not hide cancellation as a normal FAILED acknowledgement.

Add a deterministic test with a gated fake market poll proving `stop()` waits for the current bounded transaction and prevents the next poll.

---

# 15. Bounded service observability

Do not add a large metrics framework in D9C.

Add one immutable/cached service snapshot, conceptually:

```text
DecisionServiceSnapshot
  service_state
  desired_state
  generation_id
  started_at
  last_poll_at
  last_rebuild_at
  last_lifecycle_event_at
  last_error
  configured_asset_count
  configured_lane_count
  active_lane_count
  lane_status_counts
  blocked_stream_count
  lifecycle_cursor
```

Detailed bounded views may expose:

```text
lane_id
lane status/reason
pending trigger cutoff
LaneCommitWatermark
last transaction-local policy/publication/finalization/checkpoint evidence

input stream
InputReadCursor
blocked reason
```

Do not expose:

```text
full model state
full checkpoints
bar histories
model artifacts
DB/Valkey clients
raw config secrets
unbounded event history
```

Log service transitions and rebuild reasons through bound structured logging.

FastAPI instrumentation may follow existing ingestion app pattern with health endpoints excluded from tracing noise.

---

# 16. FastAPI control plane

Add a small testable API structure, e.g.:

```text
src/apps/decision_app/api/__init__.py
src/apps/decision_app/api/app.py
src/apps/decision_app/api/dependencies.py
src/apps/decision_app/api/routes.py
```

and an application bootstrap/lifespan module such as:

```text
src/apps/decision_app/bootstrap.py
```

## 16.1 Routes

Implement only:

```text
GET  /health/live
GET  /health/ready
GET  /runtime
GET  /runtime/lanes
GET  /runtime/inputs
POST /runtime/pause
POST /runtime/resume
POST /runtime/reconnect
```

No asset/model config mutation routes.

No order/risk controls.

## 16.2 Liveness

`/health/live` returns 200 whenever the ASGI process/control plane is serving.

No DB/Valkey/model I/O in the handler.

## 16.3 Readiness

Use the cached service snapshot only.

Suggested app-level readiness:

```text
RUNNING or DEGRADED with an installed generation
    -> HTTP 200
       status = ready or degraded

STARTING / REBUILDING / PAUSED / ERROR / STOPPING / STOPPED
or no generation
    -> HTTP 503
```

A partial lane failure must not force a restart of unrelated healthy lanes merely because readiness is queried. Return bounded lane counts/reasons so operators can distinguish partial degradation.

## 16.4 Controls

`pause/resume/reconnect` call service methods and return the resulting cached snapshot.

Use 409 only for genuine conflicting transitions (e.g. concurrent rebuild already active) if necessary.

Do not expose arbitrary state-setting endpoints.

---

# 17. FastAPI application factory / lifespan

Create a testable app factory similar in spirit to ingestion but smaller:

```text
create_app(...)
create_application(...)
```

`create_application()` performs no I/O until lifespan begins.

Lifespan startup sequence:

```text
ConfigManager
  ↓
load_decision_config
  ↓
init_db_pools
  ↓
ensure decision checkpoint schema on writer pool
  ↓
create Valkey client
  ↓
AssetManifestStore
  ↓
capture lifecycle stream tail
  ↓
build production composition
  ↓
D9A startup
  ↓
D9B generation
  ↓
DecisionService start
  ↓
attach app.state.decision_service / config manager / bounded dependencies
```

No signal publication may occur during lifespan startup; D9A is replay-suppressed and D9B market loop starts only after generation installation.

---

# 18. No invented production decision asset config

Current repository has:

```text
configs/decision/global.yaml
```

but no approved:

```text
configs/decision/assets/*.yaml
```

Do not fabricate BTC/SR/Momentum production lane config merely to make `create_application()` runnable from the current checkout.

Do not weaken `DecisionConfig`'s non-empty asset invariant in D9C unless a separately demonstrated architecture requirement demands it and is reported back as a blocker instead of guessed around.

D9C tests must inject deterministic test `DecisionConfig` objects / temp config fixtures exactly as D9A/D9B do.

Production lifespan validation from the current checkout may therefore record:

```text
PRODUCTION_DECISION_CONFIG_NOT_YET_AVAILABLE
```

This is not permission to invent a lane.

No `main.py` / Compose registration until an explicit service port and approved production decision asset config exist.

---

# 19. Lifecycle notification / generation rebuild tests

Add focused D9C tests proving at minimum:

```text
lifecycle tail captured before initial D9A manifest reconciliation
missing lifecycle stream uses 0-0
lifecycle event after captured tail triggers one generation rebuild
unconfigured asset lifecycle event is ignored without graph mutation
valid configured PAUSED event -> current poll completes -> rebuild -> lane inactive
valid configured RESUMED/LIVE event -> rebuild -> lane reconstructed before next live poll
multiple lifecycle events in one bounded batch coalesce to one current-manifest rebuild
stale event payload cannot override newer manifest state
malformed lifecycle notification advances notification cursor + requests manifest rebuild
no lifecycle consumer group / PEL
```

Use fake/in-memory manifests and transport in unit tests.

No ingestion production imports are required beyond shared `libs.common.asset_manifest` contracts.

---

# 20. Market loop / reconnect tests

Prove:

```text
D9B poll_once is the only market transaction primitive
transport error leaves InputReadCursor/LaneCommitWatermark unchanged
transport error retry uses same runtime/cursor after configured pacing
a resumed forward-contiguous stream continues normally
D9B RECONSTRUCTION_REQUIRED requests one generation rebuild
successful rebuild installs a new generation ID
failed rebuild leaves old generation unpolled
canonical CONFLICT does not enter an automatic rebuild loop
MALFORMED does not enter an automatic rebuild loop
HALTED publication/checkpoint lane does not enter an automatic rebuild loop
manual reconnect performs fresh D9A reconstruction
```

No PEL.

No historical signal replay.

---

# 21. Pause/resume tests

Prove:

```text
pause waits for current bounded transaction
pause returns only after no next poll can start
while PAUSED, market poll count does not increase
lifecycle watcher remains active while PAUSED
resume always builds a fresh generation
bars arriving during PAUSED are reconstructed by D9A, not emitted as stale live decisions
resume does not reuse stale D6 committed state directly
```

Use deterministic fakes/gates; do not depend on wall-clock sleeps where an event/gate can prove order.

---

# 22. Graceful shutdown tests

Prove:

```text
stop request during blocking/active market transaction does not cancel committed prefix work
current poll completes
no second poll starts
lifecycle watcher exits
service state -> STOPPED
resources are closed once by lifespan
```

Test application lifespan failure cleanup too:

```text
D9A startup raises
-> service task never starts
-> Valkey closes
-> DB pools close
-> ConfigManager shuts down
```

Do not leak tasks.

---

# 23. Control-plane tests

Use FastAPI ASGI/TestClient/AsyncClient patterns already in the repository.

Prove:

```text
/health/live -> 200 without performing runtime I/O
/health/ready -> 503 before generation / during PAUSED / ERROR
/health/ready -> 200 RUNNING
/health/ready -> 200 degraded with bounded degradation evidence
/runtime -> cached service snapshot
/runtime/lanes -> bounded lane status/watermarks
/runtime/inputs -> bounded cursors/blocked reasons
/runtime/pause -> service paused
/runtime/resume -> generation rebuilt
/runtime/reconnect -> generation rebuilt
missing service dependency -> 503
```

No secrets/state payload leakage.

---

# 24. Real SR service integration proof

Reuse the approved real SR adapter in **test-only** deterministic decision config.

Prove through the actual D9C service owner (not direct D9B only):

```text
D9A initial startup
service RUNNING
new live SR candle
D9B NO_SIGNAL
D8 state commit/watermark
checkpoint UPDATED
service snapshot records transaction
pause
more canonical history appears while paused
resume
D9A rebuild replays publication-suppressed
service RUNNING with exact reconstructed SR state
next live SR candle advances normally
```

No signal stream publication from SR.

Do not change SR mathematics/config semantics.

---

# 25. Synthetic signal service proof

Use the existing test-only decision-capable plugin fixture to prove service composition wires:

```text
D9C service
  -> D9B SIGNAL
  -> isolated ValkeySignalPublisher
  -> PUBLISHED
  -> D8 COMMITTED
```

Then force:

```text
publication CONFLICT / FAILED
```

and prove:

```text
service remains alive
lane is degraded/halted as D9B reports
unrelated service control plane remains responsive
no automatic rebuild loop
```

Never point this at a production/shared `signals:*` stream while legacy strategy publication still exists.

---

# 26. Config wiring tests

Use strict non-default settings in tests to prove:

```text
live_input.batch_size -> DirectCursorInput
live_input.block_ms -> DirectCursorInput + service transport-error pacing
signal_publication.stream_maxlen -> ValkeySignalPublisher
signal_publication.stream_approximate -> ValkeySignalPublisher
feature_policy -> D4 FeaturePolicy
```

Do not introspect private state if a small explicit property/factory evidence is cleaner.

Do not add config knobs merely for testability.

---

# 27. Import / scope boundaries

D9C decision production code may import:

```text
libs.common.*
libs.contracts.*
libs.models.sr approved adapter
FastAPI/Starlette
```

It must not import production runtime code from:

```text
apps.ingestion_app
apps.signal_app
apps.strategy_app
apps.risk_app
apps.execution_app
```

Ingestion market identity/config remains consumed through the already-approved decision-owned config/history boundaries.

Tests may import ingestion event builders when useful for parity fixtures.

---

# 28. Local infrastructure certification

D9C is a service phase and should use real local Timescale/Valkey only if the repository-provided environment is genuinely available.

Current worktree has repeatedly lacked `.env`.

Do not:

```text
copy/create credentials
borrow external/shared production broker state
start unrelated services merely to force a pass
publish to production signals:*
```

If still unavailable, record:

```text
LOCAL_INFRASTRUCTURE_VALIDATION_BLOCKED_ENVIRONMENT
```

and rely on deterministic service/lifespan transport fakes plus the already-approved D9A/D9B functional gates.

If an isolated local harness becomes available, prove:

```text
lifespan DB/Valkey resource ownership
D9A startup
one live market poll
one test-only no-signal or isolated signal transaction
lifecycle notification -> generation rebuild
manual pause/resume
clean shutdown
```

No external market provider/network calls.

---

# 29. Validation matrix

Run focused D9C first.

Suggested files:

```text
tests/decision/test_d9c_composition.py
tests/decision/test_d9c_lifecycle.py
tests/decision/test_d9c_service.py
tests/decision/test_d9c_api.py
tests/decision/test_d9c_bootstrap.py
```

Names may differ if a smaller grouping is clearer.

Then cumulative:

```text
complete tests/decision
D9A startup/reconstruction focused surface
D9B live input/transport/runtime focused surface
D8 policy/publication/finalization focused surface
D7A real SR adapter/runtime
relevant non-research SR core/config/lifecycle/replay/serialization
commons ConfigManager/connections boundary tests
canonical ingestion outbox/HTF/provenance contract slice
risk/signal wire compatibility tests
```

Attempt broader ingestion tests only as already documented; exclude only genuinely environment/Compose-blocked FINAL harness gates.

Static:

```text
Ruff check
Ruff format --check
compileall decision/SR touched scope
git diff --check
trailing whitespace scan
AST production import boundary
forbidden market XREADGROUP/XACK/XAUTOCLAIM/PEL scan
forbidden PriceRelay/price_update scan
forbidden legacy signal/strategy runtime import scan
FastAPI route inventory check
repo-local __pycache__ cleanup
```

---

# 30. Pass 1 coder self-review — correctness

Explicitly verify:

```text
D9A/D9B semantics untouched
D9B runtime settings come from decision config
lifecycle tail captured before initial manifest reconciliation
lifecycle uses direct cursor; manifests remain authority
current bounded transaction finishes before lifecycle rebuild
no stale generation is polled after rebuild request begins
PAUSED starts no new market poll
resume always rewarms through D9A
transport interruption never rolls back input/lane progress
auto rebuild only for explicit reconstruction-required conditions
conflict/malformed/halted/invalid do not rebuild-loop
manual reconnect replaces generation safely
shutdown does not intentionally cancel in-flight signal finalization
resource cleanup is once-only
health routes are cached/no-I/O
partial lane failure does not kill unrelated lane processing/control plane
no historical signal replay
```

---

# 31. Pass 2 coder self-review — simplicity/scope

Verify:

```text
one service object, not a framework
one market task + one lifecycle task only
one transition lock
no task per lane/asset
no consumer group/PEL for decision market input
no lifecycle consumer group needed
no persistent cursor table
no signal outbox
no PriceRelay
no D7B implementation
no production model/asset config invention
no HTTP port invention
no main.py/Compose registration
no risk/execution behavior moved upstream
no hot graph mutation
no generic metrics/event framework
```

---

# 32. Residual risk / carry-forward

D9C does **not** close:

```text
production decision asset/lane configuration
assigned HTTP service port/process registration
Docker/Compose decision service
PriceRelay / downstream risk price-gap contract
real local infrastructure soak
D7B real decision-capable plugin integration
D10 resource certification
D11 shadow parity
D12 cutover
D13 legacy retirement
```

The D9C result must be described as the **certified ASGI service/lifecycle shell around D9A+D9B**, not production cutover readiness.

---

# 33. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d9c-service-lifecycle-control-v1.md
```

Record:

```text
files/symbols changed
production composition catalog inventory
D9B config wiring evidence
service/generation state contracts
lifecycle tail capture/direct cursor semantics
manifest-authority reconciliation evidence
lifecycle pause/stop/resume behavior
generation rebuild ordering
market transport interruption behavior
automatic rebuild classification
manual pause/resume/reconnect evidence
graceful shutdown ordering
resource ownership/cleanup evidence
FastAPI route inventory
health/readiness semantics
bounded runtime/lanes/inputs evidence
real SR service flow
synthetic isolated signal service flow
focused/cumulative compatibility counts
local infrastructure status
Ruff/format/compile/diff/import/forbidden/cache evidence
Pass 1 findings
Pass 2 findings
residual risks
D9D/PriceRelay and D10 carry-forward
```

Do not claim:

```text
production decision configuration available
production service port assigned
Docker service runnable
PriceRelay complete
shadow parity complete
resource certification complete
production cutover safe
```

Do not start D9D automatically.

Final line exactly:

```text
DECISION_APP_D9C_SERVICE_LIFECYCLE_CONTROL_READY_FOR_REVIEW
```
