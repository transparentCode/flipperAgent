# D0 design decisions

This record preserves the original D0 design rationale and records the
implemented DA-2 amendments. Historical D0 decisions below are not a claim that
retired resolver or relay behavior remains active.

## Selected decisions

### One application, in-process plugins

`decision_app` is one runtime process with an explicit plugin catalog. Models are
in-process plugins with a small semantic interface; they are not independent
services and do not own infrastructure clients. This keeps shared bar history,
features, data snapshots, and dependency artifacts bounded on the 8 GiB / 4-core
target.

### Ingestion remains canonical

`ingestion` owns canonical OHLCV and ordinary HTF materialization. The decision
runtime consumes those lanes and does not create a second market-data authority or
re-aggregate locally in the hot path.

### Shared causal BarStore

The runtime keeps bounded shared bar views keyed by market series (asset, venue, instrument, timeframe) and cutoff, shared across lanes rather than keyed by lane.
Models receive causal views rather than copied full histories. A lane is ready only
when required timeframes reach the required cutoff; arrival order is not a
readiness rule.

### Explicit input-progress startup

Startup captures stream tails and DB cutoffs before warmup. Warmup and stateful
reconstruction run with publication suppressed. Live reads begin after the
captured stream IDs. This prevents a live event from racing ahead of the history
used to reconstruct state.

### Bounded lifecycle ownership

The approved runtime implementation uses one absolute 120-second deadline for
initial resource construction and first-generation installation, explicit 5-second
Valkey/acquisition budgets, one remaining 15-second SQL/transaction budget for
canonical history and checkpoint/effect repositories, and a 30-second control
admission/drain bound. Cleanup is one lazy aggregate 5-second budget shared
across nested owners rather than a fresh allowance per await. These numeric
defaults are sourced from `configs/decision/global.yaml`; this record is not a
configuration authority.

Startup failure shares that budget across candidate, partial-pool, schema/lease,
and final teardown cleanup, with a startup-expiry cap. Successful startup creates
a fresh lazy final-shutdown budget. Only owned resources may be closed; an
unconfirmed release retains ownership and fences reuse. `STOPPED` means owned
service tasks are quiescent; a clean lifespan additionally requires confirmed
owned-resource teardown, so cleanup failure may leave the service `STOPPED` while
application shutdown is unclean. This is an operational implementation boundary,
not a new actor, workflow, or resource-management framework.

### Independent progress markers (D0; price-relay portion superseded by DA-2)

V1 does not let a model binding own input-consumer progress. `InputReadCursor`
records how far the canonical stream reader has observed and accepted data into
the shared `BarStore`; it continues even when a lane is degraded. Each
`DecisionLane` has its own `LaneCommitWatermark`, advanced only after a committed
publication, no-signal, or explicit skip disposition and proposed-state commit. A
failed lane leaves its own state and watermark unchanged, but does not roll back
the input cursor or block unrelated lanes. The originally designed independent
`PriceRelayProgress` path was retired by DA-2; Decision no longer owns a price
relay or progress cursor.

### Reconstruct and resume, not stale-decision replay

Temporary broker recovery uses the in-memory `InputReadCursor` when the stream
is continuous.
Detectable retention gaps and process restarts reconstruct causal state from
Timescale, establish new input and lane progress positions, and resume input
reading. V1 does not replay stale trading decisions from a persistent PEL.

### Isolate startup failure by lane and recover at generation scope

DA-1 installs the ready lanes of a partially blocked startup generation. A
series capture/history failure, manifest-read failure, or lane reconstruction
failure blocks only dependent work; first-generation static planning/configuration
and application resource-construction failures remain fatal. Faults that make a
lane or input path unsafe schedule a bounded generation retry rather than
continuing that failed path. Automatic retry uses exponential backoff from 5 to
300 seconds while the installed generation continues polling healthy lanes.
Manual/lifecycle operations and a proven forward canonical input gap retain
immediate rebuild behavior, with lifecycle authority taking precedence.

