---
goal: Implement the deterministic PIT-safe semantic DataPlan and bounded LIVE/REPLAY DataResolver for decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d5, data-resolver, pit, replay]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D5 semantic DataResolver LIVE/REPLAY

## Scope executed

Implemented D5 in the cumulative D0 worktree. The implementation is a small,
deterministic, infrastructure-free semantic data boundary. It does not execute
models, access external infrastructure, or mutate runtime state.

## Files and symbols changed

Added:

```text
src/apps/decision_app/data.py
tests/decision/test_data_policy.py
tests/decision/test_data_resolver.py
plans/coder-to-orchestrator-decision-app-d5-data-resolver-live-replay-v1.md
```

Updated:

```text
src/libs/contracts/decision.py
```

The D5 module contains the explicit `DataSourceDefinition` and
`DataSourceCatalog`, app-owned `ConceptDataPolicy`/`DataPolicy`, immutable
`ResolvedConceptDataRoute`/`BindingDataPlan`/`DataPlan`, pure request-key and
materialization helpers, `BindingDataRequest`, attempt evidence,
binding-isolated `BindingDataResolution`/`DataResolution`, and the bounded
async `DataResolver`.

## Contract changes

`DataRequest` now carries the runtime-materialized `replay_support_required`,
`max_available_lag`, and `alignment` constraints. `mode` remains explicit and
has no default. All booleans and duration/alignment values are strict. The
existing `DataRequirement` envelope remains semantic and physical source names
do not enter model contracts.

`ModelSpec` rejects duplicate intrinsic data concepts and normalizes the
requirement tuple deterministically. No plugin execution was added.

## Policy and source boundary

Physical sources are explicit immutable definitions with only `cache`, `pit`,
and `live` kinds. The catalog has deterministic name ordering, duplicate-name
rejection, and no discovery or factory machinery.

`DataPolicy` owns concept scope and ordered LIVE/REPLAY routes. LIVE routes are
validated as non-decreasing `cache -> pit -> live` order with at most one live
source. REPLAY routes contain only replay-safe PIT sources. Empty routes and
unrouted requested concepts remain explicit unavailable paths; there is no
implicit fallback between policy modes.

Models cannot select source names, physical keys, tables, endpoints, or scope.
`lane_asset` materializes the resolved lane asset, while `global` materializes
no asset and `scope="global"`.

## DataPlan and identity

`compile_data_plan()` resolves only concepts declared by the current lane's
`ResolvedModelBinding.effective_data_requirements`. It preserves exact
per-binding demand, records routed and unrouted concepts, resolves source
versions/kinds/capabilities, and validates the plan against the current lane
revision and binding demand before request materialization or resolution.

`data_plan_fingerprint` is a canonical SHA-256 identity over the lane/base
revision, policy name/version, per-binding requirement envelopes, requested and
unrouted concepts, route order, scope, and used source metadata. It excludes
fetcher identity, wall clock, unused sources, and unrequested policies.
`DataPlan.__post_init__` recomputes the fingerprint from normalized fields, so
policy/route/demand mutation cannot retain a stale identity. Input ordering and
unused catalog entries do not change the fingerprint.

Before D8 authoritative publication, final effective lane/decision identity
must include the approved D4 `feature_plan_fingerprint`, this D5
`data_plan_fingerprint`, and later material runtime/policy configuration. D5
does not mutate or publish `decision_id`.

## Request materialization and identity

`materialize_data_request()` is a pure D6-facing helper. It accepts only an
exact declared `DataRequirement` subset, maps semantic freshness,
availability-lag, replay and alignment constraints, and obtains asset/scope
from the resolved app policy. It never invokes a model callback.

`make_data_request_key()` uses stable canonical SHA-256 input containing lane
identity, concept, asset/scope, mode, market cutoff, resolver knowledge cutoff,
replay requirement, freshness, availability lag, and alignment. `required` is
intentionally excluded so required and optional bindings can share one physical
request/result while retaining binding-local availability semantics.

## PIT, freshness, alignment and replay semantics

Candidate validation enforces:

```text
event_time <= market_as_of
represented_end_at <= market_as_of, when supplied
available_at <= resolver_knowledge_cutoff
```

`fetched_at` is operational provenance only. `exact`, `at_or_before`, and
`bounded_window` alignment are explicit. Freshness uses market time minus the
effective observation end; availability lag uses `available_at` minus that
same end. `UNAVAILABLE` snapshots cannot satisfy requests.

REPLAY, and any LIVE request marked `replay_support_required`, require
`LIVE_AND_REPLAY` capability. A replay route can invoke only replay-safe PIT
sources. A delayed LIVE snapshot can be accepted when availability is after
market time but within the explicit resolver knowledge cutoff.

## LIVE/REPLAY resolver evidence

`DataResolver` validates the plan, lane, binding envelopes, request identity,
scope, cutoffs, and source-catalog route metadata before any fetcher call. It
resolves unique request keys once in sorted order. LIVE follows the configured
cache/PIT/live route and stops at the first valid candidate; an ineligible
future/stale/alignment/freshness/replay candidate is recorded as `REJECTED` and
falls through. At most one configured live source can be attempted.

