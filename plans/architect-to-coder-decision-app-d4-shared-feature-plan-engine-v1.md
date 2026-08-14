---
goal: Implement the deterministic demand-driven shared FeaturePlan and offline FeatureEngine for decision_app
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d4, features, feature-plan]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D4 shared FeaturePlan + offline FeatureEngine

## 1. Objective

Implement the **smallest demand-driven shared feature layer** on top of the approved D0-D3 architecture.

D4 converts model-owned semantic shared-feature demand plus operator feature policy into a deterministic static `FeaturePlan`, extends the shared BarStore capacity floor only where enabled feature lookback requires it, and computes approved shared features **once per lane / `market_as_of`** from causal market state.

Conceptually:

```text
ResolvedLanePlan
+ model FeatureRequirement values
+ explicit FeatureCatalog
+ explicit operator FeaturePolicy
        ↓
static FeaturePlan
        ↓
feature history/capacity requirements
        ↓
LaneMarketView + shared BarStore
        ↓
FeatureEngine.compute(...)
        ↓
FeatureResolution
  shared feature snapshots computed once
  + binding-specific visible subsets
  + explicit unavailable required/optional evidence
```

D4 performs **no model evaluation, no external-data resolution, no dependency execution, no state transition, no policy decision, and no infrastructure I/O**.

Expected terminal status:

```text
DECISION_APP_D4_SHARED_FEATURE_ENGINE_READY_FOR_REVIEW
```

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not start from plain `main`; D0-D3 artifacts in this worktree are the source of truth.

---

## 2. Approved source of truth

Read and preserve:

```text
docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
docs/architecture/decision_app/decisions.md
src/libs/contracts/decision.py
src/apps/decision_app/contracts.py
src/apps/decision_app/identity.py
src/apps/decision_app/catalog.py
src/apps/decision_app/planner.py
src/apps/decision_app/market_state.py
src/apps/decision_app/readiness.py
src/apps/decision_app/view.py
plans/coder-to-orchestrator-decision-app-d3-causal-market-state-v1.md
```

Approved programme state:

```text
D0 architecture                         APPROVED
D1 semantic contracts                  APPROVED
D2 static composition planner          APPROVED
D3 causal market state / lane views    APPROVED
D4 shared feature layer                CURRENT PACKAGE
```

Hard inherited decisions:

1. Shared features are computed only when demanded by active model bindings **and** allowed by operator policy.
2. There is no universal always-on feature vector or internal feature stream.
3. Model-private deterministic transforms remain inside model plugins and are **not** moved into the shared engine merely for convenience.
4. A disabled/unavailable **required** shared feature makes the affected binding unavailable; an optional feature is simply absent with explicit evidence.
5. Feature computation is causal and keyed by `market_as_of`.
6. Shared computation must not cause feature/history leakage between otherwise independent bindings or lanes.
7. BarStore remains canonical closed bars only. Feature computation never writes bars or features back into canonical market state.
8. Projected decision bars remain ephemeral D3 `LaneMarketView.decision_bar` values.
9. D4 stays synchronous/offline and infrastructure-free.
10. Keep the 8 GiB / 4-core target: bounded exact lookbacks, compute-on-demand, no DataFrame copies, no per-model feature caches.

---

# 3. Scope

## 3.1 Preferred production files

Keep D4 small. Prefer:

```text
src/libs/contracts/decision.py
    additive shared-feature requirement/snapshot contracts only

src/apps/decision_app/features.py
    FeatureHistoryRequirement
    SharedFeatureDefinition
    FeatureCatalog
    FeaturePolicy
    BindingFeaturePlan
    FeaturePlan
    FeatureResolution / BindingFeatureResolution
    static plan + feature capacity helpers

src/apps/decision_app/feature_engine.py
    SharedFeatureContext
    FeatureEngine
    pure synchronous feature computation
```

`src/apps/decision_app/market_state.py` may receive **one small public capacity-merge helper** if useful. Do not redesign D3.

