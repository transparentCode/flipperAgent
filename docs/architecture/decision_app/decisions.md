# D0 design decisions

This record freezes the intentionally small V1 boundary for `decision_app` and
records alternatives that are deferred rather than accidentally left open.

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

The runtime keeps bounded shared bar views keyed by lane/timeframe and cutoff.
Models receive causal views rather than copied full histories. A lane is ready only
when required timeframes reach the required cutoff; arrival order is not a
readiness rule.

### Explicit input-progress startup

Startup captures stream tails and DB cutoffs before warmup. Warmup and stateful
reconstruction run with publication suppressed. Live reads begin after the
captured stream IDs. This prevents a live event from racing ahead of the history
used to reconstruct state.

### Independent progress markers

V1 does not let a model binding own input-consumer progress. `InputReadCursor`
records how far the canonical stream reader has observed and accepted data into
the shared `BarStore`; it continues even when a lane is degraded. Each
`DecisionLane` has its own `LaneCommitWatermark`, advanced only after successful
signal publication or final no-signal disposition and the proposed-state commit.
`PriceRelayProgress` is independent of both. A failed lane leaves its own state
and its `LaneCommitWatermark` unchanged, but does not roll back the input cursor
or block PriceRelay or unrelated lanes.

### Reconstruct and resume, not stale-decision replay

Temporary broker recovery uses the in-memory `InputReadCursor` when the stream
is continuous.
Detectable retention gaps and process restarts reconstruct causal state from
Timescale, establish new input and lane progress positions, and resume input
reading. V1 does not replay stale trading decisions from a persistent PEL.

### Stateful models use proposed state

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
features, replay-safe external data, upstream dependencies in topological order,
then the stateful binding. V1 stateful bindings may consume only durable
`LIVE_AND_REPLAY` external inputs; a `LIVE_ONLY` input cannot be essential to
state reconstruction.

### Explicit time semantics

The new contracts distinguish bar open/close, `market_as_of`, `signal_time`,
`decision_ready_at`, and external `event_time`/`available_at`/`fetched_at`. The
market identity is causal market time; runtime completion time is operational
metadata. The current repository has a seconds/milliseconds mismatch between
signal feature output and risk staleness, so a later downstream adapter and
contract-test migration is required before this output boundary is activated.

### Semantic external data resolution

Models request semantic concepts. `DataResolver` chooses cache, PIT storage, or a
bounded live scraper request according to `DataPolicy`, mode, and provenance.
Models declare required/optional status, freshness/alignment, and whether replay
support is required; they do not declare physical source allow-lists or resolver
capabilities. Replay never calls live acquisition. One bounded request phase runs
before model evaluation and equivalent requests are single-flight. Resolved
capability is runtime output (`LIVE_AND_REPLAY`, `LIVE_ONLY`, or `UNAVAILABLE`),
not an intrinsic model claim.

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

### Independent PriceRelay

Price updates are not a side effect of successful model evaluation. PriceRelay has
its own configured cadence and remains available to risk monitoring during model
warmup, external-data failure, policy suppression, or model failure.

PriceRelay records independent `PriceRelayProgress` and cannot silently claim
continuity after a detected input gap. Current risk uses `PriceUpdate.high`/`low`
for SL/TP monitoring, so D0 deliberately does not choose replay/catch-up versus
discard semantics for missed prices. A dedicated downstream risk compatibility
proof must establish those semantics before cutover.

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
availability timing. DataResolver is the only physical acquisition boundary.

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