REPLAY never invokes cache or live sources. Source contract corruption
(wrong type, source, capability, concept, or request identity) raises a
`DataSourceContractError` rather than silently falling through. Ordinary source
exceptions are recorded as `ERROR` and move to the next configured source;
cancellation propagates and is never converted to a miss. There are no retries,
backoff loops, sleeps, background tasks, or persistent resolver cache.

`DataSourceAttempt` preserves deterministic source outcome evidence without
timestamps. `DataResolution` retains canonical requests, shared snapshots,
unavailable reasons, attempt sequences, and binding projections. A valid shared
snapshot is reused for every requesting binding; missing required data makes
only that binding unavailable, while missing optional data is explicit and
keeps the binding available. Binding-visible snapshots cannot be unrequested,
shared/unavailable simultaneously, or different from the shared snapshot.

Lane identity is included in request keys, so D5 does not deduplicate physical
requests across lanes. Equivalent requests within one lane deduplicate even
when requiredness differs.

## Remediation closure

The resolver remediation makes physical acquisition independent of binding
ordering. Deduplicated source requests are materialized with
`required=False`; required/optional semantics remain in the original
binding-local requests and are retained in `BindingDataResolution` as disjoint
required and optional request-key partitions. Thus the source sees one
canonical physical request regardless of which binding is listed first, while
required missingness still controls only that binding's availability.

`BindingDataResolution` now rejects overlapping, incomplete, foreign, or
contradictory required/optional partitions and missingness labels.
`DataResolution` rejects shared snapshots without exactly one final matching
accepted attempt, accepted attempts for unavailable requests, multiple
accepted attempts, and unavailable results with contradictory accepted evidence.

Source kind and replay capability are independent. A LIVE-only cache may be
used as a LIVE acquisition route, while a replay-safe cache may satisfy a
replay-required LIVE request. REPLAY still permits only `pit` sources with
`LIVE_AND_REPLAY` capability. The source route and resolver tests cover both
axes explicitly.

## Explicitly not executed

No D5 implementation was added for:

```text
DecisionModelPlugin.data_requests() invocation
DecisionModelPlugin.evaluate() invocation
model instantiation or dependency execution
DecisionContext assembly
model state, state commit, causal rewarm, or DecisionPolicy
PriceRelay, publication, Valkey/Redis, Timescale, cache clients, HTTP, scraper
FastAPI, Docker, AssetRuntime, input consumers, background workers, scheduling
retry/backoff frameworks, persistent resolver caches, feature changes/DAGs
real model adapters, decision configuration, or downstream application changes
```

D6 owns exact-subset dynamic requests, complete context assembly, model and
dependency execution, and state transitions/rewarm. D8 owns composition of the
approved feature and data plan fingerprints into authoritative publication
identity.

## Validation

Using the primary repository interpreter and Ruff installation:

```text
pytest -q tests/decision/test_data_policy.py tests/decision/test_data_resolver.py
32 passed

pytest -q tests/decision tests/commons/test_model_runtime_contract.py tests/models/test_strategy_model_v2.py
157 passed

ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
passed

ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
24 files already formatted

python -m compileall -q src/libs/contracts/decision.py src/apps/decision_app tests/decision
passed

git diff --check
passed
```

The D5 production module import/boundary audit found no infrastructure client,
database pool, HTTP client, scraper runtime, downstream app, model callback,
model outcome, policy execution, or transport command dependency. Only standard
library code and approved D1/D2 decision contracts/planner/identity modules are
used.

Repository-local bytecode caches generated by test/compile validation were
removed. No Docker, broker, database, network, scraper, FastAPI, or live-market
validation was run, as required by D5.

## Pass 1 — correctness / PIT / replay

Reviewed and tested source precedence, cache/PIT/live fallback, one-live-source
boundedness, source exceptions and cancellation, contract corruption,
replay-forbidden source calls, late replay availability, delayed LIVE data,
PIT/freshness/alignment rules, required-vs-optional request identity,
input-order-independent physical deduplication, binding-local availability,
shared snapshot reuse, required/optional evidence integrity, attempt/result
consistency, independent source kind/capability, unrouted concepts, stale
plan/demand validation, and canonical request keys.

## Pass 2 — simplicity / scope

No provider framework, source discovery, persistent cache, retry system,
concurrency pool, policy inheritance, arbitrary scope DSL, request-refinement
lattice, dataframe layer, infrastructure adapter, model execution, state
machine, publication path, or runtime worker was added. D5 remains a static
policy/plan boundary plus one sequential bounded resolver pass.

## Residual risks / carry-forward

Physical adapters remain future runtime integrations and are represented only
by synthetic async fetcher seams. D6 must validate plugin dynamic requests as an
exact subset of the approved binding envelope before calling this resolver.
The resolver is intentionally sequential; bounded concurrent single-flight is
deferred to a later runtime phase. D8 must include both feature and data plan
fingerprints in final authoritative identity before publication.

DECISION_APP_D5_DATA_RESOLVER_LIVE_REPLAY_READY_FOR_REVIEW
