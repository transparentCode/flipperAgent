---
goal: Implement the offline decision_app model runtime, explicit state transaction boundary, dependency execution, and causal rewarm without starting policy/publication/runtime infrastructure
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d6, model-runtime, state, rewarm]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — decision_app D6 model runtime, state transactions and causal rewarm

## Scope executed

Implemented D6 in the cumulative D0 worktree as a small, synchronous-plugin,
offline execution core. The runtime connects the approved D2–D5 contracts but
does not add policy, publication, infrastructure, or service orchestration.

## Files added

- src/apps/decision_app/runtime_plugins.py
- src/apps/decision_app/state.py
- src/apps/decision_app/model_runtime.py
- tests/decision/test_runtime_plugins.py
- tests/decision/test_model_runtime.py
- tests/decision/test_state_rewarm.py
- this coder-to-orchestrator handoff

No D1–D5 production contracts were redesigned. The runtime receives the
approved D3 TimeframeGrid explicitly so rewarm continuity uses configured
timeframe duration rather than caller-supplied bar geometry.

## Runtime plugin boundary

RuntimePluginCatalog is separate from the D2 specification catalog. It is an
explicit immutable exact name/version factory catalog:

- duplicate registrations fail;
- unknown versions fail closed;
- factories receive only immutable binding parameters;
- each resolved binding is instantiated once at runtime construction;
- a plugin must structurally satisfy DecisionModelPlugin and its spec must
  equal the resolved binding spec;
- the same plugin object cannot be reused for two binding slots.

There is no discovery, service locator, import scan, model process, or runtime
infrastructure dependency.

## Request and evaluation sequencing

For each execution step, eligible bindings receive one synchronous
data_requests callback with:

- LaneMarketView;
- the binding-local feature subset;
- committed state for a LIVE stateful binding;
- no current upstream artifacts.

All materialized requests are passed to exactly one D5 DataResolver.resolve
batch before any model evaluation. Dynamic requirements are checked against the
binding's exact approved envelope; undeclared, duplicate, or drifted demand is
INVALID. Missing routes are ordinary required/optional unavailability.

Evaluation follows D2 ResolvedLanePlan.execution_order directly. A provider is
evaluated once, its artifact is retained once, and each dependent receives only
its dependency-slot-mapped upstream artifacts. Independent bindings continue
when another dependency chain is unavailable or invalid.

Feature and data visibility remains binding-local. Models receive no database,
Valkey, HTTP, scraper, or other infrastructure object.

## Output validation and failure classification

Every ModelOutcome is checked against its concrete binding and lane for:

- binding_id;
- lane_id;
- asset;
- decision timeframe;
- trigger timeframe;
- market_as_of;
- artifact type.

Analytical plugins cannot emit decisions; stateless plugins cannot propose
state. Contract violations produce INVALID; required feature/data absence or
dependency failure produces UNAVAILABLE/BLOCKED. Initialized stateful bindings
are marked DEGRADED or INVALID immediately as appropriate, so old state cannot
silently continue after a missed transition.

Feature-resolution and whole-batch data-resolution failures also degrade
initialized stateful bindings before propagating. Cancellation propagates and
does not become a successful execution.

## State identity and transaction boundary

LaneExecutionIdentity contains the material D2–D5 state inputs:

- lane_id;
- effective_lane_revision;
- feature_plan_fingerprint;
- data_plan_fingerprint.

The identity is carried by the state store, prepared execution, prepared state
transitions, commit receipt, and rewarm result. A state store with a different
identity cannot be reused.

LaneStateStore starts every stateful binding as WARMING; stateless bindings
have no state record. BindingRuntimeState freezes opaque plugin state before
storage or callback delivery.

prepare_live never commits state. Stateful outcomes become immutable
PreparedStateTransition values containing the exact base record, execution
identity, and proposed state. commit_prepared validates identity, all
stateful transitions, exact base-record equality, and strict cutoff advancement
before applying one atomic in-memory batch. Both published and no_signal
dispositions advance state through the explicit API. abort_prepared discards
proposals, preserves the committed state/cutoff, and marks transition-bearing
initialized stateful bindings DEGRADED so rewarm is mandatory.

Prepared execution self-validates its stateful result, transition, and blocker
sets; no partial or contradictory prepared contract can be exported.

No LaneCommitWatermark mutation occurs in D6.

## Causal rewarm

rewarm accepts a sequence of immutable RewarmStep values and internally uses
mode=REPLAY only. Each step repeats the approved causal chain:

