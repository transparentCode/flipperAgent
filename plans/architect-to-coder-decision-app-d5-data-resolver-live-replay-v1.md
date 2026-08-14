---
goal: Implement the deterministic PIT-safe semantic DataPlan and bounded LIVE/REPLAY DataResolver for decision_app
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d5, data-resolver, pit, replay]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D5 semantic DataResolver LIVE/REPLAY

## 1. Objective

Implement the **smallest deterministic external-data policy and resolution layer** on top of approved D0–D4.

D5 must establish the executable boundary:

```text
ResolvedLanePlan
+ ModelSpec intrinsic semantic DataRequirement envelope
+ explicit app-owned DataPolicy
+ explicit app-owned physical source catalog
        ↓
deterministic DataPlan
        ↓
runtime-materialized DataRequest batch
        ↓
DataResolver
  LIVE   : cache -> PIT -> at most one bounded LIVE source
  REPLAY : PIT durable sources only
        ↓
PIT/freshness/alignment/capability validation
        ↓
shared DataSnapshot per equivalent request
        ↓
binding-isolated DataResolution evidence
```

D5 performs **no model plugin execution**. In particular it does not call:

```text
DecisionModelPlugin.data_requests()
DecisionModelPlugin.evaluate()
```

D6 will invoke the plugin request phase, validate the returned semantic demands against the approved D5 static envelope, materialize `DataRequest` values, and assemble complete `DecisionContext` objects.

D5 must provide the pure/materialization and validation helpers D6 will use, but must not start D6.

Expected terminal status:

```text
DECISION_APP_D5_DATA_RESOLVER_LIVE_REPLAY_READY_FOR_REVIEW
```

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not start from plain `main`; approved D0–D4 artifacts in this worktree are the source of truth.

---

# 2. Approved source of truth

Preserve:

```text
docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
docs/architecture/decision_app/decisions.md
docs/architecture/decision_app/catalog.yaml

src/libs/contracts/decision.py
src/apps/decision_app/contracts.py
src/apps/decision_app/identity.py
src/apps/decision_app/planner.py
src/apps/decision_app/market_state.py
src/apps/decision_app/readiness.py
src/apps/decision_app/view.py
src/apps/decision_app/features.py
src/apps/decision_app/feature_engine.py

plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Status entering D5:

```text
D0 APPROVED
D1 APPROVED
D2 APPROVED
D3 APPROVED
D4 APPROVED
```

D5 implements the D0 rules:

```text
Model owns semantic demand.
decision_app owns physical I/O policy.

LIVE:
  runtime cache
  -> PIT durable source
  -> one permitted bounded live acquisition

REPLAY:
  PIT durable sources only
  -> never cache-latest semantics
  -> never live scraper/acquisition

represented observation/window end <= market_as_of
event_time <= market_as_of
available_at <= resolver_knowledge_cutoff
fetched_at is operational provenance only
```

---

# 3. Hard D5 principles

1. **Models never name physical sources.** `DataRequirement` stays semantic.
2. **DataPolicy is application-owned.** Cache/DB/live source names belong only to `decision_app`.
3. **Resolved capability is runtime/source evidence.** A model never claims `LIVE_AND_REPLAY` or `LIVE_ONLY`.
4. **Replay cannot touch LIVE-only acquisition.** This is a hard testable boundary.
5. **One bounded request phase.** No recursive data request from a source or feature/model callback.
6. **Equivalent requests share one physical acquisition/result per resolver call.** No per-binding duplicate I/O.
7. **Binding visibility remains isolated.** A binding sees only its requested snapshots.
8. **Missing required data affects only the requesting binding.** Independent bindings continue.
9. **Optional missing data is explicit but does not make the binding unavailable.**
10. **Source precedence is explicit and deterministic.** First valid candidate in configured route wins.
11. **A future/stale/ineligible cache candidate is rejected and may fall through to the next allowed source.** It is never silently accepted as “latest.”
12. **No retries/backoff/poll loops in D5.** Those belong to runtime integration if later needed.
13. **No persistent internal data cache in D5.** A physical cache may be represented as a source adapter; the resolver itself does not become a cache framework.
14. **No general provider framework.** Explicit small source definitions and one protocol/callable boundary are enough.
15. **Material DataPolicy/source version changes are identity changes.** D5 records a deterministic `data_plan_fingerprint` for later D8 authoritative identity.

---

# 4. Scope

## Preferred production files

Keep D5 small. Prefer:

```text
src/libs/contracts/decision.py
    small additive DataRequest contract fields / ModelSpec data-demand tightening only