This uses the existing generation factory and startup reconstruction path. It
does not add lane workers or a second per-lane reconstruction algorithm.

Poisoning is the exception to retry. When a storage repository is poisoned
(unconfirmed cleanup after a lease timeout) the factory raises `GenerationFenced`
and the fence cannot be lifted in-process, so the service enters a terminal
`ERROR`: no generation, no retry, later rebuild requests are rejected, and
readiness reports `dependency_poisoned` (`fenced_reason` in `/runtime`). Recovery
is a process restart. User-approved 2026-10-06 ("Visible, stop retrying").

DA-3 amendment (user-approved 2026-10-06). Lane-local faults quarantine only
that lane and do not rebuild the generation. These are model preparation,
policy evaluation or a BLOCKED/INVALID policy verdict, stale finalization, and
pre-publication failures (missing publisher, envelope build, preflight,
`finalize_no_signal`). The lane takes the status `QUARANTINED`. Each cutoff it
then misses is recorded as a single-cutoff `lane_fault` skip row, advances lane
effect progress and the finalizer watermark (disposition `skipped`), and the lane
is not evaluated again. A stateless quarantined lane rejoins on the next
generation build, whatever requests it; a stateful lane also requests
`AUTOMATIC_RECOVERY` so its state is re-warmed. Shared faults (overtaken pending
cutoff, fatal context, market-view failure, series failure, input dispositions),
publish-uncertain faults (the publisher was called) and post-commit durability
faults keep generation recovery. The service is `DEGRADED` while any lane is
quarantined. Rejoin skips forward: a failed cutoff is never re-evaluated. If
`lane_fault` accounting itself fails, the lane is HALTED for generation recovery.
Automatic per-lane retry is deferred (DA-3b).

### Readiness measures live-lane availability

The service remains ready while its existing generation/service-state contract
holds and at least one configured lane is live. If all configured lanes remain
non-live for more than 300 seconds while desired state is `RUNNING`, readiness
returns 503 (`no_lane_live`). An absent generation reports `no_generation`.
Paused operation and zero-lane configurations are not subject to this
no-live-lane timeout. Liveness is independent; this threshold is not a causal
market-data or trading-progress SLO.

### Stateful models use proposed state (D0; extended by DA-2)

`evaluate()` sees a state snapshot and returns a proposed next state. The runtime
commits it only after policy and successful idempotent publication, or a final
no-signal result, and then advances the affected `LaneCommitWatermark`. A
publication failure or conflict leaves committed state and that lane's
`LaneCommitWatermark` unchanged without rolling back `InputReadCursor` or
`BarStore`. A missed stateful trigger
caused by a causal gap, missing required data, dependency failure, or model
exception invalidates/degrades the binding. It cannot continue from stale state;
it must causally re-warm before returning `LIVE`.

Causal re-warm is not an arbitrary history warmup. It replays the same execution
chain as live operation, with publication suppressed: causal bar views, shared
features, upstream dependencies in topological order, then the stateful binding.
DA-2 removed external-data execution and rejects non-empty intrinsic data
requirements.

### Explicit time semantics (D0; current serialized units clarified by DA-1)

The contracts distinguish bar open/close, `market_as_of`, `signal_time`,
`decision_ready_at`, and external `event_time`/`available_at`/`fetched_at`. The
market identity is causal market time; runtime completion time is operational
metadata. The active signal adapter writes `TradeSignal.timestamp` in seconds and
uses milliseconds only for the explicit stream entry ID; Risk's signal-staleness
comparison is also in seconds. Risk converts a `PriceUpdate` bar-open timestamp
from milliseconds to seconds. Decision does not publish `PriceUpdate`.

### Semantic external data resolution (D0 proposal; removed by DA-2)

