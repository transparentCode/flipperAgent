# `decision_app` semantic contracts

This document records the frozen D0 semantics and the implemented DA-2 runtime
amendments. It is intentionally language-neutral: implementation types must
preserve these fields and rules.

## Identity vocabulary

| Identity | Meaning | Stability |
| --- | --- | --- |
| `asset` | Configured downstream model asset, normalized by the application catalog. | Stable configuration identity. |
| `venue` | Canonical market venue supplied by `ingestion`. | Stable lane input identity. |
| `instrument_id` | Canonical venue instrument identity. | Stable lane input identity. |
| `timeframe` | Explicit bar duration, never inferred from arrival cadence. | Stable configuration identity. |
| `lane_id` | One authoritative decision lane for an asset/timeframe and configured lane identity. | Deterministic from canonical configuration. |
| `binding_id` | One named model binding slot inside a lane. | Deterministic from lane, slot, plugin/version, and binding configuration fingerprint. |
| `decision_id` | One authoritative lane result for one market cutoff. | Deterministic from lane revision and canonical `market_as_of`. |

An authoritative lane is the only publisher for its `(asset, decision timeframe)`
signal stream. A shadow lane can evaluate and record diagnostics but cannot publish
an authoritative result.

## Independent progress contracts

The runtime does not use one shared progress marker for input reading and
model-lane commit. These are distinct contracts:

```text
InputReadCursor
  canonical input stream identity
  latest stream ID / observed input position
  latest accepted canonical market cutoff

LaneCommitWatermark
  lane_id
  latest market_as_of whose state and publication disposition committed
```

`InputReadCursor` advances when the canonical stream reader observes and accepts
an input into the shared `BarStore`; it is not held back by model evaluation or
publication. Each `LaneCommitWatermark` advances independently, only after that
lane has successfully published its authoritative result or recorded its final
no-signal/skip disposition and committed proposed state. A lane failure leaves
that lane's `LaneCommitWatermark` unchanged without rolling back the input cursor
or BarStore. Decision has no price-relay or price-progress cursor; downstream
price continuity requires a separately approved risk-side feed change.

## Time contract

All conceptual times are timezone-aware UTC instants. A serialized representation
must be declared by the implementation and used consistently; magnitude-based
seconds/milliseconds guessing is prohibited.

| Field | Definition | Allowed use |
| --- | --- | --- |
| `bar_open_at` | Inclusive UTC start of the canonical bar interval. | Bar identity and chronology. |
| `bar_close_at` | Exclusive UTC end of the canonical bar interval. | Closed-bar availability and alignment. |
| `market_as_of` | Latest market event/cutoff included in a causal context. For a closed decision bar it equals its `bar_close_at`; for a projected view it equals the latest included source close. | Model inputs, dependency matching, decision identity. |
| `signal_time` | Market time of the decision. In V1 it equals `market_as_of`; it is not publication wall time. | Signal identity and downstream causal interpretation. |
| `decision_ready_at` | UTC wall-clock time when all required inputs/dependencies completed and the decision became publishable. | Latency, operations, and diagnostics only. |
| `event_time` | Timestamp intrinsic to an external data observation. | PIT ordering and semantic alignment. |
| `available_at` | Earliest time the external observation was available to the runtime/consumer. | Look-ahead prevention and replay selection. |
| `fetched_at` | Time this runtime acquired the snapshot. | Operational provenance only. |

`decision_ready_at` must never be used as a substitute for `market_as_of` or
`signal_time`. It is also compared with `market_as_of` solely by the configured
freshness gate; a stale result is skipped, never published.

## DecisionContext

`DecisionContext` is the complete immutable input to one model evaluation. It
contains at least:

```text
DecisionContext
  asset
  venue
  instrument_id
  lane_id
  binding_id

  market_as_of
  trigger_timeframe
  decision_timeframe
  trigger_mode
  decision_bar
  decision_bar_closed

  causal_bar_views
    timeframe -> bounded ordered bar view through market_as_of
  shared_features
    feature_name -> value with feature provenance
  external_data
    always empty in the current Decision runtime
  upstream_artifacts
    dependency slot -> ModelArtifact
  provenance
    input read cursor, observed source cutoffs, stream ids, history cutoffs
```

The model receives no DB pool, Valkey client, HTTP client, scraper object,
repository, or scheduler. `decision_bar_closed` is explicit. An incomplete or
projected bar cannot be silently treated as a closed bar.

## ModelSpec

`ModelSpec` describes intrinsic plugin behavior and capabilities:

```text
ModelSpec
  name
  version
  stateful
  output_kind
    analytical | predictive | decision_capable
  trigger_modes
  supported_timeframes
  input_contract
  intrinsic_feature_requirements
  intrinsic_data_requirements
  warmup_requirements
  state_reconstruction
    durable_pit_required_when_stateful
```

The spec does not contain asset-specific wiring or operator policy. A model may
produce an analytical artifact without direction or a trade decision. A stateful
spec must declare enough information for the runtime to reconstruct it from
durable canonical inputs. DA-2 rejects any model spec with non-empty
`intrinsic_data_requirements`; external-data execution is not active.

## ResolvedModelBinding

The runtime resolves one configured binding slot to a concrete binding:

```text
ResolvedModelBinding
  binding_id
  lane_id
  slot_name
  plugin_name
  plugin_version
  model_spec
  parameters
  binding_config_fingerprint
  effective_lane_revision
  trigger_timeframe
  decision_timeframe
  trigger_mode
  dependencies
    named slot -> binding_id
  effective_feature_requirements
  risk_profile_key
  publication_authority
```

Resolution is static at process startup. Dependencies must point to a binding
inside the same lane, must be acyclic, and must resolve to compatible artifact
types. A dependency is executed once per binding/as-of and its artifact is reused
for all dependents.

## Retained external-data contracts (inactive)

The shared library retains `DataRequirement`, `DataRequest`, `DataSnapshot`,
`validate_data_snapshot`, `DataMode`, and `ResolvedCapability` for compatibility.
These types do not imply a current Decision acquisition path. The planner rejects
non-empty `ModelSpec.intrinsic_data_requirements`; `ResolvedModelBinding` has no
effective data-requirements field; and runtime `DecisionContext.external_data` is
empty. Reintroducing external data requires a separately reviewed implementation
that proves causal availability and replay/PIT semantics before any source is
activated.

## FeaturePlan and feature policy

```text
FeaturePlan
  lane_id
  requested_shared_features
  operator_allowed_features
  model_private_features
  effective_shared_features
  disabled_features
```

Effective shared computation is:

```text
model demands feature AND operator policy allows feature
    -> compute once per lane/as-of

model demands feature AND operator policy disables feature
    -> required binding unavailable; optional value absent
```

Model-private deterministic transforms execute within the plugin and remain
bounded by the runtime evaluation budget. There is no always-on universal feature
vector.

## ModelArtifact and ModelOutcome

An artifact is a typed analytical result, not necessarily a trade instruction:

```text
ModelArtifact
  artifact_type
  binding_id
  asset
  market_as_of
  produced_at
  payload
  provenance
```

One evaluation returns:

```text
ModelOutcome
  artifact
  decision: optional ModelDecision
  metadata
  proposed_next_state: optional opaque state value
```

`evaluate()` is synchronous in semantic terms and receives complete input already
resolved by the runtime. It may perform deterministic CPU work but may not perform
recursive I/O. The runtime may run that work on a bounded CPU executor.

## ModelDecision

```text
ModelDecision
  binding_id
  asset
  decision_timeframe
  trigger_timeframe
  market_as_of
  signal_time
  direction_hint: -1 | 0 | 1 | absent
  score: optional typed score
  conviction: optional normalized confidence
  metadata
```

Scores are not comparable across plugins unless `DecisionPolicy` declares the
normalization and weighting rule. Analytical models can return no decision.

## Stateful evaluation and commit

Stateful evaluation is transactional at the runtime boundary:

```text
committed_state + complete_context + upstream_artifacts
    -> ModelOutcome(proposed_next_state)
    -> policy
    -> successful idempotent publication, final no-signal, or explicit skip
    -> commit proposed_next_state
    -> advance affected LaneCommitWatermark
```

The plugin must not mutate the committed state object during evaluation. A
publication failure or conflict leaves committed state and the affected
`LaneCommitWatermark` unchanged. It does not roll back `InputReadCursor` or
`BarStore` progress. If the required trigger has a causal gap, missing required
data, unavailable dependency, or model exception, the binding transitions to
`DEGRADED` or `INVALID`. The old state cannot be used for a later trigger as if
the missed transition succeeded; input reading and unrelated lanes continue.

The runtime must causally rewarm before returning the binding to `LIVE` by
replaying the same execution chain used in live operation: causal bar views,
shared features, upstream dependencies in topological order, then the stateful
binding, with publication suppressed. External-data execution is inactive and
non-empty intrinsic data requirements are rejected.

## DecisionPolicy result

```text
DecisionPolicyResult
  lane_id
  market_as_of
  decision: optional authoritative TradeSignal intent
  contributing_artifacts
  normalization / gating / weighting evidence
  policy_version
  feature_plan_fingerprint
  effective_lane_revision
  binding_config_fingerprints
  decision_ready_at
```

