---
goal: Implement the deterministic static composition planner for decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d2, planner, dependencies]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator handoff — `decision_app` D2 static composition planner

## Result

D2 is complete as a small deterministic static compiler over the approved D1
semantic contracts. It resolves explicit plugin specifications and lane/binding
wiring into immutable plans without evaluating a model or performing any
infrastructure I/O.

No D3 work was started.

## Scope and starting checkout

```text
starting SHA: 4fc0de62515112dc371e08a6cde503746c54f7f7
worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
branch state: detached HEAD from main
primary checkout: not modified
commit/merge/push/branch switch/reset/restore: none
```

The worktree contains the approved cumulative D0/D1 artifacts. Existing
untracked D0/D1 files were preserved. No configuration, Compose, runtime,
signal, strategy, risk, execution, portfolio, ingestion, or scraper file was
changed.

## Files and symbols changed

```text
src/libs/contracts/decision.py
  ModelDependencyRequirement
  ModelSpec additive intrinsic fields:
    produces_artifact_type
    supported_trigger_timeframes
    dependency_requirements

src/apps/decision_app/catalog.py
  CatalogError
  PluginCatalog

src/apps/decision_app/planner.py
  PlannerError
  ModelBindingSpec
  DecisionLaneSpec
  ResolvedLanePlan
  ResolvedDecisionPlan
  StaticCompositionPlanner
  compile_decision_plan

tests/decision/test_catalog.py
tests/decision/test_planner.py
tests/decision/test_semantic_contracts.py
tests/decision/test_plugin_contract.py
```

`identity.py` and `apps/decision_app/contracts.py` were reused unchanged for
D2. Existing D1 tests were updated only to provide the newly required
plugin-owned artifact type.

## Additive ModelSpec extension

`ModelDependencyRequirement` requires a non-empty dependency slot and expected
artifact type. `ModelSpec` now requires `produces_artifact_type`, and accepts
the empty-or-explicit capability tuple `supported_trigger_timeframes` plus
model-owned `dependency_requirements`. Duplicate dependency slots and invalid
entries fail during spec construction. Existing `supported_timeframes` retains
its D2 meaning as supported decision timeframes.

The planner rechecks stateful effective replay safety before constructing a
resolved binding. For every stateful binding it walks the complete same-lane
dependency ancestor closure, so a non-replay-safe external requirement on a
direct or transitive upstream model identifies the stateful consumer, offending
upstream binding, and data concept and fails startup. D2 uses only intrinsic
feature/data requirements; it does not apply a future operator feature policy
or physical data policy.

## Catalog behavior

`PluginCatalog` is explicitly constructed from `ModelSpec` values. It has no
global registry, import scanning, entry points, module paths, factories, or
runtime loading. Exact `(name, version)` duplicates are rejected; multiple
versions of one name are supported; unknown exact lookups fail with
`CatalogError`. Iteration is sorted by `(name, version)`, and the catalog
backing structures reject normal mutation.

## Binding and lane resolution

`ModelBindingSpec` freezes parameters using the D1 semantic-value vocabulary
and validates string-only dependency wiring. `DecisionLaneSpec` validates
market/lane identity, timing, policy identity, binding-slot uniqueness,
authoritative risk-key requirements, and immutable policy parameters.

For every binding the planner:

```text
exact catalog lookup
→ decision/trigger timeframe and trigger-mode capability checks
→ stateful replay-safety recheck
→ deterministic binding fingerprint
→ deterministic binding ID
```

The fingerprint includes lane/market identity, slot, timing, plugin
name/version, sorted dependency wiring, and model parameters. Resolved
bindings contain complete non-empty identity fields, the resolved ModelSpec,
intrinsic requirements, lane revision, and provider binding IDs rather than
raw dependency slot names.

## Dependency and artifact validation

Declared model dependency slots must be wired exactly once. Undeclared slots,
missing slots, missing same-lane providers, self-dependencies, and artifact
type mismatches fail closed. There is no cross-lane lookup syntax or graph
machinery. A shared provider is represented once in the lane plan and its
binding ID is reused by every consumer.

The planner uses a direct stable Kahn topological sort. Ready nodes are ordered
by binding slot name. Cycles report deterministic involved slots. The canonical
synthetic graph:

```text
Boundary → Regression
        ↘ BreakoutContext
```

resolves Boundary once, followed by deterministic `breakout`/`regression`
ordering.

## Plan identity and authority

