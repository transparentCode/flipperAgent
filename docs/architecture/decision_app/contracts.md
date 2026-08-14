# `decision_app` semantic contracts

This document freezes meaning and invariants for D0. It is intentionally
language-neutral: later implementation may choose Python dataclasses, Pydantic
models, or equivalent internal types, but it must preserve these fields and
rules.

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

The runtime does not use one shared progress marker for input reading, model-lane
commit, and price handling. These are distinct contracts:

```text
InputReadCursor
  canonical input stream identity
  latest stream ID / observed input position
  latest accepted canonical market cutoff

LaneCommitWatermark
  lane_id
  latest market_as_of whose state and publication disposition committed

PriceRelayProgress
  relay plan identity
  latest canonical market_as_of successfully handled
  continuity status / detected gap evidence
```

`InputReadCursor` advances when the canonical stream reader observes and accepts
an input into the shared `BarStore`; it is not held back by model evaluation or
publication. Each `LaneCommitWatermark` advances independently, only after that
lane has successfully published its authoritative result or recorded its final
no-signal disposition and committed proposed state. A lane failure leaves that
lane's `LaneCommitWatermark` unchanged without rolling back the input cursor or BarStore;
unrelated lanes and PriceRelay continue.

`PriceRelayProgress` is independent of lane progress. PriceRelay must not silently
claim continuity after a detected input gap. Because current downstream risk uses
`PriceUpdate.high`/`low` for SL/TP monitoring, the exact missed-price catch-up or
discard semantics are deferred to a dedicated downstream risk-compatibility proof;
D0 selects neither policy.

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
`signal_time`. A decision may be ready later than its market cutoff without
changing its market identity.

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
    semantic request key -> DataSnapshot
  upstream_artifacts
    dependency slot -> ModelArtifact
  provenance
    input read cursor, observed source cutoffs, stream ids, history cutoffs,
    resolver decisions
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
durable PIT-safe inputs.

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
  effective_data_requirements
  risk_profile_key
  publication_authority
```

Resolution is static at process startup. Dependencies must point to a binding
inside the same lane, must be acyclic, and must resolve to compatible artifact
types. A dependency is executed once per binding/as-of and its artifact is reused
for all dependents.

## DataRequirement and DataRequest

Models declare semantic requirements; the runtime resolves physical acquisition.

```text
DataRequirement
  concept
    OPEN_INTEREST | BTC_DOMINANCE | LIQUIDATION_HEATMAP | ...
  required
  replay_support_required
  max_age_at_market_as_of
  max_available_lag
  alignment
    exact | at_or_before | bounded_window
```

At evaluation time, the resolver materializes a request:

```text
DataRequest
  request_key
  concept
  asset / optional scope
  market_as_of
  required
  freshness_bound
  mode
    LIVE | REPLAY
  resolver_knowledge_cutoff
```

`DataRequirement` is a model-level semantic demand. It does not name physical
sources or claim an infrastructure capability. `DataPolicy` is owned by
`decision_app` and supplies physical routing, source allow-lists, freshness and
availability rules, and the resolver's resolved capability:

```text
DataPolicy
  live_source_order
  replay_source_order
  allowed_physical_sources
  freshness_and_availability_rules
  resolved_capability
    LIVE_AND_REPLAY | LIVE_ONLY | UNAVAILABLE
```

`resolver_knowledge_cutoff` is runtime-supplied context for the selected mode; it
is not a model-controlled physical-source choice.

The runtime runs one bounded request phase before model evaluation. Equivalent
requests for a lane/as-of are single-flight and share the resulting snapshot.
Missing optional data is explicit. Missing required data makes the binding
unavailable for that trigger; it is not silently replaced by an older or live-only
value.

## DataSnapshot

```text
DataSnapshot
  request_key
  concept
  payload
  event_time
  available_at
  fetched_at
  source
  resolved_capability
    LIVE_AND_REPLAY | LIVE_ONLY | UNAVAILABLE
  provenance
  freshness_check
```

For `LIVE` resolution, the policy is runtime cache → PIT database → one permitted
bounded scraper request. For `REPLAY`, only PIT durable sources are eligible.
The resolver must enforce these point-in-time rules:

```text
represented observation/window end <= market_as_of
event_time <= market_as_of
cache latest result must be bounded by market_as_of
REPLAY available_at <= resolver_knowledge_cutoff
```

For replay, `resolver_knowledge_cutoff` is the simulated evaluation cutoff. For
live resolution it is the runtime's actual resolver cutoff used with the
freshness policy. `available_at` must be known before a snapshot can satisfy a
PIT-sensitive requirement. `fetched_at` is never evidence that the source was
historically available.

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
    -> successful idempotent publication (or final no-signal result)
    -> commit proposed_next_state
    -> advance affected LaneCommitWatermark
```