`planner.py` / `contracts.py` may be changed only for the minimal `FeatureRequirement` type migration required by D4.

Do not create a feature package hierarchy unless a demonstrated ownership problem makes the two-file layout impossible.

## 3.2 Focused tests

Prefer at most:

```text
tests/decision/test_features.py
tests/decision/test_feature_engine.py
```

Update existing D1/D2/D3 tests only where the additive `FeatureRequirement` contract replaces current raw strings.

No real quant-model migration in D4.

---

# 4. Explicit non-goals

D4 must not implement:

```text
DecisionModelPlugin instantiation
DecisionModelPlugin.data_requests()
DecisionModelPlugin.evaluate()
model dependency execution
model state / proposed state commit
state rewarm runtime
DataResolver / DataPolicy
scraper / HTTP / DB / Timescale
Valkey / stream reads / stream publication
DecisionPolicy
TradeSignal publication
PriceRelay
FastAPI/control plane
Docker/Compose
configs/decision loader
AssetRuntime
async workers/task scheduling
feature-to-feature dependency DAG
incremental/rolling feature engine
persistent feature cache/store
feature stream/pubsub
Pandas/Polars feature frames
universal FeatureVector transport
real model adapters/migrations
cross-lane feature dependencies
cross-asset feature dependencies
training/optimization
```

No new dependency in `pyproject.toml`.

Do not commit, merge, push, switch branches, reset, or restore.

Do not start D5 automatically.

---

# 5. Required additive plugin-facing feature contracts

The current D1 contract represents `ModelSpec.intrinsic_feature_requirements` as bare strings. D4 must distinguish required from optional shared feature demand, so a small additive contract refinement is required.

## 5.1 `FeatureRequirement`

Add to `src/libs/contracts/decision.py`:

```text
FeatureRequirement
  name: str
  required: bool = True
```

Rules:

- `name` is a non-empty semantic feature identifier;
- `required` must be a strict bool;
- no lookback, timeframe, implementation class, physical source, cache key, or calculator belongs here;
- model demand owns **what semantic feature is needed**, not how it is computed.

Change:

```text
ModelSpec.intrinsic_feature_requirements
```

from:

```text
tuple[str, ...]
```

to:

```text
tuple[FeatureRequirement, ...]
```

`ModelSpec` must:

- validate every item is `FeatureRequirement`;
- reject duplicate feature names within one model spec, including duplicates that disagree on `required`;
- preserve deterministic tuple order supplied by the plugin or normalize by feature name; whichever is chosen, tests must prove planner identity does not depend on accidental input ordering.

`ResolvedModelBinding.effective_feature_requirements` must use the same typed tuple.

Do **not** add model-private feature declarations to the shared contract in D4. Private transforms remain plugin implementation details.

## 5.2 `FeatureSnapshot`

Add an immutable plugin-visible feature value contract approximately:

```text
FeatureSnapshot
  name
  version
  market_as_of
  value
  provenance
```

Required semantics:

- `name` / `version` non-empty;
- `market_as_of` explicit timezone-aware UTC;
- `value` deep-frozen using the approved D1 semantic-value vocabulary;
- `provenance` immutable string-keyed semantic mapping;
- no `decision_ready_at`;
- no wall-clock timestamp used as causal identity;
- no infrastructure handles.

Update `DecisionContext.shared_features` and `ModelRequestContext.shared_features` to be structurally capable of carrying:

```text
feature_name -> FeatureSnapshot
```

without recursively converting the typed snapshot into an untyped object.

The mapping key must equal `FeatureSnapshot.name`.

Do not weaken D1 immutability to accomplish this.

---

# 6. App-owned shared feature definition

A model requests semantic feature `X`. `decision_app` owns the versioned implementation contract for `X`.

Implement an immutable app-owned definition such as:

```text
SharedFeatureDefinition
  name
  version
  history_requirements
  calculator
```