src/apps/decision_app/data.py
    physical source definitions/catalog
    DataPolicy / concept routes
    DataPlan + fingerprint
    request-key/materialization helpers

src/apps/decision_app/data_resolver.py
    bounded async resolver
    candidate validation
    attempt evidence
    binding/shared resolution outputs
```

`src/apps/decision_app/identity.py` may be reused but should not require redesign.

Do not create more production modules unless an actual ownership conflict appears.

## Preferred tests

Add at most two focused D5 files:

```text
tests/decision/test_data_policy.py
tests/decision/test_data_resolver.py
```

Update existing D1/D2 tests only where the authorized additive `DataRequest` / `ModelSpec` semantics require it.

---

# 5. Explicit non-goals

D5 must not implement or modify:

```text
DecisionModelPlugin.data_requests() invocation
DecisionModelPlugin.evaluate() invocation
model instantiation/model runtime
same-lane model dependency execution
DecisionContext assembly
model state / state commit / causal rewarm orchestration
DecisionPolicy
TradeSignal publication
PriceRelay
Valkey/Redis integration
Timescale repository adapter
real cache client
real scraper/HTTP client
FastAPI/control plane
Docker/Compose
configs/decision
AssetRuntime
input consumer/read loop
background tasks
retry/backoff framework
persistent resolver cache
feature computation changes
feature DAG
data DAG
real model migration
signal_app/strategy_app/risk_app/execution_app changes
```

No new third-party dependency.

Do not commit, merge, push, switch branches, reset, or restore.

---

# 6. Authorized additive shared-contract tightening

D1 created `DataRequest` before D5 had executable request semantics. D5 may add only the missing runtime-materialized semantic constraints needed to validate a snapshot.

## 6.1 Extend `DataRequest`

Preserve current fields and add:

```text
replay_support_required: bool = False
max_available_lag: timedelta | None = None
alignment: exact | at_or_before | bounded_window = at_or_before
```

Keep:

```text
freshness_bound
```

as the materialized runtime form of:

```text
DataRequirement.max_age_at_market_as_of
```

Do not add physical source names to `DataRequest`.

Required strict validation:

```text
required is bool
replay_support_required is bool
mode is explicit LIVE | REPLAY
alignment is one approved value
freshness/max_available_lag are None or non-negative timedelta
market_as_of UTC
resolver_knowledge_cutoff UTC
resolver_knowledge_cutoff >= market_as_of
```

`DataRequest.required` is binding availability semantics; it is intentionally not a physical source-routing field.

## 6.2 Tighten `ModelSpec` intrinsic data requirements

A plugin must not declare the same semantic concept twice with contradictory constraints.

Require unique:

```text
DataRequirement.concept
```

within `ModelSpec.intrinsic_data_requirements`.

Do not add source/policy metadata to `ModelSpec`.

---

# 7. Freeze D5 interpretation of DataRequirement constraints

No live semantics exist elsewhere in the repository, so D5 must make these explicit and test them.

For a candidate `DataSnapshot`, define:

```text
effective_observation_end =
  snapshot.represented_end_at if supplied
  else snapshot.event_time
```

Base PIT rules remain:

```text
snapshot.event_time <= request.market_as_of
snapshot.represented_end_at <= request.market_as_of, when supplied
snapshot.available_at <= request.resolver_knowledge_cutoff
```

`fetched_at` does not satisfy any freshness/PIT condition.

## 7.1 Alignment

### `exact`

Require:

```text
effective_observation_end == market_as_of
```

### `at_or_before`

Require:

```text
effective_observation_end <= market_as_of
```

which is already implied by the base PIT rule.

### `bounded_window`

Require:

```text
represented_end_at is present
represented_end_at <= market_as_of
```

D5 does not invent a represented-window start field.

## 7.2 Freshness

When `freshness_bound` is present:

```text
market_as_of - effective_observation_end <= freshness_bound
```

A future effective observation end is rejected by the base PIT rule rather than producing a negative age.

## 7.3 Availability lag

When `max_available_lag` is present, define availability lag as:

```text
available_at - effective_observation_end
```

Require:

```text
available_at >= effective_observation_end
available_at - effective_observation_end <= max_available_lag
```

This is source-publication/availability latency, not fetch latency.

`fetched_at - available_at` is never used for semantic acceptance.

## 7.4 Replay capability

Require `LIVE_AND_REPLAY` when either:

```text
request.mode == REPLAY
```

or:

```text
request.replay_support_required == True
```

Therefore a LIVE evaluation of a stateful/replay-required input cannot quietly consume a `LIVE_ONLY` source.

Implement a small pure D5 validator around the existing D1 `validate_data_snapshot()` rather than duplicating the base PIT checks.

---

# 8. Physical source definition and catalog

D5 must model physical sources explicitly but must not implement real infrastructure clients.

## 8.1 Source kinds

Use only:

```text
cache
pit
live
```

Semantics:

- `cache`: runtime/cache lookup semantics; LIVE only in V1;
- `pit`: durable PIT-safe source; eligible for LIVE and REPLAY if capability permits;
- `live`: bounded live acquisition/scraper semantics; LIVE only.

No source subtype hierarchy.

## 8.2 `DataSourceDefinition`

Approximately:

```text
DataSourceDefinition
  name
  version
  kind: cache | pit | live
  capability: LIVE_AND_REPLAY | LIVE_ONLY
  fetcher: async callable(DataRequest) -> DataSnapshot | None