The policy is lane-local and produces zero or one authoritative result per
market_as_of. Risk allocation, SL/TP, position limits, and execution are not part
of this result.

## TradeSignal boundary

The active Decision-to-Risk payload contains:

```text
TradeSignal
  asset
  timeframe
  timestamp: epoch seconds derived from market_as_of
  direction
  conviction
  price
  idempotency_key
  model_name: configured risk_profile_key
  metadata: market_as_of_utc, decision identity/revision, policy and contributor provenance
```

The Valkey stream entry ID is milliseconds derived from the same
`market_as_of`; it is not the unit of `TradeSignal.timestamp`. The freshness
gate uses `decision_ready_at - market_as_of`; `decision_ready_at` is not used as
market identity.

The stable passthrough model identity or explicitly configured composed
`risk_profile_key` is the risk-selection key. Contributor model names belong in
metadata/provenance and must not accidentally become a composed lane's risk key.
Risk compares the seconds-valued signal timestamp with wall-clock seconds. A
separate `PriceUpdate` timestamp is milliseconds and Risk converts it to seconds;
Decision does not publish that type.

## Publication identity and idempotency

Canonical identity serialization is deterministic:

```text
lane_id = canonical asset + decision timeframe + configured lane identity
binding_config_fingerprint = SHA-256(canonical binding parameters + runtime binding)
binding_id = lane_id + named slot + plugin/version + binding_config_fingerprint
LaneExecutionIdentity = (lane_id, effective_lane_revision, feature_plan_fingerprint)
decision_execution_revision = SHA-256(lane_id + base lane revision + feature plan + policy)
decision_id = lane_id + decision_execution_revision + canonical UTC market_as_of
```

The canonical serialization includes effective parameters, runtime binding,
feature-plan identity, and policy configuration. Therefore a material change
produces a new fingerprint/revision and cannot reuse an identity for different
behavior. The physical `data_plan_fingerprint` columns remain in the checkpoint
and effect-progress tables for compatibility and are written as the constant
`none`; they are excluded from runtime identity. The authoritative lane uses a deterministic transport entry identity
derived from `decision_id`/`market_as_of`. Raw Valkey XADD rejects a duplicate
explicit ID; an adapter must first look up the existing entry and compare the
identity and payload. An identical retry is success, while a same-identity,
different-payload result is a conflict and fails closed. The runtime does not
create a second authoritative lane to avoid a publication conflict.

## Lane readiness and progress

```text
LaneReadiness
  state: WARMING | LIVE | DEGRADED | INVALID | PAUSED | STOPPED
  required_cutoff
  input_read_cursor
  observed_cutoffs
  lane_commit_watermark
  missing_inputs
  missing_dependencies
  last_rewarm_reason
```

Readiness is evaluated against canonical cutoffs for every required timeframe and
dependency. An arrival-only condition is insufficient.

## Startup and replay contract

The startup sequence is:

```text
resolve streams and static graph
  -> capture InputReadCursor / stream tails / candle cutoffs
  -> warm BarStores from Timescale through latest retained trigger cutoffs R
  -> validate required lane history at R
  -> probe exact first-unaccounted publication ID X
  -> rewarm stateful bindings through R with publication suppressed
  -> record compact skip ranges; do not replay stale stateless effects
  -> install lanes and begin reads after captured stream IDs
  -> evaluate stateless R only when the live freshness gate permits it
```

Temporary broker interruption resumes from the in-memory `InputReadCursor` when
the stream is continuous. A proven forward canonical market gap requests one
`INPUT_RECONSTRUCTION` generation rebuild; generic lane-level
`RECONSTRUCTION_REQUIRED` remains lane-local and does not request this rebuild.
Full restart validates history at the latest retained trigger cutoff `R`; it does
not replay stateless publication effects across downtime. For stored effect
progress `P`, startup probes the exact ID for `P + duration` (or `R` when no `P`
exists). An exact current-identity entry reconciles as already effected; a
different identity at that ID is recorded as `foreign_entry`, not republished.
Stateless cutoffs after the probe and before `R` are one `restart` skip range;
only `R` may be evaluated live, and only when fresh. Stateful lanes rewarm every
required transition through `R` with publication suppressed, then record the
missed range as `restart_rewarm` and resume at `R + trigger_duration`. Skipped
progress uses NULL disposition; the append-only skip table preserves the reason
and range without one row per cutoff.
When a single-cutoff `stale` or `foreign_entry` row already exists at the first
unaccounted cutoff (live records it after the cutoff commits and before it saves
progress), startup advances progress to that cutoff and does not probe or
re-record it, so an interrupted progress save cannot block the lane.