The definition is code-owned and explicitly registered. It is not discovered dynamically.

## 6.1 `FeatureHistoryRequirement`

Shared feature definitions may require bounded canonical closed-bar history.

Use one small representation with exactly three source modes:

```text
FeatureHistoryRequirement
  source: decision | trigger | fixed
  bars: positive int
  timeframe: optional str
```

Rules:

```text
source=decision
  -> resolve to lane.decision_timeframe
  -> timeframe must be None

source=trigger
  -> resolve to lane.trigger_timeframe
  -> timeframe must be None

source=fixed
  -> timeframe must be a non-empty explicit timeframe
```

`bars` must be a strict positive integer. A feature requiring no historical bars uses an empty requirements tuple; do not encode zero.

This is the entire D4 feature-input geometry. Do not introduce a general query DSL, sessions, resampling, windows in seconds, or feature dependencies.

If two requirements for one feature resolve to the same timeframe for a concrete lane, use the maximum bar count rather than duplicate/copy the history.

## 6.2 Calculator boundary

The calculator must be a synchronous callable that receives only a D4 `SharedFeatureContext` and returns one D1-supported semantic value.

Conceptually:

```text
calculator(context: SharedFeatureContext) -> semantic value
```

A calculator must not receive:

```text
BarStore
DB/Valkey/HTTP clients
DataResolver
scheduler/executor
mutable runtime state
other feature outputs
```

No feature-to-feature dependencies in V1/D4.

The framework cannot mathematically prove calculator purity, but D4 production modules must expose no infrastructure path and tests must use deterministic synthetic calculators.

The definition's `name + version + resolved history requirements` are authoritative feature implementation identity for D4. Never hash a Python callable repr/address.

---

# 7. Explicit immutable `FeatureCatalog`

Implement an explicit catalog of `SharedFeatureDefinition` values.

Required behavior:

- one active definition per semantic feature name in D4;
- duplicate feature name registration fails;
- exact lookup by name;
- unknown lookup has a small clear exception;
- deterministic sorted iteration by feature name;
- catalog backing state immutable after construction;
- no global mutable registry;
- no package scanning/entry points/import discovery;
- no calculator factory machinery.

A definition version may change between deployments; that version must change D4 plan fingerprint/provenance.

Do not support multiple simultaneously selectable versions for one feature name in D4. If that becomes necessary later, it requires an explicit contract instead of implicit selection.

---

# 8. Operator `FeaturePolicy`

Implement a small immutable operator policy data contract, not a config loader.

Recommended shape:

```text
FeaturePolicy
  name
  version
  allowed_features: tuple[str, ...]
```

Semantics:

- allowlist is explicit and fail-closed;
- a requested feature is enabled only if its semantic name is in `allowed_features` **and** a definition exists;
- allowed-but-unrequested features are never computed;
- duplicate allowlist entries invalid or normalized deterministically;
- policy names in the allowlist must resolve in the supplied `FeatureCatalog`; reject unknown policy entries to catch operator typos;
- an empty allowlist is valid and disables all shared features;
- this object has no YAML/file loading in D4.

Do not add precedence layers, glob patterns, asset inheritance, wildcard names, or per-feature parameter bags in D4.

If a feature requires tunable behavior, that behavior belongs in the versioned feature definition for this phase. General operator feature parameters can be added only when a real use case requires them.

---

# 9. Static `FeaturePlan`

Compile one immutable FeaturePlan from:

```text
ResolvedLanePlan
+ FeatureCatalog
+ FeaturePolicy
```

The plan must preserve **binding-level demand semantics** while deduplicating lane-level computation.

Recommended shape:

```text
BindingFeaturePlan
  binding_id
  required_features
  optional_features
  enabled_features
  disabled_required_features
  disabled_optional_features
  undefined_required_features
  undefined_optional_features
  statically_available: bool

FeaturePlan
  lane_id
  base_lane_revision
  feature_policy_name
  feature_policy_version
  requested_shared_features
  operator_allowed_features
  effective_shared_features
  disabled_features
  undefined_features
  feature_versions
  bindings: binding_id -> BindingFeaturePlan
  feature_plan_fingerprint
```