```

Rules:

- name/version non-empty;
- no `UNAVAILABLE` registration capability; runtime unavailability is represented by miss/rejection/error;
- fetcher must be callable;
- definition immutable;
- callable repr/address is never identity;
- D5 tests use synthetic async fetchers only.

A source may return `None` for no candidate.

## 8.3 `DataSourceCatalog`

Explicit immutable catalog keyed by source name.

Required behavior:

```text
explicit construction only
one definition per source name
duplicate name rejected
unknown lookup rejected
deterministic iteration sorted by name
immutable backing state
no import scanning
auto discovery prohibited
no factory framework
```

---

# 9. App-owned DataPolicy

## 9.1 `ConceptDataPolicy`

Approximately:

```text
ConceptDataPolicy
  concept
  scope_mode: lane_asset | global
  live_source_order: tuple[source_name, ...]
  replay_source_order: tuple[source_name, ...]
```

D5 V1 supports only the two scope modes above.

Materialization:

```text
lane_asset:
  DataRequest.asset = resolved_lane.asset
  DataRequest.scope = None

global:
  DataRequest.asset = None
  DataRequest.scope = "global"
```

The model cannot override scope in V1.

Do not build arbitrary cross-asset request routing in D5.

## 9.2 `DataPolicy`

Approximately:

```text
DataPolicy
  name
  version
  concepts: concept -> ConceptDataPolicy
```

No wildcard concepts or inheritance.

## 9.3 Route validation against source catalog

At plan compile, validate every referenced source exists.

LIVE source order must follow non-decreasing kind order:

```text
cache -> pit -> live
```

Allowed examples:

```text
cache, pit, live
pit, live
cache, pit
pit
live
```

Reject examples:

```text
live, pit
pit, cache
live, live
```

Allow multiple cache/PIT sources if explicitly configured, but allow **at most one `live` source** in a concept LIVE route.

REPLAY route rules:

```text
source kind == pit
source capability == LIVE_AND_REPLAY
```

No cache and no live acquisition in a replay route.

Source names within one route must be unique.

A route may be empty. This is explicit policy absence and is handled as unavailable for requests in that mode; do not silently substitute the other mode's route.

---

# 10. Static DataPlan

Compile one immutable D5 plan per `ResolvedLanePlan` from:

```text
ResolvedLanePlan
+ DataPolicy
+ DataSourceCatalog
```

Recommended shapes:

```text
BindingDataPlan
  binding_id
  requirements: tuple[DataRequirement, ...]
  required_concepts
  optional_concepts

ResolvedConceptDataRoute
  concept
  scope_mode
  live_source_order
  replay_source_order
  source_versions
  source_kinds
  source_capabilities

DataPlan
  lane_id
  base_lane_revision
  data_policy_name
  data_policy_version
  requested_concepts
  routes: concept -> ResolvedConceptDataRoute
  unrouted_concepts
  bindings: binding_id -> BindingDataPlan
  data_plan_fingerprint