LaneMarketView -> FeatureEngine -> plugin.data_requests with no current
upstream artifacts -> one D5 REPLAY resolution batch -> D2 dependency-order
evaluation -> shadow proposed-state application.

Only stateful bindings and their transitive dependency ancestors execute during
rewarm. Historical decisions are never published. Replay-safe D5 source mode
is explicitly covered by tests.

The supplied trigger steps must be contiguous using the approved TimeframeGrid
duration. A committed baseline requires the first replay cutoff to be exactly
the next trigger interval; no state transition may be silently skipped.

The real store is unchanged while replay runs. If any step fails, real records
remain unchanged. Only after all steps succeed are final shadow records
atomically installed as LIVE at the final cutoff.

## Explicit non-goals preserved

D6 does not add:

- DecisionPolicy or final policy results;
- TradeSignal or publication;
- Valkey/Redis, Timescale, HTTP, scraper, FastAPI or Docker;
- AssetRuntime, input consumers, background loops or service scheduling;
- PriceRelay or LaneCommitWatermark advancement;
- real model adapters or downstream migrations;
- state checkpoints, journals, persistence or retry frameworks;
- generic DAG/workflow/actor/executor frameworks.

D7 remains unstarted.

## Validation evidence (pre-remediation baseline)

Focused D6 tests:

- tests/decision/test_runtime_plugins.py
- tests/decision/test_model_runtime.py
- tests/decision/test_state_rewarm.py
- 16 passed

Cumulative compatibility suite:

- tests/decision
- tests/commons/test_model_runtime_contract.py
- tests/models/test_strategy_model_v2.py
- 173 passed

The full tests/decision collection alone passed 161 tests.

Static validation:

- Ruff check: passed;
- Ruff format --check: passed;
- compileall: passed;
- git diff --check: passed;
- trailing-whitespace scan: passed.

An AST import-boundary scan over the three D6 production modules passed. No
forbidden infrastructure, downstream application, network, database, or
dataframe imports are present.

Repository-local validation generated and then removed Python cache files; no
runtime service, external data store, or production state was touched.

## Two review passes

Pass 1 correctness checks:

- request-before-evaluation ordering;
- one resolver batch per step;
- dependency artifact reuse;
- binding feature/data isolation;
- dynamic demand fail-closed validation;
- output identity/type validation;
- state proposal versus commit;
- atomic multi-stateful commit;
- stale commit and abort;
- no stale-state continuation;
- REPLAY-only rewarm;
- failed rewarm real-store preservation;
- grid-based rewarm continuity.

Pass 2 scope checks:

- no runtime service loop;
- no infrastructure adapter;
- no publication or policy layer;
- no generic graph/workflow framework;
- no persistent state/checkpoint layer;
- no D7 model adapter.

## D6 continuity remediation

The remediation closes the LIVE state-transaction boundary without adding a
runtime framework.  Initialized stateful bindings now require the requested
market cutoff to equal the common committed cutoff plus exactly one configured
trigger duration.  Same-cutoff, backward, and skipped-trigger evaluations fail
closed before feature or model execution.

Each runtime owns at most one `_pending_state_execution`.  Any prepared result
with one or more state transitions occupies that slot, including an ineligible
multi-stateful partial result.  A second stateful preparation and causal
rewarm are rejected until the pending result is explicitly committed or
aborted.  Commit and abort accept only the current prepared object; failed
commit validation leaves both state and the pending owner unchanged.  Abort
degrades only transition-bearing bindings, preserving the existing rewarm
requirement and invalid peer state.

`PreparedLaneExecution` now self-validates complete feature/data/result binding
coverage, artifact binding and lane identity, and blocker references to real
non-executed results.  `LaneStateStore.install_rewarm()` also requires one
shared committed cutoff across the reconstructed stateful records.

New focused regressions cover exact trigger continuity, pending ownership and
clearance, copied prepared-object rejection, pending-aware rewarm, partial
multi-stateful failure without stale continuation, prepared evidence-map
completeness, artifact identity, and invalid blocker evidence.

Post-remediation validation:

- focused D6 files: **25 passed**;
- cumulative D1-D6 compatibility command: **182 passed**;
- Ruff check: passed;
- Ruff format --check: passed;
- compileall: passed;
- git diff --check: passed;
- D6 import-boundary scan: passed;
- no Docker, broker, database, network, or live-market operation was run;
- D7 remains unstarted.

## Final status

DECISION_APP_D6_MODEL_RUNTIME_STATE_REWARM_READY_FOR_REVIEW