Exact names may be simplified if equivalent semantics remain explicit.

## 9.1 Demand union

For each resolved binding:

- read `effective_feature_requirements`;
- split into required/optional semantic names;
- preserve only that binding's demand in `BindingFeaturePlan`.

Across the lane:

```text
effective_shared_features
  = union(requested features that are operator-allowed and catalog-defined)
```

Compute each effective semantic feature once per lane/as-of even if several bindings request it.

## 9.2 Disabled and undefined behavior

For a binding:

```text
required + disabled by policy
  -> binding statically unavailable

required + no catalog definition
  -> binding statically unavailable

optional + disabled
  -> feature absent; binding remains statically available

optional + undefined
  -> feature absent; binding remains statically available
```

Do not silently approximate or substitute another feature.

Do not fail the whole lane merely because one independent binding has a disabled required feature. Preserve per-binding evidence for D6.

## 9.3 No all-lane visibility

`FeaturePlan` may deduplicate compute, but later binding views must remain isolated:

```text
Binding A requests F1
Binding B requests F2
```

After shared computation:

```text
A sees F1 only
B sees F2 only
```

Neither receives every feature computed for the lane.

This is a hard compositionality invariant analogous to D3 lane-local history visibility.

---

# 10. Feature-plan deterministic fingerprint

D4 does **not** publish authoritative decisions, so do not rewrite the D2 identity graph speculatively.

However feature implementation/policy changes are material behavioral changes. Compute one deterministic full-SHA256:

```text
feature_plan_fingerprint
```

Include canonical semantic values at least:

```text
lane_id
D2 base effective_lane_revision
feature policy name/version
operator allowlist
per-binding required/optional feature demands
resolved active feature name/version
resolved feature history requirement semantics
static disabled/undefined results
```

Requirements:

- input mapping/list insertion order cannot affect fingerprint;
- feature definition version change changes fingerprint;
- feature history requirement change changes fingerprint;
- operator allowlist change changes fingerprint;
- required/optional demand change changes fingerprint;
- unrelated catalog definition that is neither requested nor effective must **not** change the lane feature-plan fingerprint;
- callable object identity/repr must never enter the fingerprint.

Use existing D1 canonical SHA-256 helpers rather than a second serialization framework.

### Identity carry-forward

Record explicitly in the coder handoff:

> Before D8 authoritative publication, the final effective decision/lane identity must incorporate the approved `feature_plan_fingerprint` (and later material DataPolicy/runtime configuration). D4 itself does not mutate or publish `decision_id`.

Do not claim D2 `effective_lane_revision` is the final publication identity after D4 configuration exists.

---

# 11. Feature history resolution

Implement a pure resolver from:

```text
SharedFeatureDefinition
+ ResolvedLanePlan
+ TimeframeGrid
```

to exact bounded canonical history requirements:

```text
MarketSeriesKey -> bar_count
```

For each `FeatureHistoryRequirement`:

- resolve decision/trigger/fixed timeframe;
- require timeframe exists in `TimeframeGrid`;
- construct the same canonical `MarketSeriesKey` identity as D3 using asset/venue/instrument;
- merge duplicate resolved timeframe requirements by maximum count.

Feature history is always closed canonical history. The current projected/closed `LaneMarketView.decision_bar` is a separate explicit input to the feature calculator.

Do not synthesize an HTF history inside D4.

---

# 12. Extend shared BarStore capacity without changing model-visible D3 history

D3 base capacity is already compiled from lane timing and model warmup. D4 adds only effective shared-feature lookback capacity.

Add helpers approximately:

```text
compile_feature_bar_store_capacities(
    resolved_decision_plan,
    feature_plans,
    feature_catalog,
    timeframe_grid,
) -> FrozenMapping[MarketSeriesKey, int]

merge_bar_store_capacities(
    base_capacities,
    feature_capacities,
) -> FrozenMapping[MarketSeriesKey, int]
```

Rules:

- only `effective_shared_features` contribute feature capacity;
- disabled/undefined/unrequested features contribute zero;
- capacity per shared series is maximum required, never sum;
- feature lookback may increase the physical shared BarStore capacity;
- **it must not change `LaneMarketRequirements` or `LaneMarketView` visible history**;
- D3 `DecisionViewBuilder` must continue limiting canonical histories to D3 lane requirements;
- feature calculator histories are separately sliced to the exact feature definition requirement.

Required regression:

```text
Lane A model requires 1 × 1h market warmup
Lane B/shared feature requires 20 × 1h
physical BarStore capacity = 20
Lane A LaneMarketView still exposes 1 × 1h
feature calculator receives exactly its declared 20 × 1h
```

No per-feature/per-model BarStore instance.

---

# 13. `SharedFeatureContext`

A shared calculator receives an immutable exact input context, not BarStore.

Recommended shape:

```text
SharedFeatureContext
  lane_id
  asset
  venue
  instrument_id
  market_as_of
  decision_timeframe
  trigger_timeframe
  decision_bar: CausalBarView
  decision_bar_closed: bool
  histories: timeframe -> exact tuple[CausalBarView, ...]
  observed_cutoffs: timeframe -> datetime
```

Invariants:

- identity/time fields match the input `LaneMarketView`;
- `decision_bar` is exactly the D3 direct/projected bar and remains causal;
- histories contain canonical closed bars only;
- every history bar `market_as_of <= context.market_as_of`;
- each history is exactly bounded to the feature definition's resolved count;
- required recent history is contiguous under the current continuous-UTC contract;
- bars validate against `TimeframeGrid` duration/alignment;
- observed cutoff equals the actual final supplied bar cutoff for each history;
- nested values immutable;
- no shared features or external data inside this context (prevents feature DAGs/recursive resolution).

If a definition requires no history, `histories` may be empty and the feature may operate on `decision_bar` only.

---

# 14. Feature readiness / unavailable semantics

The D3 `LaneReadiness` is market-layer readiness only. D4 must not mutate that contract to pretend feature readiness already existed in D3.

The FeatureEngine must explicitly classify expected feature unavailability.

For each effective feature at one `market_as_of`:

```text
history count insufficient
latest expected canonical cutoff missing
recent history gap
    -> feature unavailable for this evaluation
```

Do not invoke the calculator with partial history.

Malformed canonical geometry is contract corruption and should fail with the existing D3 geometry error rather than be downgraded to normal feature unavailability.

Static disabled/undefined features are already known from `FeaturePlan` and must not be computed.

A deterministic calculator exception or invalid output is a `FeatureComputationError`, not a silent optional absence. Preserve feature name/version in the error.

Do not implement retries/fallbacks.

---

# 15. `FeatureEngine`

Implement a synchronous/offline engine approximately:

```text
FeatureEngine(
  feature_catalog,
  bar_store,
  timeframe_grid,
)

compute(
  feature_plan,
  resolved_lane,
  lane_market_view,
) -> FeatureResolution
```

Required validation before compute:

```text
feature_plan.lane_id == resolved_lane.lane_id
lane_market_view.lane_id == resolved_lane.lane_id
asset/venue/instrument identity matches
market_as_of is explicit UTC
lane_market_view timing/timeframes match resolved lane
feature plan base lane revision matches resolved lane revision
```

No implicit current time.

## 15.1 Once-per-lane/as-of computation

Within one `compute()` call:

- iterate `effective_shared_features` once in deterministic feature-name order;
- build one exact `SharedFeatureContext` per feature;
- invoke that feature calculator once;
- create one immutable `FeatureSnapshot`;
- reuse that snapshot for every binding requesting the feature.