```

Keep exact names small if equivalent semantics are preserved.

## 10.1 Requested concepts

Union only the lane's `ResolvedModelBinding.effective_data_requirements` concepts.

Unrequested DataPolicy concepts/source definitions must not enter the lane plan fingerprint.

## 10.2 Unrouted concepts

A requested concept with no `ConceptDataPolicy` is explicit:

```text
unrouted_concepts
```

Do not fail the whole lane plan merely because an independent binding has an unrouted optional/required potential requirement. D6/runtime request resolution will decide the affected binding for each actual request phase.

Do not invent a fallback policy.

## 10.3 Binding demand integrity

`BindingDataPlan` must preserve the exact sorted intrinsic requirement tuple from the corresponding `ResolvedModelBinding.effective_data_requirements`.

Provide a pure:

```text
validate_data_plan_against_lane(data_plan, resolved_lane)
```

that rejects:

```text
lane_id mismatch
base revision mismatch
missing/extra binding ID
changed concept
required/optional drift
replay-support drift
freshness drift
availability-lag drift
alignment drift
```

The resolver and request materializer must call this validator; they must not trust a caller-supplied plan because its binding IDs look correct.

---

# 11. Data-plan deterministic fingerprint

D5 introduces:

```text
data_plan_fingerprint
```

Use the existing canonical SHA-256 helper.

Include only material used semantics:

```text
lane_id
D2 base effective_lane_revision
DataPolicy name/version
per-binding exact DataRequirement envelope
requested/unrouted concepts
for each requested routed concept:
  scope_mode
  live/replay ordered source names
  used source definition versions
  source kinds
  source capabilities
```

Do not include:

```text
fetcher repr
object address
wall clock
unused source definitions
unrequested concept policies
```

Requirements:

```text
input order does not affect fingerprint
policy name/version change -> fingerprint changes
route order change -> fingerprint changes
used source version/capability/kind change -> fingerprint changes
DataRequirement semantic change -> fingerprint changes
unrequested source/catalog entry addition -> fingerprint unchanged
```

## 11.1 Fingerprint self-integrity

Follow approved D4 precedent.

`DataPlan.__post_init__` must recompute its canonical fingerprint from normalized semantic fields and reject:

```text
supplied fingerprint != recomputed fingerprint
```

A stale/tampered DataPlan may not retain an older identity.

## 11.2 Identity carry-forward

Record in the coder handoff:

> Before D8 authoritative publication, final effective lane/decision identity must incorporate approved `feature_plan_fingerprint` and `data_plan_fingerprint` plus any later material runtime/policy configuration. D5 does not mutate or publish `decision_id`.

---

# 12. Runtime request materialization helper

D5 must provide the pure helper D6 will use after the plugin request phase.

Conceptually:

```text
materialize_data_request(
    resolved_lane,
    resolved_binding,
    data_plan,
    dynamic_requirement,
    mode,
    market_as_of,
    resolver_knowledge_cutoff,
) -> DataRequest
```

D5 itself does not call the plugin.

## 12.1 V1 dynamic-envelope rule

For D5/D6 V1, keep this deliberately strict:

- `dynamic_requirement.concept` must be declared by the resolved binding;
- the dynamic requirement must equal the declared `DataRequirement` semantic constraints for that concept exactly;
- the plugin may choose a **subset** of its declared concept requirements for one evaluation;
- it may not weaken/strengthen requiredness, replay support, freshness, availability lag, or alignment in V1.

This is intentionally simpler than a refinement lattice. Relax only when a real model needs it and a separate contract is approved.

## 12.2 Request scope

Materialize `asset/scope` from the `ConceptDataPolicy.scope_mode`, never from plugin input.

An unrouted concept cannot be materialized; fail with an explicit DataPlan/request error.

## 12.3 Request fields

Map:

```text
DataRequirement.required
  -> DataRequest.required

DataRequirement.replay_support_required
  -> DataRequest.replay_support_required

DataRequirement.max_age_at_market_as_of
  -> DataRequest.freshness_bound

DataRequirement.max_available_lag
  -> DataRequest.max_available_lag

DataRequirement.alignment
  -> DataRequest.alignment
```

Use explicit caller-supplied:

```text
mode
market_as_of
resolver_knowledge_cutoff
```

No implicit current time.

---

# 13. Canonical DataRequest identity

Equivalent physical requests must deduplicate predictably.

Implement a small deterministic helper such as:

```text
make_data_request_key(...)
```

Use full SHA-256 or a stable readable prefix + full fingerprint. Do not use Python hash/repr.

The canonical request identity must include:

```text
lane_id
concept
asset/scope
market_as_of
mode
resolver_knowledge_cutoff
replay_support_required
freshness_bound
max_available_lag
alignment
```

Intentionally **exclude `required`** from physical request identity.

Therefore two bindings asking for the same semantic snapshot with identical constraints but one required and one optional share the same request key and physical acquisition.

Changing any actual candidate-selection constraint must change the key.

The resolver must recompute/check canonical request keys and reject a caller-supplied stale/noncanonical key.

---

# 14. Binding request batch

Use a tiny app-owned wrapper, approximately:

```text
BindingDataRequest
  binding_id
  request: DataRequest
