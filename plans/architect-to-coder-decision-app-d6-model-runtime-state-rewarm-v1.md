---
goal: Implement the offline decision_app model runtime, explicit state transaction boundary, dependency execution, and causal rewarm without starting policy/publication/runtime infrastructure
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d6, model-runtime, state, rewarm]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D6 model runtime + state + causal rewarm

## 1. Objective

Implement the first complete **offline model-execution core** for `decision_app` on top of approved D0–D5.

D6 connects:

```text
D3 LaneMarketView
      +
D4 FeaturePlan / FeatureEngine
      +
D5 DataPlan / DataResolver
      +
D2 same-lane dependency topology
      +
explicit runtime plugin instances
      +
D1 ModelRequestContext / DecisionContext / ModelOutcome
      ↓
one bounded plugin request phase
      ↓
one bounded D5 data-resolution batch
      ↓
dependency-ordered model evaluation
      ↓
PreparedLaneExecution
      +
proposed state transitions
```

D6 must additionally implement:

```text
explicit in-memory state ownership
prepared-state transaction semantics
explicit commit/abort API for future D8
causal state rewarm using the same bars -> features -> REPLAY data -> dependency models -> stateful-model chain
```

D6 **does not** implement DecisionPolicy, authoritative publication, LaneCommitWatermark advancement, PriceRelay, Valkey, Timescale adapters, FastAPI, Docker, AssetRuntime, service loops, or real model migration.

Expected terminal status:

```text
DECISION_APP_D6_MODEL_RUNTIME_STATE_REWARM_READY_FOR_REVIEW
```

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not commit, merge, push, switch branches, reset, restore, or start D7 automatically.

---

# 2. Approved upstream contracts are source of truth

Preserve the approved behavior of:

```text
D0 architecture
D1 semantic contracts
D2 ResolvedLanePlan / execution_order / dependency wiring
D3 LaneMarketView / TimeframeGrid / causal BarStore
D4 FeaturePlan / FeatureResolution / feature_plan_fingerprint
D5 DataPlan / DataResolution / data_plan_fingerprint
```

Do not reopen or redesign D0–D5 merely for D6 convenience.

Important frozen rules:

1. models are in-process plugins, not services;
2. plugin-visible contexts contain no infrastructure clients;
3. same-lane dependencies are static and topologically ordered by D2;
4. shared features are binding-isolated at the model-facing boundary;
5. external data is resolved through D5 only;
6. one bounded data-request phase occurs before model evaluation;
7. plugin evaluation performs no recursive I/O;
8. plugin state is explicit through `state_snapshot` / `proposed_next_state`;
9. proposed state is not committed merely because `evaluate()` succeeded;
10. stateful missed transitions cannot continue from stale state;
11. rewarm uses durable PIT-safe REPLAY data and suppresses historical publication;
12. final authoritative publication identity is still deferred to D8.

---

# 3. Critical D6 sequencing clarification — preserve one bounded request phase

`ModelRequestContext` contains an `upstream_artifacts` field, but D0/D1/D5 also freeze:

```text
one bounded request phase before model evaluation
```

D6 V1 must resolve this without recursive I/O.

## 3.1 Request phase

For every otherwise eligible binding:

```text
LaneMarketView
+ that binding's FeatureResolution subset
+ frozen committed state snapshot (stateful only)
+ upstream_artifacts = {}
      ↓
plugin.data_requests(...)
```

**Current same-cutoff upstream artifacts are intentionally empty during `data_requests()` in D6 V1.**

Then, after every eligible binding has had at most one request callback:

```text
all BindingDataRequest values
      ↓
one DataResolver.resolve(...) batch
```

Only after this single data batch completes may model evaluation begin.

## 3.2 Evaluation phase

During dependency-ordered `evaluate()` calls, `DecisionContext.upstream_artifacts` contains the already-evaluated current-cutoff dependency artifacts keyed by the consumer's **dependency slot name**.

Do not recall `data_requests()` after an upstream artifact appears.
Do not interleave source I/O with model evaluation.
Do not create a recursive request/evaluation loop.

This is a V1 simplification and must be covered by tests. D7 real model adapters must conform to it.

---

# 4. Scope and preferred files

Keep D6 small and explicit.

Preferred production files:

```text
src/apps/decision_app/runtime_plugins.py
    explicit runtime plugin factory catalog

src/apps/decision_app/state.py
    lane execution identity
    in-memory state records/store
    prepared transitions
    commit/abort semantics

src/apps/decision_app/model_runtime.py
    request-phase context assembly
    D5 request materialization/resolution
    topological model execution
    output validation
    PreparedLaneExecution
    causal rewarm
```

Small additive changes to:

```text
src/apps/decision_app/contracts.py
src/libs/contracts/decision.py
```

are allowed only if a concrete D6 invariant cannot be represented cleanly with existing approved contracts. Prefer app-owned D6 types over modifying shared plugin contracts.

Preferred focused tests:

```text
tests/decision/test_runtime_plugins.py
tests/decision/test_model_runtime.py
tests/decision/test_state_rewarm.py
```

Do not create more modules/tests without an actual ownership conflict.

---

# 5. Explicit non-goals

D6 must not implement or modify:

```text
DecisionPolicy logic
DecisionPolicyResult production
TradeSignal publication
signals:* writes
price_update:* writes
Valkey/Redis consumers or publishers
Timescale repository adapters
real cache/DB/scraper adapters
FastAPI/control plane
Docker/Compose
configs/decision
AssetRuntime
input stream reader
InputReadCursor mutation
LaneCommitWatermark advancement
PriceRelay
background loops/workers
CPU thread/process pool
retry/backoff framework
persistent model-state storage
state checkpoint framework
snapshot journal/outbox
generic workflow/DAG engine
actors
hot graph mutation
live training
real model adapters
signal_app / strategy_app / risk_app / execution_app changes
```

D7 owns representative real model adapters.
D8 owns DecisionPolicy, final effective identity, downstream publication, timestamp/risk compatibility, and the actual policy/publication authorization that causes D6 state commit.
D9 owns live runtime/infrastructure.

---

# 6. Runtime plugin registry — separate from D2 static `PluginCatalog`

Do **not** turn D2 `PluginCatalog` into a mutable service locator or factory registry.

D2's specs-only catalog remains the static planning source.

Add a separate explicit runtime registry, approximately:

```text
RuntimePluginDefinition
  plugin_name
  plugin_version
  factory

RuntimePluginCatalog
  exact (name, version) lookup
  instantiate(binding.parameters) -> DecisionModelPlugin
```

Recommended factory semantic shape:

```text
factory(parameters: immutable Mapping[str, Any]) -> DecisionModelPlugin
```

No import scanning or entry-point discovery.
No module auto-discovery.
No infrastructure arguments.
No async factory.

## 6.1 Runtime instance validation

When one runtime is constructed, instantiate exactly one plugin instance per resolved binding.

Validate:

```text
instance structurally conforms to DecisionModelPlugin
instance.spec == ResolvedModelBinding.model_spec
instance.spec.name/version == binding plugin name/version
factory is called once per binding during runtime construction, not once per evaluation
```

Prefer distinct plugin instances per binding; reject accidental reuse of the same mutable instance across two binding IDs in one lane.

The plugin object itself must not become the state store. D6 passes explicit `state_snapshot` on every callback.

Callable/factory repr or object address must not enter any identity/fingerprint.

---

# 7. D6 execution identity for state ownership

Do not create another speculative hash unless necessary.

Use one small immutable identity carrying the already-approved material components, approximately:

```text
LaneExecutionIdentity
  lane_id
  effective_lane_revision
  feature_plan_fingerprint
  data_plan_fingerprint
```

Every D6 state store, prepared execution, state transition, commit receipt, and rewarm result must carry/validate this exact identity.

This fixes the D2 carry-forward requirement: state is not reusable merely because `binding_id` stayed the same when upstream composition/input policy changed.

State from:

```text
lane revision A + feature plan X + data plan Y
```

must never be read/committed by:

```text
lane revision A + feature plan X2 + data plan Y
```

or any other material identity change.

Do not claim this is the final D8 publication identity. D8 still composes final effective decision identity.

---

# 8. In-memory state store — explicit and lane-scoped

Keep V1 state ownership simple.

Recommended small types:

```text
BindingRuntimeHealth
  WARMING | LIVE | DEGRADED | INVALID

BindingRuntimeState
  binding_id
  health
  committed_market_as_of: optional UTC datetime
  committed_state: ModelState
  last_failure_reason: optional stable string

LaneStateStore
  LaneExecutionIdentity
  exact stateful binding IDs
  binding_id -> BindingRuntimeState
```

The store is in-memory only.
No persistence/checkpoints/database.
No locks/concurrency framework in D6.

## 8.1 Initialization

When a lane runtime is constructed:

- stateless bindings do not receive state records;
- every configured stateful binding starts `WARMING` with no committed cutoff/state;
- stateful LIVE execution is forbidden until causal rewarm initializes it.

This matches D0 startup reconstruction semantics.

## 8.2 State snapshots supplied to plugins

For a LIVE stateful binding:

```text
state_snapshot = freeze_model_state(committed_state)
```

The plugin cannot mutate store-owned state through the supplied object.

A stateful binding whose health is:

```text
WARMING
DEGRADED
INVALID
```

must not receive its old committed state for a later LIVE transition. It is unavailable until successful rewarm.

---

# 9. Dynamic plugin data requirements

D6 invokes `plugin.data_requests()` exactly once per otherwise eligible binding per execution step.

Validate callback output before materialization:

```text
must be a Sequence, not string/bytes/generator-only surprise
all values are DataRequirement
concepts unique
returned set is a subset of the binding's approved D5 BindingDataPlan envelope
every returned requirement equals its declared envelope value exactly
no requiredness/replay/freshness/availability/alignment drift
```

The plugin may return an empty subset.

A declared `required=True` requirement does **not** mean it must be requested every evaluation; it means that **if dynamically requested**, failure to resolve it makes that binding unavailable.

No dynamic strengthening/weakening in V1.

### Failure classification

```text
callback raises
callback returns invalid type
callback returns undeclared/drifted requirement
  -> binding INVALID for this execution
  -> stateful binding health INVALID
```

A dynamically requested concept that is declared but currently has no D5 route is ordinary input unavailability:

```text
required unrouted -> binding unavailable / stateful DEGRADED
optional unrouted -> omit optional value; binding may continue
```

Do not treat operator route absence as plugin contract corruption.

---

# 10. One D5 resolution batch

Collect every materializable `BindingDataRequest` from the request phase and call:

```text
await DataResolver.resolve(...)
```

exactly once per lane execution step.

Pass explicit:

```text
mode
market_as_of
resolver_knowledge_cutoff
```

LIVE normal evaluation uses `mode="LIVE"`.
Causal rewarm uses `mode="REPLAY"` only.

No model evaluation may occur before this resolver call finishes.

Bindings that requested no materializable data still receive their D5 data perspective from the resulting `DataResolution` plus D6's explicit unrouted/invalid-request evidence.

Cancellation must propagate.

If D5 reports a normal missing required request, only affected bindings are unavailable.
If D5 raises source/plan contract corruption for the whole batch, D6 must fail closed and ensure stateful bindings cannot silently proceed to a later trigger from stale state.

Do not retry the batch.

---

# 11. Binding eligibility before `evaluate()`

A binding may execute only if all are true:

```text
plugin request phase valid
required shared features available
required dynamically requested data available
stateful state health == LIVE (normal LIVE mode)
all configured upstream dependency bindings executed successfully at same market_as_of
all required upstream artifacts are present and valid
```

Expected normal unavailability:

```text
required feature missing/disabled
required data missing/unrouted
upstream dependency unavailable
stateful binding requires rewarm
```

must skip that binding without executing its plugin.

Independent bindings later in topological order continue when their own inputs do not depend on the failed binding.

---

# 12. Dependency-ordered model execution

Use D2 `ResolvedLanePlan.execution_order` directly.

Do not rebuild/re-sort the DAG in D6.

For each binding ID in execution order:

1. resolve exact `ResolvedModelBinding`;
2. check binding eligibility;
3. gather current-cutoff upstream artifacts from already-executed provider bindings;
4. map them by the consumer dependency slot name;
5. build complete `DecisionContext`;
6. call `plugin.evaluate(context, state_snapshot)` exactly once;
7. validate `ModelOutcome`;
8. retain one outcome/artifact for dependency reuse and later D8 policy.