The original D0 proposal had models request semantic concepts and a
`DataResolver` choose cache, PIT storage, or a bounded live scraper request
according to `DataPolicy`, mode, and provenance.
Models declare required/optional status, freshness/alignment, and whether replay
support is required; they do not declare physical source allow-lists or resolver
capabilities. Replay never calls live acquisition. One bounded request phase runs
before model evaluation and equivalent requests are single-flight. Resolved
capability is runtime output (`LIVE_AND_REPLAY`, `LIVE_ONLY`, or `UNAVAILABLE`),
not an intrinsic model claim. DA-2 removed that runtime, its source catalog, and
its policy; the shared contract types remain inactive and the planner rejects
non-empty intrinsic data requirements.

PIT acceptance requires the represented observation/window end and `event_time` to
be no later than `market_as_of`; a cache's latest result is rejected when it is
future-dated. Replay additionally requires historical `available_at` to be no
later than the simulated resolver knowledge cutoff. `fetched_at` never proves
historical availability.

### Static, same-lane dependencies

Dependencies are named slots resolved to concrete bindings at startup. They are
acyclic and same-lane only in V1. Upstream artifacts are computed once per
binding/as-of and reused. This is enough for a Boundary → Regression composition
without introducing a general workflow engine.

### Shared feature policy

Shared features run once only when a model requires them and operator policy allows
them. Model-private deterministic transforms stay inside the plugin. Disabled
required features make a binding unavailable; they are not silently approximated.

### Independent PriceRelay (D0 choice; retired by DA-2)

The D0 design specified that price updates would not be a side effect of
successful model evaluation. PriceRelay would have its own configured cadence and
would remain available to risk monitoring during model warmup, external-data
failure, policy suppression, or model failure.

PriceRelay records independent `PriceRelayProgress` and cannot silently claim
continuity after a detected input gap. Current risk uses `PriceUpdate.high`/`low`
for SL/TP monitoring, so D0 deliberately does not choose replay/catch-up versus
discard semantics for missed prices. A dedicated downstream risk compatibility
proof must establish those semantics before cutover. DA-2 retired this component
before activation: Decision publishes no `price_update:*`; downstream Risk price
continuity remains a separately coordinated feed contract.

### One authoritative publisher

Only one lane may publish a given `(asset, decision timeframe)` signal stream.
Within that lane, policy emits zero or one result per `market_as_of`. Deterministic
identities include canonical binding parameters/runtime and the effective lane and
policy revision. A same-payload retry is idempotent and a same-identity/different-
payload retry a fail-closed conflict.

An isolated Valkey proof confirmed ordered explicit timestamp IDs, raw duplicate
XADD rejection, older-ID rejection, and adapter lookup classification of identical
retry success versus different-payload conflict.

### Stable risk identity

A passthrough binding uses a stable configured risk key. A composed lane uses an
explicit `risk_profile_key`; contributor models remain metadata. This preserves
the downstream risk-selection boundary and avoids deriving risk configuration from
an arbitrary ensemble contributor.

## DA-2 implemented amendments

These amendments describe the active runtime and supersede conflicting D0
proposals above without erasing their design history.

### Restart skip-forward and durable effect accounting

Startup validates each lane's required history at the latest retained trigger
cutoff `R`, probes one exact first-unaccounted stream ID, and does not replay
stateless publication effects across downtime. A matching current-identity entry
reconciles as already effected; a foreign entry is recorded as `foreign_entry`.
Stateless missed cutoffs form one `restart` skip range, with only `R` eligible for
live evaluation. Stateful bindings rewarm every required transition through `R`
with publication suppressed, then record `restart_rewarm`. The append-only
`decision.lane_effect_skips` table records ranges; latest effect progress uses
NULL disposition when no publication effect occurred. A stale cutoff is also
committed as `skipped`, with proposed state/checkpoint advanced and no publication.
If progress was not saved after that skip row, startup reconciles the existing
single-cutoff `stale` or `foreign_entry` row at the first unaccounted cutoff by
advancing progress, rather than recording the cutoff again as `restart`.