```

Rules:

- binding ID must exist in the DataPlan/resolved lane;
- request concept/semantic constraints must match that binding's D5 envelope;
- request asset/scope must match policy materialization;
- request mode/market_as_of/knowledge cutoff must match the resolver batch;
- no duplicate identical binding/request pair;
- same physical request key across different bindings is allowed and expected.

Do not add model objects.

---

# 15. Data source fetch boundary

The source fetcher is the only D5 physical acquisition seam.

Use async semantic shape:

```text
async fetch(request: DataRequest) -> DataSnapshot | None
```

Why async here:

- later real cache/PIT/live adapters are I/O;
- D5 can test the semantic boundary using synthetic async callables without adding infrastructure;
- D5 itself does not add background loops or task pools.

The D5 resolver may process unique request keys sequentially in deterministic sorted order. Bounded parallel scheduling belongs to D9 unless separately authorized.

No sleeps, retries, backoff, timeouts, or subprocesses in D5.

Cancellation must propagate; never swallow `asyncio.CancelledError`/task cancellation as a normal source error.

---

# 16. Source candidate contract

When one source returns a non-`None` candidate:

1. value must be `DataSnapshot`;
2. `snapshot.source == DataSourceDefinition.name`;
3. `snapshot.resolved_capability == DataSourceDefinition.capability`;
4. `snapshot.concept == request.concept`;
5. `snapshot.request_key == request.request_key`;
6. validate D1 PIT rules;
7. validate D5 alignment/freshness/availability-lag/replay-support rules.

Wrong type/source/capability/concept/request identity is **source contract corruption** and must raise a D5 source-contract exception. Do not silently fall through.

A semantically well-formed candidate that is future/stale/not aligned/not replay-capable is an **ineligible candidate**, not source corruption. Record rejection and continue to the next policy-allowed source.

Examples:

```text
cache returns future observation
  -> reject candidate
  -> try PIT

cache returns stale observation
  -> reject candidate
  -> try PIT

LIVE_ONLY candidate for replay-required request
  -> reject candidate
  -> try next eligible source
```

---

# 17. Attempt evidence

Add one small immutable diagnostic contract, approximately:

```text
DataSourceAttempt
  source
  source_kind
  outcome: MISS | REJECTED | ERROR | ACCEPTED
  reason: optional stable text/code
```

No timestamps are necessary in D5 attempt evidence.

Purpose:

- prove deterministic source precedence;
- explain why cache/PIT/live fallback happened;
- make replay tests auditable.

Do not create an observability/event framework.

Source exception behavior:

- cancellation propagates;
- ordinary source exception => record `ERROR`, continue to next explicitly allowed source;
- if no later valid source succeeds, request is unavailable;
- do not retry the failing source.

---

# 18. LIVE resolution semantics

For one unique request in LIVE mode:

```text
route = DataPlan concept live_source_order
```

Attempt sources exactly in policy order.

Requirements:

- a valid cache candidate wins immediately;
- future/stale/ineligible cache candidate is rejected then next source is attempted;
- PIT may satisfy LIVE;
- at most one `live` source exists/gets attempted;
- first valid candidate wins;
- sources after first accepted candidate are not called;
- no hidden source fallback outside policy;
- no second live/scraper attempt.

If route is empty/unrouted or every allowed source misses/rejects/errors, request is unavailable.

---

# 19. REPLAY resolution semantics

For REPLAY:

```text
route = DataPlan concept replay_source_order
```

Hard requirements:

```text
only source kind pit
only LIVE_AND_REPLAY source definition
never invoke cache source
never invoke live source
never invoke scraper/live acquisition indirectly
```

Snapshot additionally requires:

```text
available_at <= resolver_knowledge_cutoff
```

A PIT row that existed in the DB today but whose historical `available_at` exceeds the simulated knowledge cutoff is rejected.

`fetched_at` may be later than the replay cutoff and remains operational provenance only.

---

# 20. Equivalent-request deduplication

Resolver input may contain requests from multiple bindings.

Within one `resolve()` call:

```text
same canonical request_key + same physical request semantics
  -> resolve once
  -> one DataSnapshot object/result
  -> reuse for every requesting binding