An upstream binding is evaluated at most once per lane/as-of.

No recursive evaluate calls.
No generic graph executor.

---

# 13. Context assembly

## 13.1 `ModelRequestContext`

Use only causal/binding-visible values:

```text
identity from ResolvedLanePlan / binding
market_as_of from LaneMarketView
current direct/projected decision_bar
LaneMarketView.causal_bar_views
that binding's D4 feature snapshots only
upstream_artifacts = {} in D6 V1 request phase
stable provenance containing at least lane revision + feature/data plan fingerprints + mode
```

No `decision_ready_at`.
No external data yet.

## 13.2 `DecisionContext`

At evaluation time reuse the same base semantics plus:

```text
that binding's D5 visible DataSnapshot mapping only
current same-cutoff upstream dependency artifacts keyed by dependency slot
```

Do not expose lane-level shared feature/data mappings to every model.

A binding must never receive another binding's unrequested feature or data snapshot.

---

# 14. ModelOutcome runtime validation

D1 validates intrinsic shape; D6 must validate the output against the concrete resolved binding/lane.

Require:

```text
outcome is ModelOutcome
artifact.binding_id == binding.binding_id
artifact.lane_id == lane.lane_id
artifact.asset == lane.asset
artifact.decision_timeframe == lane.decision_timeframe
artifact.trigger_timeframe == lane.trigger_timeframe
artifact.market_as_of == LaneMarketView.market_as_of
artifact.artifact_type == binding.model_spec.produces_artifact_type
```

Decision rules:

```text
analytical output_kind -> outcome.decision must be None
predictive -> decision may be present or absent
decision_capable -> decision may be present or absent
```

If decision exists, D1 identity/time invariants remain mandatory.

State rules:

```text
stateless spec -> proposed_next_state must be None
stateful spec -> proposed_next_state is a frozen proposal value; None is allowed as an explicit semantic state value
```

Do not infer policy meaning from model scores/directions.

Runtime output contract violation:

```text
wrong artifact type
wrong binding/lane/asset/time identity
analytical model emits decision
stateless model emits proposed state
wrong output type
```

=> binding INVALID; stateful binding health INVALID; dependent bindings are blocked, independent bindings continue.

---

# 15. Binding execution result

Add one small immutable execution result, exact name may vary:

```text
BindingExecutionResult
  binding_id
  status: EXECUTED | UNAVAILABLE | BLOCKED | INVALID
  outcome: optional ModelOutcome
  reason: optional stable string
  blocked_dependency_ids: tuple[str, ...]
```

Invariants:

- `EXECUTED` requires exactly one valid outcome;
- non-executed statuses must not carry an outcome;
- blocked dependencies belong to the resolved lane;
- reason strings are stable semantic codes/text, not exception repr with addresses;
- result identity matches lane/as-of through the contained outcome where present.

Keep status vocabulary small. Do not create a workflow state machine.

---

# 16. Prepared state transitions and LIVE transaction boundary

A successful stateful `evaluate()` returns a **proposal**, not a committed state transition.

Represent it explicitly, approximately:

```text
PreparedStateTransition
  binding_id
  market_as_of
  base_state_record: exact immutable BindingRuntimeState used for evaluation
  proposed_next_state
```

Then return a lane-level immutable object:

```text
PreparedLaneExecution
  LaneExecutionIdentity
  market_as_of
  mode = LIVE
  FeatureResolution
  DataResolution
  binding_results
  stateful_binding_ids
  prepared_state_transitions
  state_commit_eligible
  state_commit_blockers
```

`PreparedLaneExecution` is **not** a DecisionPolicy result and is **not** published.

## 16.1 `state_commit_eligible`

For D6 V1:

```text
True when every configured stateful binding executed successfully and has a prepared transition for this cutoff
```

Stateless binding failure does not itself make state transitions invalid; D8 policy later decides whether the lane can finalize.

If any configured stateful binding is WARMING/DEGRADED/INVALID/unavailable/blocked/failed:

```text
state_commit_eligible = False
```

No partial state batch commit.

This preserves lane-level transactional state progression.

---

# 17. Explicit commit API for future D8 — D6 does not call it automatically

Implement an explicit method such as:

```text
commit_prepared(
    prepared_execution,
    disposition: CommitDisposition  # published | no_signal
) -> StateCommitReceipt
```

D6 tests may call this method with synthetic authorization, but normal `prepare_live()` must never call it.

Before mutation validate atomically:

```text
prepared identity == state store identity
prepared mode == LIVE
state_commit_eligible == True
all prepared stateful binding IDs exactly match configured stateful binding IDs
current state record for every binding == transition.base_state_record
current committed cutoff < prepared market_as_of
```

Only after **all** checks pass:

```text
committed_state = proposed_next_state
committed_market_as_of = prepared.market_as_of
health = LIVE
clear failure reason
```

for every stateful binding as one in-memory batch.

No LaneCommitWatermark mutation in D6.

Return a small immutable receipt containing at least:

```text
LaneExecutionIdentity
market_as_of
disposition
committed_binding_ids
```

D8 will later use successful publication/no-signal handling + this receipt to advance the lane watermark.

## 17.1 Stale prepared execution

If state changed after preparation, committing an older prepared object must fail closed with no partial mutation.

Do not add a generic transaction manager/versioning framework. Exact base-record comparison is sufficient for D6 single-process semantics.

---

# 18. Explicit abort/finalization-failure API

D0 requires publication/policy failure to leave old committed state intact **and** prevent stale-state continuation.

Expose a small method such as:

```text
abort_prepared(prepared_execution, reason)
```

Future D8 will call it after policy/publication failure/conflict.

Behavior:

- never commit proposed state;
- leave committed state/cutoff unchanged;
- mark every stateful binding that had a prepared transition `DEGRADED`;
- retain already `INVALID` state for stateful bindings that failed during execution;
- require causal rewarm before next LIVE evaluation;
- reject stale/mismatched prepared identity rather than clobbering newer state.

D6 does not simulate publication failure itself; tests invoke the API directly.

---

# 19. Immediate stateful failure semantics during LIVE prepare

If a stateful binding misses a required transition during LIVE preparation, update its health immediately so a later trigger cannot reuse old state.

Freeze classification:

### `DEGRADED`

Expected causal/input failure:

```text
required feature unavailable
required dynamically requested data unavailable/unrouted
dependency unavailable/blocked
prepared execution aborted by later policy/publication failure
```

### `INVALID`

Plugin/runtime contract failure:

```text
data_requests callback exception
invalid dynamic requirement output
evaluate callback exception
invalid ModelOutcome identity/type/state semantics
```

### `WARMING`

No initialized state yet; causal rewarm required.

The old committed state may remain stored as reconstruction baseline, but LIVE evaluation must not use it while health is not `LIVE`.

Independent stateless bindings continue where causally possible.

Cancellation should propagate. If a LIVE execution step has already begun and is cancelled, ensure stateful bindings cannot silently continue from a missed transition on the next trigger; use a simple DEGRADED marking rule rather than swallowing cancellation.

---

# 20. No double LIVE state transition

For stateful bindings, reject a LIVE evaluation cutoff that is not strictly after the committed state cutoff.

After a successful explicit commit at `T`:

```text
prepare_live(... market_as_of=T)
prepare_live(... market_as_of<T)
```

must not execute a second state transition.

Idempotent publication retry after state commit belongs to D8/D9 and must use stored policy/publication evidence, not rerun stateful model evaluation.

Stateless-only lane repeated offline evaluation may remain deterministic, but do not weaken stateful cutoff safety.

---

# 21. Causal rewarm — same execution chain, publication suppressed

D6 must implement the approved causal rewarm path.

Recommended input:

```text
RewarmStep
  lane_market_view: LaneMarketView
  resolver_knowledge_cutoff: UTC datetime
```

and:

```text
await rewarm(steps: Sequence[RewarmStep]) -> RewarmResult
```

REPLAY mode is fixed internally; callers must not choose LIVE for rewarm.

## 21.1 Rewarm target

Rewarm all configured stateful bindings and their direct/transitive D2 dependency ancestors.

Compute this subset from the already-resolved same-lane dependency graph without introducing a new DAG framework.

Independent bindings outside every stateful ancestor closure do not need to execute during state reconstruction.

## 21.2 Baseline

If the lane has a committed state baseline:

- all stateful binding records should share one committed cutoff because D6 commits them atomically;
- preserve those states as the initial shadow state;
- first replay step must be exactly the next trigger interval after the baseline cutoff.

If no stateful binding has ever been initialized:

- start shadow state from `None` for each stateful binding;
- first supplied step is the caller-selected initialization boundary;
- D6 then requires strict trigger-timeframe continuity for every subsequent step.

D6 does not invent historical inception or checkpoint discovery. D9/D7 will ensure the supplied warmup horizon is sufficient for concrete models.

Reject inconsistent per-binding committed cutoffs as state corruption.

## 21.3 Step continuity

Use approved `TimeframeGrid` and the lane's `trigger_timeframe` duration.

Require:

```text
strictly increasing market_as_of
no duplicate step
successive step market_as_of == previous + trigger_duration
```

If a committed baseline exists:

```text
first step == baseline + trigger_duration
```

Every LaneMarketView identity/timeframe/trigger mode must match the resolved lane.

Do not silently skip a missed state transition.

## 21.4 Same chain per step

For each replay step:

```text
LaneMarketView
  -> FeatureEngine.compute(...)
  -> plugin.data_requests(... shadow state; no current upstream artifacts)
  -> one DataResolver.resolve(... mode=REPLAY)
  -> dependency-ordered evaluate() over stateful closure
  -> apply successful proposed state to shadow state only
  -> next replay step
```

Decisions may be returned by plugins internally but are ignored/suppressed as historical outputs.
No DecisionPolicy.
No publication.
No LaneCommitWatermark advancement.

D5 must prove REPLAY external data are `LIVE_AND_REPLAY`; D6 does not add another source path.

## 21.5 Atomic install

Real `LaneStateStore` must remain unchanged during replay.

If any required stateful reconstruction path fails at any step:

```text
rewarm fails
real store unchanged
existing WARMING/DEGRADED/INVALID health preserved
```

Only after **every replay step succeeds**:

```text
atomically install final shadow states
committed_market_as_of = final step market_as_of
health = LIVE
```

for all configured stateful bindings.

This reconstruction install is explicitly publication-suppressed historical state reconstruction, not a D8 live commit.

---

# 22. Rewarm result

Keep output small:

```text
RewarmResult
  LaneExecutionIdentity
  starting_market_as_of: optional
  final_market_as_of
  replay_step_count
  reconstructed_binding_ids
```

No historical decisions/signals in this result.
No model output journal.
No checkpoint payload.

---

# 23. Feature/data plan and state identity validation

Runtime construction must validate:

```text
FeaturePlan matches ResolvedLanePlan
DataPlan matches ResolvedLanePlan
FeaturePlan.base_lane_revision == lane.effective_lane_revision
DataPlan.base_lane_revision == lane.effective_lane_revision
state store LaneExecutionIdentity matches all three
plugin runtime catalog covers exactly every resolved binding name/version needed
```

Do not accept stale FeaturePlan/DataPlan objects because binding IDs look correct.

Prepared execution, commit, abort, and rewarm must all reject identity mismatch.

---

# 24. Failure isolation

Representative behavior:

```text
A (independent stateless) succeeds
B (stateless provider) missing required data
C depends on B
D (independent stateless) succeeds
```

Expected:

```text
A EXECUTED
B UNAVAILABLE
C BLOCKED
D EXECUTED
```

For stateful bindings:

```text
stateful B missing required input -> B DEGRADED
stateful C blocked by B -> C DEGRADED
```

No stale state transition for B/C.

Plugin/output contract failure uses INVALID rather than normal unavailable.

Do not abort all independent model execution merely because one binding failed, unless a shared pre-evaluation component such as FeatureEngine/DataResolver raises a lane-level contract-corruption exception that prevents a trustworthy resolution object.

---

# 25. Required runtime tests — plugin registry

Cover at minimum:

```text
explicit runtime factory registration
exact name/version lookup
catalog immutable
duplicate registration rejected
unknown runtime plugin rejected
factory called once per binding
same factory may create separate instances for separate bindings
same instance reused across two binding IDs rejected
plugin structural protocol required
plugin.spec must equal ResolvedModelBinding.model_spec
factory exception fails runtime construction
no import scanning/discovery
```

Synthetic plugins only.