The effective lane revision includes lane/market/timing/authority/risk
identity, sorted resolved binding IDs/fingerprints and dependency wiring, and
policy name/version/parameters. Parameter, dependency, timing, policy, or risk
changes therefore alter the revision. Input binding/catalog order does not.

`ResolvedLanePlan` freezes policy parameters and self-validates binding map
keys, lane/revision identity, timeframe/mode, authority/risk agreement, unique
execution IDs, same-lane dependency IDs, and provider-before-consumer order.
`ResolvedDecisionPlan` sorts lanes by lane ID, rejects duplicate lane IDs, and
derives/checks that its immutable authoritative routes exactly represent every
authoritative lane and no shadow lane. Shadow lanes may share an authoritative
route, while a second authoritative lane for the same route fails. Different
assets and decision timeframes remain independent.

## D2 remediation evidence

The independent D2 review findings are closed without changing the planner
architecture:

```text
stateful → direct LIVE-only ancestor              rejected
stateful → transitive LIVE-only ancestor          rejected
stateful replay-safe ancestor closure             accepted
mutable resolved policy parameters                frozen
duplicate execution ID                            rejected
consumer before provider                         rejected
foreign dependency binding ID                    rejected
binding map key / slot mismatch                  rejected
binding lane or revision mismatch               rejected
binding timing/authority/risk mismatch            rejected
invalid or shadow authoritative route            rejected
duplicate resolved lane ID                        rejected
```

Stateful closure errors include the stateful consumer, offending upstream
binding, and data concept. The resolved-plan checks are enforced in the
exported dataclass constructors as well as by the compiler, so later runtime
phases can trust provider precedence, binding identity, lane consistency, and
authoritative route data.

## Validation

All commands used the primary repository interpreter where Python was needed:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q tests/decision
58 passed in 0.14s

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
70 passed in 2.75s

/Users/kajukatli/.local/bin/ruff check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
passed

/Users/kajukatli/.local/bin/ruff format --check \
  src/libs/contracts/decision.py src/apps/decision_app tests/decision
11 files already formatted

/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m compileall -q \
  src/libs/contracts/decision.py src/apps/decision_app
passed

git diff --check
passed

untracked-file whitespace check for new D1/D2 Python files
passed

infrastructure-import boundary scan over D1/D2 production modules
passed; no infrastructure imports or model execution call
```

The focused D2 tests cover catalog lookup/versioning/immutability, all
capability gates, direct and transitive stateful replay safety, dependency-slot
errors, provider absence, self-dependency, artifact mismatch, cycles, shared
dependencies, stable topological order, resolved-plan immutability and
invariants, identity changes, authority collisions, duplicate lane/binding
validation, unsupported semantic parameters, and the infrastructure/import
boundary.

## Pass 1 — correctness self-review

Reviewed catalog name/version ambiguity, complete resolved identity, capability
bypass, direct/transitive stateful replay safety, dependency slot completeness,
same-lane provider resolution, artifact compatibility, self/cyclic graphs,
stable topological ordering, resolved binding/lane invariants, execution-order
uniqueness and provider precedence, mapping/list insertion-order independence,
parameter and policy identity drift, risk-profile identity, and
authoritative-route consistency. The direct synthetic permutation tests
produce identical fingerprints, binding IDs, lane revision, dependency
identities, and execution order.

No D0/D1 contradiction was found.

## Pass 2 — simplicity and scope self-review

Confirmed D2 contains only an explicit catalog and direct planner. It adds no
global mutable registry, discovery mechanism, factory, NetworkX/workflow
dependency, abstract planner framework, cross-lane graph support, runtime task,
model execution, I/O, configuration loader, or infrastructure client.

## Explicitly not executed

No model execution, model instance/factory, BarStore, AssetRuntime,
DecisionLane runtime, FeatureEngine, DataResolver, Timescale, scraper, Valkey,
PriceRelay, publication, state commit/rewarm, FastAPI, Docker, decision YAML,
real model adapter, downstream migration, or live-market validation was run or
introduced.

## Blockers and residual risks

None for the authorized D2 static-planner scope. Runtime enforcement that
actual dynamic model data requests refine the intrinsic envelope, physical
DataPolicy resolution, causal state progression, model execution, publication,
and PriceRelay recovery remain intentionally deferred to later authorized
phases.

## Final status

DECISION_APP_D2_STATIC_COMPOSITION_PLANNER_READY_FOR_REVIEW