```

If the same request key is supplied with conflicting physical semantics, fail closed.

No persistent cache across resolver calls in D5.

No concurrent in-flight registry is necessary while D5 resolves unique keys sequentially. D9 may add bounded concurrent single-flight while preserving this identity contract.

---

# 21. Resolver output contracts

Recommended small outputs:

```text
BindingDataResolution
  binding_id
  available
  snapshots: request_key -> DataSnapshot
  missing_required_requests
  missing_optional_requests

DataResolution
  lane_id
  base_lane_revision
  data_plan_fingerprint
  mode
  market_as_of
  resolver_knowledge_cutoff
  shared_snapshots: request_key -> DataSnapshot
  unavailable_requests: request_key -> reason
  attempts: request_key -> tuple[DataSourceAttempt, ...]
  bindings: binding_id -> BindingDataResolution
```

All nested values immutable.

## 21.1 Binding availability

```text
required request unavailable
  -> only affected binding unavailable

optional request unavailable
  -> binding remains available; explicit missing optional evidence
```

A binding that submitted no requests is available from D5's data perspective.

D5 does not combine feature availability or dependency availability; D6 will compose all binding inputs.

## 21.2 Shared snapshot consistency

Follow D4 precedent:

- binding snapshot key must exist in `DataResolution.shared_snapshots`;
- binding-visible snapshot must equal/reuse the corresponding shared snapshot;
- one request cannot be both shared and unavailable;
- a present request cannot also be missing;
- every missing request must have lane-level unavailable evidence;
- binding `available` iff `missing_required_requests` is empty.

## 21.3 Cutoff consistency

Every shared snapshot must validate against the physical request that produced it.

It is acceptable to keep an immutable lane-level mapping:

```text
requests: request_key -> canonical DataRequest
```

inside `DataResolution` if that materially strengthens self-validation without creating duplication. Prefer this if needed for a trustworthy D6 boundary.

---

# 22. DataResolver

Implement an async, bounded, deterministic resolver approximately:

```text
DataResolver(
  source_catalog,
)

await resolve(
  data_plan,
  resolved_lane,
  binding_requests,
  mode,
  market_as_of,
  resolver_knowledge_cutoff,
) -> DataResolution
```

The DataPlan already carries resolved source-route identity; the resolver uses `DataSourceCatalog` to access actual fetchers and revalidates used source version/kind/capability against the plan before acquisition.

Required preflight validation:

```text
data_plan matches resolved lane
DataPlan fingerprint self-integrity already valid
all binding requests match lane/binding envelope
all request keys canonical
batch mode/cutoffs consistent
source catalog definitions match DataPlan used route metadata
```

Then:

1. group by canonical request key;
2. validate same-key physical semantics do not conflict (ignoring only binding requiredness);
3. resolve each unique request once in deterministic request-key order;
4. collect attempts/shared snapshot or unavailable reason;
5. project shared result into binding-isolated resolutions;
6. return immutable `DataResolution`.

No model callback occurs inside resolver.

---

# 23. Important D5 boundary: plugin dynamic requests

D5 must **not** execute `DecisionModelPlugin.data_requests()`.

However D5 must prove its pure envelope/materialization helper with synthetic dynamic requirements.

D6 later performs:

```text
LaneMarketView
+ binding FeatureResolution subset
+ state snapshot
+ upstream artifacts available so far as appropriate
        ↓
ModelRequestContext
        ↓
plugin.data_requests()
        ↓
validate subset against D5 BindingDataPlan
        ↓
materialize DataRequest
        ↓
D5 DataResolver
```

Do not implement this execution chain in D5.

---

# 24. Data-plan and feature-plan independence

D5 must not modify the approved D4 FeaturePlan/FeatureEngine.

External data and shared features are independent inputs:

```text
FeaturePlan fingerprint
DataPlan fingerprint
```

Neither is nested inside the other.

D6 will assemble both into binding contexts.
D8 will compose their material identities into the final authoritative lane/decision identity.

Do not create a generic “input plan” abstraction.

---

# 25. Tests — shared contract additions

Update D1/D2 compatibility tests as necessary and add focused coverage:

```text
DataRequest replay_support_required strict bool
DataRequest alignment validation
DataRequest max_available_lag non-negative timedelta
DataRequest existing explicit mode/cutoff behavior preserved
ModelSpec duplicate intrinsic data concept rejected
```

No D1 regression.

---

# 26. Tests — source catalog and policy

Cover:

```text
explicit DataSourceCatalog lookup
catalog deterministic order
catalog immutable
source duplicate name rejected
invalid source kind/capability rejected