---

# 26. Required runtime tests — request phase

Cover:

```text
data_requests called exactly once for eligible binding
request context contains binding-isolated D4 features
request context carries frozen committed state for LIVE stateful binding
request context current upstream_artifacts is empty even for dependent binding
no evaluate() happens before all request callbacks and one D5 batch complete
returned dynamic requirement subset accepted
empty dynamic subset accepted
undeclared concept rejected
requiredness drift rejected
replay/freshness/availability/alignment drift rejected
duplicate returned concept rejected
request callback exception -> binding INVALID
required unrouted dynamic request -> binding unavailable
optional unrouted dynamic request -> binding may execute without it
```

Instrument synthetic callbacks/call sequence explicitly.

---

# 27. Required runtime tests — execution and dependency topology

Representative graph:

```text
Boundary -> Regression -> DecisionModel
IndependentModel
```

Prove:

```text
D2 execution_order used exactly
provider evaluated once
consumer gets provider artifact under declared dependency slot
upstream artifact market_as_of identical
independent binding continues when unrelated binding unavailable
missing provider result blocks dependent without calling dependent evaluate
provider exception/invalid output blocks dependent
no recursive evaluation
```

Output validation tests:

```text
wrong artifact binding_id
wrong lane_id
wrong asset
wrong timeframe
wrong market_as_of
wrong artifact_type
analytical plugin emits decision
stateless plugin emits proposed state
non-ModelOutcome callback return
```

Each must fail the affected binding closed.

---

# 28. Required runtime tests — binding isolation

Prove:

```text
Binding A sees only A feature snapshots
Binding A sees only A requested external snapshots
Binding B cannot see A-only feature/data
consumer sees only configured upstream dependency artifacts
independent model receives no dependency artifacts
```

Do not expose lane-level shared FeatureResolution/DataResolution mappings directly to a plugin.

---

# 29. Required state transaction tests

Use a synthetic stateful plugin whose state increments causally.

Prove:

```text
new stateful binding starts WARMING
LIVE prepare before rewarm does not call plugin
successful rewarm makes state LIVE
LIVE evaluate receives frozen committed state
ModelOutcome proposal does not mutate store
repeated prepare before commit sees same committed state
explicit commit(published) advances state
explicit commit(no_signal) advances state
LaneCommitWatermark is not mutated by D6
stale prepared commit rejected with zero partial updates
stateful double evaluation after committed same cutoff rejected
abort_prepared leaves old committed state/cutoff unchanged
abort_prepared marks transition-bearing stateful binding DEGRADED
DEGRADED/INVALID state is not passed to next LIVE evaluation
feature/data fingerprint identity change cannot reuse old store
```

Also test at least two stateful bindings in one lane to prove batch commit is all-or-nothing.

---

# 30. Required rewarm tests

Synthetic causal sequence, preferably 3–5 trigger steps.

Cover:

```text
startup rewarm from None shadow state
rewarm from existing committed baseline
trigger-step gap rejected
duplicate/out-of-order step rejected
wrong lane/view identity rejected
REPLAY mode used for every D5 request
LIVE/cache-only acquisition never used by rewarm
upstream dependency executed each replay step
stateful plugin receives previous shadow state step-by-step
plugin decisions are not published/exposed as authoritative output
failed middle replay step leaves real state store byte/structurally unchanged
successful rewarm installs only final state after all steps
successful rewarm sets all configured stateful bindings LIVE
reconstructed cutoff == final replay step
```

Include one stateful binding with a stateless upstream dependency.

No real I/O.

---

# 31. State failure classification tests

Prove:

```text
required feature missing -> stateful DEGRADED
required data missing -> stateful DEGRADED
dependency unavailable -> stateful DEGRADED
data_requests exception -> stateful INVALID
evaluate exception -> stateful INVALID
invalid outcome -> stateful INVALID
publication/policy abort simulation -> stateful DEGRADED
```

After any non-LIVE health, a later `prepare_live()` must not call that plugin until rewarm succeeds.

---

# 32. No hidden plugin state dependency

The runtime passes explicit state and must not create an alternate state callback/lifecycle framework.

Production D6 must not add:

```text
plugin.on_start
plugin.on_stop
plugin.on_checkpoint
plugin.on_disconnect
plugin.restore
plugin.save_state
```