Do not compute once per binding.

No persistent cache is required in D4. The caller will retain/reuse the one `FeatureResolution` during later D6 binding execution. Avoid an incremental cache engine until evidence requires one.

## 15.2 Output contract

Use immutable data approximately:

```text
BindingFeatureResolution
  binding_id
  available
  features: feature_name -> FeatureSnapshot
  missing_required_features
  missing_optional_features

FeatureResolution
  lane_id
  base_lane_revision
  feature_plan_fingerprint
  market_as_of
  shared_features: feature_name -> FeatureSnapshot
  unavailable_features: feature_name -> reason
  bindings: binding_id -> BindingFeatureResolution
```

The lane-level `shared_features` mapping is internal shared computation evidence.

The **binding resolution mapping is the model-facing boundary** and must contain only that binding's declared enabled feature subset.

For a statically disabled required feature, the binding is unavailable even if another binding computes a feature with a similar name.

For runtime missing history of a required enabled feature, affected bindings are unavailable. Bindings that do not require that feature remain available.

For optional missing feature, omit it and record `missing_optional_features` without making binding unavailable.

---

# 16. Feature value/provenance

Every computed `FeatureSnapshot` should record deterministic provenance sufficient for later replay/debugging without turning D4 into an evidence framework.

At minimum provenance should include semantic values such as:

```text
feature_name
feature_version
market_as_of
resolved history cutoffs/counts by timeframe
projected_or_closed_decision_bar indicator when useful
```

Do not include unstable object repr, memory addresses, wall-clock computation time, or callable repr.

`FeatureSnapshot.market_as_of` must equal the lane view `market_as_of` even when its history inputs close earlier at their expected canonical cutoffs.

---

# 17. Projected lane semantics

D4 must support the approved D3 projected decision bar without manufacturing future data.

For a projected 4h lane triggered at 1m:

```text
market_as_of = 10:00
LaneMarketView.decision_bar
  08:00 -> 12:00 bucket
  market_as_of = 10:00
  closed = False
```

A shared feature may:

- inspect that projected `decision_bar` explicitly;
- request canonical 1m/4h/fixed history through its declared history requirements.

Canonical history resolution still uses D3 `expected_closed_cutoff(tf, market_as_of)`.

At 10:00:

```text
4h canonical history latest expected cutoff = 08:00
```

At 12:00:

```text
4h canonical history latest expected cutoff = 12:00
```

D4 must not aggregate or substitute a closed 4h candle at the boundary.

---

# 18. Determinism and compositionality acceptance

D4 must prove all of these:

## 18.1 Input-order determinism

Permuting:

```text
binding order
feature requirement order
FeatureCatalog registration order
FeaturePolicy allowlist order
lane order when compiling capacities
```

must not change semantic results/fingerprints.

## 18.2 Unrelated feature/catalog isolation

Adding an unrequested feature definition to the catalog must not change:

```text
FeaturePlan.effective_shared_features
feature_plan_fingerprint
computed snapshots
binding-visible feature mappings
```

## 18.3 Unrelated binding isolation

Adding another binding that requests a new feature may add shared compute/capacity, but must not change the feature set visible to an existing independent binding.

## 18.4 Shared compute dedupe

Two bindings requesting the same feature produce one calculator invocation and the exact same immutable `FeatureSnapshot` value/identity reused in both binding resolutions.

## 18.5 No history leakage

A feature requiring 20 bars gets 20 bars even if BarStore retains 200.

A binding's D3 `LaneMarketView` remains at its D3-required history length even if D4 raises physical capacity to 200.

---

# 19. Failure behavior

Expected static policy situations are represented as plan/resolution evidence, not exceptions:

```text
requested required feature disabled
requested optional feature disabled
requested required feature undefined
requested optional feature undefined
insufficient causal history
missing current canonical cutoff
history gap
```

Programmer/contract corruption fails explicitly:

```text
invalid FeatureRequirement
invalid FeatureHistoryRequirement
unknown feature in operator allowlist
invalid/duplicate catalog registration
lane/feature-plan identity mismatch
malformed canonical bar geometry
calculator raises
calculator returns unsupported mutable/non-finite semantic value
FeatureSnapshot identity mismatch
```

Do not catch broad exceptions and turn code defects into optional absence.

---

# 20. Tests — contract migration

Update D1/D2 tests for typed `FeatureRequirement`.

Prove:

```text
FeatureRequirement name non-empty
required strict bool
duplicate ModelSpec feature names rejected
ResolvedModelBinding effective feature requirements typed/immutable
FeatureSnapshot UTC-only
FeatureSnapshot value/provenance deeply immutable
FeatureSnapshot key/name consistency when placed in model context
DecisionContext shared feature mapping cannot be mutated
```

No infrastructure imports in plugin-facing contracts.

---

# 21. Tests — catalog / policy / FeaturePlan

Use synthetic definitions only.

Catalog:

```text
exact semantic-name lookup
stable sorted iteration
duplicate definition rejected
unknown lookup rejected
immutable backing state
```

Policy:

```text
explicit empty allowlist valid
allowlist order irrelevant
unknown allowed feature rejected
allowed but unrequested feature not effective
```

Plan:

```text
required+allowed+defined -> enabled
optional+allowed+defined -> enabled
required+disabled -> binding statically unavailable
optional+disabled -> binding remains available
required+undefined -> binding statically unavailable
optional+undefined -> binding remains available
same feature requested by two bindings -> one effective feature
unrelated binding feature not visible to first binding
```

Fingerprint:

```text
same semantics different ordering -> same fingerprint
feature definition version change -> different fingerprint
history requirement change -> different fingerprint
policy allowlist change -> different fingerprint
required/optional demand change -> different fingerprint
unrequested catalog addition -> unchanged fingerprint
no callable repr/address enters fingerprint
```

---

# 22. Tests — history resolution and capacity

Cover:

```text
decision timeframe source resolves correctly
trigger timeframe source resolves correctly
fixed timeframe source resolves correctly
unknown fixed timeframe fails
invalid source/timeframe combination fails
same resolved timeframe uses max lookback
feature with no history requirement valid
```

Capacity:

```text
effective feature lookback raises capacity
disabled feature does not raise capacity
undefined feature does not raise capacity
unrequested allowed feature does not raise capacity
same shared series uses max across features/lanes, not sum
base D3 capacity merged by max
feature capacity never reduces D3 capacity
D3 LaneMarketView visible history unchanged by feature capacity
```

---

# 23. Tests — FeatureEngine causal computation

Synthetic calculators should be tiny deterministic functions such as:

```text
last_close
mean_close over exact N closed bars
range from decision_bar
```

Do not add real TA indicators.

Prove:

```text
same requested feature computed exactly once for multiple bindings
FeatureSnapshot market_as_of equals LaneMarketView market_as_of
calculator receives exact declared bounded history
future retained bars excluded by market_as_of
latest canonical cutoff must match expected cutoff
insufficient history -> feature unavailable
recent history gap -> feature unavailable
malformed canonical geometry -> explicit geometry error
projected decision_bar remains closed=False and causal
canonical HTF history at projected cutoff does not include future bucket
calculator output deeply immutable
unsupported mutable output rejected
non-finite numeric output rejected
calculator exception wrapped/identified as FeatureComputationError
repeated pure compute on same inputs yields equal semantic results
```

Binding resolution:

```text
binding A requests F1 only -> receives F1 only
binding B requests F1+F2 -> receives F1+F2
same F1 snapshot reused
missing required F2 -> B unavailable, A can remain available
missing optional F2 -> B remains available with explicit optional absence
```

---

# 24. Boundary tests

D4 production modules must import no:

```text
redis / valkey
asyncpg
httpx / requests
FastAPI
scraper_app
ingestion runtime/repository
DBPoolManager
pandas / polars
strategy_app
signal_app
risk_app
execution_app
```

No production D4 call to:

```text
DecisionModelPlugin.data_requests
DecisionModelPlugin.evaluate
ModelOutcome
DataResolver
BarStore.append during feature computation
```

No async runtime loops.

No file/config/network access.

---

# 25. Validation

Use the primary repository interpreter:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D4 tests first, approximately:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_features.py \
  tests/decision/test_feature_engine.py
```

Then all decision tests plus established compatibility surfaces:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Because D4 changes `ModelSpec.intrinsic_feature_requirements`, inspect any additional direct constructors outside `tests/decision` that fail import/collection and update only the minimal compatible test/contract construction necessary. Do not migrate old runtime behavior.

Run scoped static checks on all touched D0-D4 Python modules/tests:

```text
ruff check
ruff format --check
compileall
git diff --check
untracked-file whitespace checks where necessary
infrastructure-import boundary scan
```

Remove generated `__pycache__` / `.pyc` artifacts created by validation from the worktree before handoff.

No Docker, Valkey, Timescale, browser, network, FastAPI, or live-market validation in D4.

---

# 26. Two-pass coder self-review

## Pass 1 — correctness / PIT / determinism

Review adversarially for:

```text
required vs optional feature ambiguity
feature definition/policy bypass
unknown policy typo silently accepted
feature computed when not requested
same feature computed once per binding instead of once per lane/as-of
binding receiving another binding's feature
feature lookback leaking into D3 model-visible history
feature calculator receiving more bars than declared
future bar leakage
wrong expected canonical cutoff
projected market_as_of replaced by future bucket end
canonical HTF synthesized in D4
history gap accepted
malformed geometry downgraded to ordinary unavailability
unstable callable repr included in fingerprint
feature version/policy change not reflected in fingerprint
unrequested catalog change altering fingerprint
mutable FeatureSnapshot payload/provenance
```

If D4 reveals a genuine D0-D3 contradiction, stop with:

```text
DECISION_APP_D4_BLOCKED_ARCHITECTURE_CONFLICT
```

instead of silently redesigning prior approved contracts.

## Pass 2 — simplicity / overengineering

Remove or reject:

```text
feature DAGs
feature-to-feature dependencies
incremental rolling engines
persistent caches/stores
feature publication streams
DataFrames
technical-indicator framework
factory/discovery frameworks
config loader hierarchy
async workers
thread pools
runtime scheduling
feature parameter DSL
glob/wildcard policy
cross-lane/cross-asset feature plumbing
real model-specific features
premature performance optimizations
```

The final D4 package should look like a small explicit catalog + static plan + exact causal compute pass.

---

# 27. Coder handoff

Update/create:

```text
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Use repository-compliant YAML front matter and include:

```text
scope executed / explicitly not executed
files and symbols changed
FeatureRequirement / FeatureSnapshot contract migration
FeatureCatalog behavior
FeaturePolicy behavior
FeaturePlan static demand/availability behavior
feature_plan_fingerprint evidence
history requirement resolution
BarStore capacity extension/merge evidence
D3 history-visibility isolation evidence
FeatureEngine once-per-lane/as-of evidence
binding-specific feature isolation evidence
PIT/projected-view evidence
failure/unavailability semantics
validation commands + exact results
Pass 1 findings
Pass 2 findings
blockers/residual risks
```

Explicit residual carry-forward:

```text
D5 will add external DataResolver only.
D6 will assemble complete per-binding DecisionContext and execute models/state.
Before authoritative publication, final effective identity must include the approved D4 feature_plan_fingerprint.
```

Do not claim model execution, DataResolver, state, dependency execution, policy, publication, or runtime integration.

Final line exactly:

```text
DECISION_APP_D4_SHARED_FEATURE_ENGINE_READY_FOR_REVIEW
```