DataPolicy concept lookup
lane_asset scope
 global scope
unknown source reference rejected
LIVE cache->pit->live order accepted
LIVE pit->cache rejected
LIVE >1 live source rejected
REPLAY PIT LIVE_AND_REPLAY accepted
REPLAY cache rejected
REPLAY live rejected
REPLAY PIT LIVE_ONLY rejected
route duplicate source rejected
empty route explicitly allowed
```

No real I/O.

---

# 27. Tests — DataPlan and identity

Synthetic resolved lane(s) with intrinsic data requirements.

Cover:

```text
per-binding exact DataRequirement preservation
requested concept union deterministic
unrouted concept explicit
unrequested policy concept does not enter fingerprint
unused source catalog addition does not alter fingerprint
policy version change alters fingerprint
used route order alters fingerprint
used source version alters fingerprint
used source capability/kind alters fingerprint
DataRequirement semantic change alters fingerprint
input ordering does not alter fingerprint
DataPlan stale/tampered policy/route/demand with old fingerprint rejected
validate_data_plan_against_lane rejects required/optional drift
validate_data_plan_against_lane rejects freshness/replay/alignment drift
```

---

# 28. Tests — request materialization and request identity

Cover:

```text
lane_asset request uses lane asset
global request uses scope="global" and no lane asset
plugin/dynamic request cannot select source
undeclared concept rejected
changed semantic constraint vs binding envelope rejected
subset of declared concepts accepted
DataRequirement -> DataRequest field mapping exact
canonical request key deterministic
required vs optional difference alone shares same physical request key
freshness/replay/alignment difference changes request key
mode/cutoff/scope change changes request key
noncanonical caller request key rejected by resolver
```

---

# 29. Tests — PIT/freshness/alignment validator

Cover at least:

```text
event_time > market_as_of rejected
represented_end_at > market_as_of rejected
available_at > resolver_knowledge_cutoff rejected
fetched_at after knowledge cutoff still allowed

exact alignment exact end accepted
exact alignment older end rejected
at_or_before older accepted
bounded_window without represented_end_at rejected
bounded_window with causal represented_end_at accepted

freshness exactly at bound accepted
freshness older than bound rejected

availability lag exactly at bound accepted
availability lag over bound rejected
available_at < effective observation end rejected when max_available_lag is requested