### Freshness and identity

Authoritative SIGNAL results and all shadow observations are publishable only
when `decision_ready_at - market_as_of <= signal_freshness_seconds`; the active
default is 300 seconds, and exactly 300 seconds is fresh. Stale work advances
state and lane watermark as a skip, not as a signal or shadow effect.

DA-2's one identity change adds the feature-plan fingerprint to
`LaneExecutionIdentity` and includes it in `decision_execution_revision`, along
with lane identity, base lane revision, and policy. `decision_id` derives from
that execution revision and `market_as_of`. The physical
`data_plan_fingerprint` columns remain but are written as the constant `none` and
are excluded from identity.

### External data and price-relay retirement

Decision has no active `DataResolver`, source catalog, or external-data
acquisition phase. Shared external-data contracts remain inactive, and the
planner rejects non-empty intrinsic data requirements. Decision no longer owns
PriceRelay or publishes `price_update:*`; downstream Risk price continuity needs
a separately approved feed change.

### Per-lane momentum history

Momentum feature history follows each route's locked RSI/MACD history rather than
the maximum across all routes: BTC 1h is 136 bars, BTC 4h is 272 bars, and ETH 4h
is 544 bars. Feature values on each route's own window remain unchanged.

## Alternatives deliberately rejected or deferred

### Separate signal and strategy services

Rejected for V1. Splitting model evaluation across services would duplicate causal
history, add transport ordering, and make state/replay boundaries harder to prove.
The downstream strategy/risk boundary remains an integration concern, but the new
decision runtime is one application.

### Model-per-process isolation

Deferred. It adds memory, lifecycle, and IPC overhead that is not justified by the
current 8 GiB / 4-core envelope. Process/GPU isolation remains a future extension
for evidence-backed heavy models.

### PEL replay as the restart protocol

Rejected for V1. A PEL does not by itself provide a complete causal reconstruction
or safe suppression of stale trading decisions. Input-progress and cutoff-based
reconstruction from durable history is the selected restart boundary.

### Universal feature store or always-on feature vector

Rejected. It would compute and retain features that no active binding needs and
would obscure model-private transforms. FeaturePlan is demand- and operator-policy
driven.

### Direct model DB/Valkey/HTTP I/O

Rejected. It prevents deterministic evaluation, complicates replay, and hides
availability timing. DA-2 has no active physical external-data acquisition
boundary.

### General DAG/workflow framework

Rejected. V1 needs only a small static topological planner for acyclic, same-lane
named dependencies. Cross-lane and cross-asset graphs are future contracts.

### Generic model checkpoints

Deferred. Stateful V1 models must be reconstructable from durable PIT-safe inputs.
Checkpoints may be added only for a measured reconstruction problem with explicit
versioning and causal validation.

### Live training or optimization

Rejected. Training and optimization remain offline workflows. Runtime evaluation
must be deterministic with immutable configured model parameters.

### Broad import-time auto-discovery

Rejected. An explicit plugin catalog is auditable, has bounded startup behavior,
and avoids import-time side effects from arbitrary modules.

### Local HTF re-aggregation

Rejected in the hot path. Canonical ingestion HTFs provide one source of alignment
and chronology. A later research-only calculation can be separate if it has an
explicit non-authoritative identity.

### Competing authoritative lanes

Rejected. Multiple publishers for one `(asset, decision timeframe)` would create
ambiguous risk input and duplicate/conflicting decisions. Shadow lanes cannot
publish authoritative signals.

## Future extension points, not V1 commitments

These are legitimate extensions only after a separate contract and evidence:

- durable decision journal/outbox;
- versioned state checkpoints;
- incremental feature engines;
- cross-lane dependencies;
- cross-asset model artifacts;
- GPU or process-isolated execution;
- asset sharding and active/standby runtime;
- direct risk ingestion of an independent price feed.

None is created, implied, or required by D0.