The plugin must not mutate the committed state object during evaluation. A
publication failure or conflict leaves committed state and the affected
`LaneCommitWatermark` unchanged. It does not roll back `InputReadCursor` or
`BarStore` progress. If the required trigger has a causal gap, missing required
data, unavailable dependency, or model exception, the binding transitions to
`DEGRADED` or `INVALID`. The old state cannot be used for a later trigger as if
the missed transition succeeded; input reading, unrelated lanes, and PriceRelay
continue.

The runtime must causal-rewarm before returning the binding to `LIVE` by replaying
the same execution chain used in live operation: causal bar views, shared
features, replay-safe external data, upstream dependencies in topological order,
then the stateful binding, with publication suppressed. In V1, a stateful binding
may not consume `LIVE_ONLY` external data; every stateful input must be
reconstructable from durable PIT-safe `LIVE_AND_REPLAY` data.

## DecisionPolicy result

```text
DecisionPolicyResult
  lane_id
  market_as_of
  decision: optional authoritative TradeSignal intent
  contributing_artifacts
  normalization / gating / weighting evidence
  policy_version
  effective_lane_revision
  binding_config_fingerprints
  decision_ready_at
```

The policy is lane-local and produces zero or one authoritative result per
market_as_of. Risk allocation, SL/TP, position limits, and execution are not part
of this result.

## TradeSignal boundary

The future decision output is conceptually:

```text
TradeSignal
  decision_id
  asset
  decision_timeframe
  market_as_of
  signal_time
  decision_ready_at
  direction
  conviction
  price_at_market_as_of
  risk_profile_key
  idempotency_key
  metadata / contributor provenance
```

The stable passthrough model identity or explicitly configured composed
`risk_profile_key` is the risk-selection key. Contributor model names belong in
metadata/provenance and must not accidentally become a composed lane's risk key.
The existing downstream numeric `TradeSignal.model_name`/timestamp boundary is
an adapter concern for a later coordinated migration; D0 does not alter it.

## Publication identity and idempotency

Canonical identity serialization is deterministic:

```text
lane_id = canonical asset + decision timeframe + configured lane identity
binding_config_fingerprint = SHA-256(canonical binding parameters + runtime binding)
binding_id = lane_id + named slot + plugin/version + binding_config_fingerprint
effective_lane_revision = SHA-256(canonical effective lane + policy configuration)
decision_id = lane_id + effective_lane_revision + canonical UTC market_as_of
```

The canonical serialization includes effective parameters, runtime binding, and
policy configuration. Therefore a parameter, binding, or policy change produces a
new fingerprint/revision and cannot reuse an identity for materially different
behavior. The authoritative lane uses a deterministic transport entry identity
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
  -> warm BarStores from Timescale through cutoffs
  -> replay causal chain: bars -> shared features -> replay-safe external data
  -> execute upstream dependencies topologically, then stateful bindings
  -> verify every required cutoff and reconstructed binding
  -> begin live reads after captured stream ids
  -> process only post-cutoff events
```

Temporary broker interruption resumes from the in-memory `InputReadCursor` when the
stream is continuous. A detected stream gap causes causal reconstruction of the
affected `BarStore` views and lanes from Timescale, with new input and lane
progress positions. Full restart reconstructs state and resumes input reading; stale
historical decisions are not republished from a persistent PEL in V1.

## PriceRelay

```text
PriceRelayPlan
  asset
  source lane / canonical price source
  timeframes
  publication cadence
  downstream risk compatibility
```

PriceRelay runs from canonical BarStore observations independently of model-lane
evaluation and records `PriceRelayProgress`. A model failure cannot block eligible
price handling or advance of unrelated lane state. If PriceRelay detects a gap,
it enters an explicit unresolved/degraded condition rather than silently asserting
continuous SL/TP coverage. The recovery/catch-up policy is a later downstream risk
compatibility gate because `risk_app` uses price high/low observations for SL/TP
monitoring.

The relay is independently configured and may publish eligible prices while model
bindings are warming, degraded, unavailable, or policy-suppressed. Model, data,
scraper, and policy failures cannot prevent eligible price updates.

## Asset lifecycle and control states

Ingestion lifecycle is availability authority:

```text
LIVE       -> configured asset/lane runtimes may evaluate
PAUSED     -> configured runtimes stop evaluation under explicit policy
REMOVING   -> runtime tears down and emits removal state
STOPPED    -> no evaluation until a new authoritative live transition
```

Asset lifecycle never invents model bindings or timeframes. A configured lane may
also be disabled without changing the asset manifest. PriceRelay behavior is an
explicit policy field. Open-position and liquidation behavior remains a downstream
risk contract and is not invented here.