A plugin object may exist for the lane lifetime, but all causal model state required for correctness must flow through the approved explicit state snapshot/proposal contract.

This purity is partly a code-review responsibility; D7 real adapters must be audited for hidden mutable state.

---

# 33. Infrastructure/scope guard

D6 production modules may use standard library and approved decision_app/D1–D5 modules.

They must not import or instantiate:

```text
redis
valkey
asyncpg
sqlalchemy
httpx
requests
aiohttp
FastAPI
ConfigManager
DBPoolManager
scraper_app
ingestion runtime
risk_app
execution_app
signal_app
strategy_app
pandas
polars
```

No XREAD/XADD.
No DB query.
No network.
No Docker mutation.

`DataResolver` synthetic source fetchers in tests are allowed.

---

# 34. Simplicity / overengineering guard

Reject or remove if introduced:

```text
general workflow engine
new graph library
actor model
state-machine framework
checkpoint framework
persistent event journal
state serialization framework
plugin discovery framework
DI/service-container framework
thread/process executor
per-model process
per-binding feature/data cache
background task scheduler
retry framework
hot reload
```

Expected production design is roughly:

```text
explicit factories
+ one lane executor
+ one small in-memory state store
+ immutable prepared execution/state transition contracts
+ causal replay loop
```

---

# 35. Validation

Use the primary repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D6 first, for example:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_runtime_plugins.py \
  tests/decision/test_model_runtime.py \
  tests/decision/test_state_rewarm.py
```

Then cumulative decision/compatibility because D6 consumes all D1–D5 contracts:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then:

```bash
ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
git diff --check
```

Run an import/scope scan proving no forbidden infrastructure/downstream imports or D7/D8 behavior.

Remove generated repo-local `__pycache__` directories after validation.

Do not run Docker, broker, database, external HTTP, or live-market tests in D6.

---

# 36. Two-pass coder self-review

## Pass 1 — causality / correctness / state safety

Review specifically:

```text
one request phase before evaluate
no same-cutoff upstream artifact in data_requests
D5 dynamic envelope exact-subset validation
binding feature/data isolation
D2 topological execution
artifact identity/type validation
state snapshots immutable
proposed state remains uncommitted
commit all-or-nothing
abort leaves old state and forces rewarm
state identity includes D2+D4+D5 material identity
no stale state continuation
rewarm step continuity
REPLAY-only external data during rewarm
real state unchanged until rewarm success
historical decisions suppressed
```

## Pass 2 — simplicity / scope

Review specifically:

```text
no AssetRuntime
no DecisionPolicy
no publication
no LaneCommitWatermark mutation
no infrastructure
no checkpoint framework
no generic DAG/workflow
no hidden lifecycle callback system
no real model adapters
no unnecessary abstraction
```

Remove speculative code before handoff.

---

# 37. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d6-model-runtime-state-rewarm-v1.md
```

Use required YAML front matter:

```yaml
---
goal: Implement D6 offline model runtime, explicit state transaction boundary, dependency execution, and causal rewarm
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d6, model-runtime, state, rewarm]
---
```

Record exact evidence:

```text
files/symbols changed
runtime plugin catalog behavior
request-phase sequencing evidence
D5 exact-subset/materialization evidence
topological execution/dependency reuse evidence
model-output fail-closed evidence
binding isolation evidence
state-store identity evidence
prepared commit/abort evidence
causal rewarm evidence
no-publication/LaneCommitWatermark evidence
focused test count
cumulative compatibility count
Ruff/format/compile/diff/import results
Pass 1 findings
Pass 2 findings
residual risks
```

Explicitly record:

```text
D6 does not publish or advance LaneCommitWatermark.
D8 must authorize commit only after DecisionPolicy + successful idempotent publication or final no-signal disposition.
D8 final identity must compose approved D2 lane identity + D4 feature_plan_fingerprint + D5 data_plan_fingerprint plus any later material policy/runtime identity.
D7 real model adapters were not started.
```

Do not claim full live runtime/infrastructure integration.
Do not start D7 automatically.

Final line exactly:

```text
DECISION_APP_D6_MODEL_RUNTIME_STATE_REWARM_READY_FOR_REVIEW
```