REPLAY rejects LIVE_ONLY
LIVE replay_support_required rejects LIVE_ONLY
LIVE non-replay-required may accept LIVE_ONLY
UNAVAILABLE snapshot never satisfies request
```

---

# 30. Tests — LIVE route behavior

Use synthetic async sources with call counters.

Cover:

```text
valid cache hit => PIT/live not called
cache miss => PIT called
cache future candidate rejected => PIT called
cache stale candidate rejected => PIT called
PIT hit => live not called
PIT miss => exactly one live source called
live valid candidate accepted
all miss => request unavailable
source ordinary exception recorded and next allowed source tried
source contract corruption fails closed
cancellation propagates
first accepted candidate stops route
attempt evidence preserves exact source order/outcome
```

No sleeps/network.

---

# 31. Tests — REPLAY route behavior

Prove strongly:

```text
REPLAY never invokes cache fetcher
REPLAY never invokes live fetcher
PIT valid historical snapshot accepted
PIT candidate available after knowledge cutoff rejected
PIT LIVE_ONLY candidate rejected
fetched_at after simulated cutoff does not invalidate otherwise historically available row
all PIT candidates unavailable => explicit unavailable request
```

Add call counters asserting forbidden source call count stays exactly zero.

---

# 32. Tests — dedup and binding isolation

Representative batch:

```text
Binding A requires OPEN_INTEREST
Binding B optionally requests identical OPEN_INTEREST
Binding C requests BTC_DOMINANCE
```

Prove:

```text
A+B same canonical key -> source called once
same shared DataSnapshot reused/equal in A and B
C resolved independently
A missing required -> A unavailable
B same missing optional -> B available
C unaffected
binding sees no unrequested snapshot
shared and unavailable sets disjoint
present and missing sets disjoint
missing request requires unavailable evidence
binding available iff no missing required request
```

Also test same key + conflicting physical request semantics fails closed.

---

# 33. Tests — no cross-lane/source leakage

If two lanes resolve the same concept but different asset/scope:

```text
BTC OPEN_INTEREST
ETH OPEN_INTEREST
```

request keys must differ and snapshots must not cross-bind.

Global scope may deduplicate only when all canonical request semantics including lane identity contract permit it. D0 says equivalent requests are shared for the same lane/as-of; D5 V1 should therefore keep lane ID in request identity and **not deduplicate across lanes**.

This keeps lane-level provenance and failure isolation simple.

---

# 34. Infrastructure and scope tests

D5 production modules may import standard library and approved decision contracts/modules.

They must not import or instantiate:

```text
redis
valkey
asyncpg
sqlalchemy
httpx
requests
aiohttp
scraper_app
ingestion_app runtime
DBPoolManager
ConfigManager
FastAPI
pandas
polars
```

No real connector/client.

Production D5 source should contain no:

```text
DecisionModelPlugin.data_requests(
DecisionModelPlugin.evaluate(
ModelOutcome
DecisionPolicy
XREAD/XADD
```

Synthetic test fetchers are allowed.

---

# 35. Validation

Use the primary repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D5 first:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_data_policy.py \
  tests/decision/test_data_resolver.py
```

Then the cumulative decision/compatibility surface because D5 touches `DataRequest` and `ModelSpec`:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Run scoped static validation:

```text
ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
python -m compileall -q src/libs/contracts/decision.py src/apps/decision_app tests/decision
git diff --check
untracked-file whitespace check where needed
D5 infrastructure/import boundary scan
```

Remove generated repository-local `__pycache__` directories after validation.

No Docker, broker, Timescale, HTTP, scraper, FastAPI, or live-market validation in D5.

---

# 36. Two-pass coder self-review

## Pass 1 — correctness / PIT / replay

Review adversarially for:

```text
model controlling physical source/scope
policy/source drift without fingerprint change
stale DataPlan accepted
same concept duplicate requirement ambiguity
noncanonical DataRequest key
required/optional accidentally changing physical request identity
cross-lane request dedup
future cache latest accepted
stale cache accepted despite freshness bound
available_at replay leakage
fetched_at incorrectly used as historical evidence
LIVE_ONLY replay leak
replay invoking cache/live source
second live acquisition attempt
source contract corruption silently falling through
source exception causing hidden retry
cancellation swallowed
duplicate physical acquisition per binding
shared snapshot mismatch in binding result
required missing not affecting availability
optional missing incorrectly affecting availability
```

## Pass 2 — simplicity / overengineering

Remove/reject:

```text
generic provider framework
source factories/discovery
persistent cache framework
retry/backoff framework
concurrency/task pool
background worker
policy inheritance/wildcards
arbitrary scope DSL
request refinement lattice
DataFrame layer
real infrastructure adapter
config loader
model execution
state machine
DecisionPolicy
publication
```

The final D5 package should look like:

```text
small explicit source/policy catalog
+ deterministic DataPlan
+ pure request materialization
+ bounded resolver pass
+ immutable resolution evidence
```

---

# 37. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d5-data-resolver-live-replay-v1.md
```

Use repository-compliant front matter and include:

```text
scope executed / explicitly not executed
files/symbols changed
DataRequest additive contract changes
ModelSpec duplicate-data-demand tightening
source catalog/policy semantics
DataPlan and data_plan_fingerprint
fingerprint self-integrity evidence
request materialization/request-key semantics
PIT/freshness/alignment semantics
LIVE route evidence
REPLAY forbidden-source evidence
request dedup evidence
binding isolation/availability evidence
source attempt evidence
validation commands + exact results
Pass 1 findings
Pass 2 findings
blockers/residual risks
```

Record explicitly:

```text
D6 will invoke plugin.data_requests(), validate exact-subset demands,
materialize D5 DataRequests, assemble DecisionContext, and execute models/state.

D8 final authoritative identity must include approved feature_plan_fingerprint
and data_plan_fingerprint plus later material runtime configuration.
```

Do not claim model execution, state/rewarm, publication, real cache/DB/scraper integration, or runtime soak parity.

Do not start D6 automatically.

Final line exactly:

```text
DECISION_APP_D5_DATA_RESOLVER_LIVE_REPLAY_READY_FOR_REVIEW
```