## Freshness and effect skips

Authoritative `SIGNAL` decisions and all shadow observations are published only
when `decision_ready_at - market_as_of <= signal_freshness_seconds` (300 seconds
by default). Exactly 300 seconds is fresh. A stale result commits proposed state
and advances its lane watermark with disposition `skipped`, but publishes no
signal or shadow observation. Its cutoff is recorded in the append-only
`decision.lane_effect_skips` table; latest effect progress advances with a NULL
disposition for skipped work. Restart ranges and foreign exact-ID entries use the
same durable skip trail, without expanding into one row per skipped cutoff.

## Service availability and recovery

Startup evidence is lane-isolated. `STARTUP_READY` means all active configured
lanes reconstructed; `STARTUP_BLOCKED` records one or more blocked lanes, not a
fatal generation-construction result. A generation installs every ready lane;
series capture/history failures, manifest-read failures, and lane reconstruction
failures block only their dependent series, asset, or lane. First-generation
static planning/configuration errors and application resource-construction
failures remain fatal.

The service schedules generation-level `AUTOMATIC_RECOVERY` for malformed or
conflicting input, non-forward-gap `RECONSTRUCTION_REQUIRED`, halted/invalid or
reconstruction-required lanes, blocked startup lanes, and failed rebuilds.
Automatic attempts use exponential delays from 5 seconds through a 300-second
cap. While an installed generation waits for an automatic retry, it continues
polling so healthy lanes can progress. A forward canonical market gap is the
separate immediate `INPUT_RECONSTRUCTION` path; manual control and lifecycle
reconciliation are also immediate. Rebuild precedence is
`LIFECYCLE_RECONCILIATION` > `MANUAL` > `INPUT_RECONSTRUCTION` >
`AUTOMATIC_RECOVERY`. A failed non-automatic rebuild retains its source and
request, exposes `ERROR`/not-ready, and retries after the bounded backoff; a
failed automatic rebuild retains the current generation in `DEGRADED` and
retries it.

Readiness is true only under the existing installed-generation, desired-running,
and `RUNNING`/`DEGRADED` service conditions, except that a zero-lane configuration
does not acquire a lane-liveness deadline. For a running configuration with at
least one lane, no `LIVE` lane for more than 300 seconds makes readiness false
with reason `no_lane_live`; absence of an installed generation reports
`no_generation`. The 300-second interval is an availability threshold, not a
market or causal-progress guarantee. `/health/live` remains independent of
readiness. Status includes `not_live_seconds` and pending rebuild source,
attempt, and due time.

## Bounded runtime and resource ownership

The D9 implementation adds an operational envelope without changing the D0
causal, identity, progress, publication, or downstream ownership contracts:

```text
initial resources + first generation: one absolute 120s deadline
Valkey command + DB acquisition: <= 5s native I/O budget
canonical history + checkpoint/effect SQL / transaction: one remaining 15s budget
control admission + effect-task drain: <= 30s
owned cleanup: one lazy aggregate <= 5s budget
```

These numeric defaults are approved configuration values sourced from
`configs/decision/global.yaml`; this document and the architecture catalog do
not define a second configuration authority.

The cleanup budget is shared across nested owners. A startup failure may cap its
cleanup expiry at the startup deadline plus the cleanup allowance; successful
startup starts a fresh lazy budget for final shutdown. Normal shutdown activates
cleanup only after the control/drain phase.

Only Decision-owned resources may be closed. Borrowed resources remain borrowed.
An unconfirmed lease or resource release retains ownership and fences reuse. The
service `STOPPED` state means owned service tasks are quiescent; a clean lifespan
also requires confirmed owned-resource teardown, so cleanup failure may leave the
service `STOPPED` while application shutdown is unclean. These rules describe
bounded implementation behavior and do not certify a deployment, backend
leak-freedom, or soak.

## Downstream price continuity

Decision does not own or publish `price_update:*`. Risk-side stop-loss,
take-profit, and mark-to-market price continuity requires a separately approved
downstream feed change. DA-2 does not alter Risk, Execution, or Portfolio
contracts.

## Asset lifecycle and control states

Ingestion lifecycle is availability authority:

```text
LIVE       -> configured asset/lane runtimes may evaluate
PAUSED     -> configured runtimes stop evaluation under explicit policy
REMOVING   -> runtime tears down and emits removal state
STOPPED    -> no evaluation until a new authoritative live transition
```

Asset lifecycle never invents model bindings or timeframes. A configured lane may
also be disabled without changing the asset manifest. Open-position and
liquidation behavior remains a downstream risk contract and is not invented here.
