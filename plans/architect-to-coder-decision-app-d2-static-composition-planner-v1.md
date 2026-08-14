---
goal: Implement the deterministic static model catalog, binding resolver, and same-lane dependency planner for decision_app
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d2, planner, dependencies]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D2 static composition planner

## 1. Objective

Implement the **smallest deterministic static composition layer** on top of the approved D0 architecture and approved D1 contracts.

D2 converts explicit lane/model configuration plus an explicit plugin-spec catalog into a fully validated immutable decision plan:

```text
explicit plugin catalog
+ lane/binding specifications
        ↓
capability validation
binding identity resolution
dependency-slot resolution
artifact compatibility
cycle detection
authoritative-lane validation
        ↓
deterministic ResolvedDecisionPlan
```

D2 performs **no model evaluation and no infrastructure I/O**.

Expected terminal status:

```text
DECISION_APP_D2_STATIC_COMPOSITION_PLANNER_READY_FOR_REVIEW
```

Continue in the existing cumulative isolated worktree:

```text
/Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
```

Do not start from plain `main`; the approved D0/D1 artifacts in this worktree are the source of truth.

## 2. Approved source of truth

Read and preserve:

```text
docs/architecture/decision_app/README.md
docs/architecture/decision_app/contracts.md
docs/architecture/decision_app/decisions.md
src/libs/contracts/decision.py
src/apps/decision_app/contracts.py
src/apps/decision_app/identity.py
plans/coder-to-orchestrator-decision-app-d1-core-contracts-v1.md
```

D0 status: approved.
D1 status: approved.

D2 may make only the **small additive D1 contract extension explicitly authorized below** where static dependency/capability validation requires intrinsic model metadata. Do not otherwise redesign D1 contracts.

## 3. Scope

### Allowed production files

Prefer this minimal shape:

```text
src/libs/contracts/decision.py              # small additive intrinsic model metadata only
src/apps/decision_app/catalog.py            # immutable explicit plugin-spec catalog
src/apps/decision_app/planner.py            # lane/binding specs + deterministic static planner
```

`src/apps/decision_app/contracts.py` and `identity.py` may be touched only if a concrete, minimal compatibility change is required. Reuse existing D1 helpers rather than duplicating identity/freeze logic.

Do not create additional production modules unless there is a demonstrated ownership problem. If D2 starts growing into a package hierarchy or framework, stop and report why.

### Allowed tests

Prefer at most two new files:

```text
tests/decision/test_catalog.py
tests/decision/test_planner.py
```

Existing D1 tests may be updated only for the authorized additive `ModelSpec` fields.

## 4. Explicit non-goals

D2 must not implement:

```text
model instantiation or model execution
DecisionModelPlugin.evaluate calls
runtime model loader/factory machinery
BarStore
AssetRuntime runtime
DecisionLane runtime
FeaturePlan execution
FeatureEngine
DataResolver
Timescale access
scraper access
Valkey reads/writes
publication/idempotent stream adapter
PriceRelay runtime
state commit/rewarm runtime
FastAPI/control plane
observability runtime
Docker/Compose
configs/decision
real model migration/adapters
signal_app/strategy_app changes
risk_app/execution_app changes
training/optimization
cross-lane dependencies
cross-asset model dependencies
generic DAG/workflow framework
hot graph mutation
```

No new dependency in `pyproject.toml`.

Do not commit, merge, push, switch branches, reset, or restore.

## 5. Authorized additive `ModelSpec` extension

D0 requires dependency artifact compatibility and D2 must validate model runtime capabilities. The current D1 `ModelSpec` lacks enough intrinsic metadata to prove these safely. Add only the following minimal plugin-owned semantics in `src/libs/contracts/decision.py`.

### 5.1 `ModelDependencyRequirement`

Add a small immutable contract approximately:

```text
ModelDependencyRequirement
  slot_name
  artifact_type
```

Rules:

- both fields are required non-empty strings;
- dependency slots are intrinsic model semantics, not config-owned physical wiring;
- all declared dependency slots are required in V1;
- duplicate slot names in one `ModelSpec` are invalid;
- no optional dependency framework in D2.

### 5.2 Produced artifact type

A plugin's `ModelSpec` must declare the artifact type it promises to produce:

```text
produces_artifact_type
```

This is the static type checked against downstream dependency requirements.

Do not infer it from model name or `output_kind`.

Later runtime phases must still verify that the actual `ModelArtifact.artifact_type` returned by a model matches this declaration; D2 does not execute models.

### 5.3 Trigger timeframe capability

Keep existing `supported_timeframes` and freeze its D2 meaning as **supported decision timeframes**.

Add:

```text
supported_trigger_timeframes
```

Capability semantics for D2:

```text
empty capability tuple => model declares no intrinsic restriction for that dimension
non-empty tuple         => binding value must be present in the tuple
```

Validate:

```text
binding.decision_timeframe against ModelSpec.supported_timeframes
binding.trigger_timeframe against ModelSpec.supported_trigger_timeframes
binding.trigger_mode against ModelSpec.supported_trigger_modes
```

Do not introduce a general capability-expression system.

### 5.4 Dependency requirements on `ModelSpec`

Add:

```text
dependency_requirements: tuple[ModelDependencyRequirement, ...]
```

Validate the tuple eagerly and reject duplicate dependency slot names.

Update `__all__` and D1 tests as necessary.

## 6. Explicit plugin catalog

Implement an immutable, in-memory **spec catalog**, not a discovery framework.

Conceptually:

```text
PluginCatalog
  key = (ModelSpec.name, ModelSpec.version)
  value = ModelSpec
```

Required behavior:

- constructed explicitly from supplied `ModelSpec` values;
- no global mutable registry;
- no import scanning;
- no Python entry points;
- no package discovery;
- no module-path strings;
- multiple versions of one plugin name are allowed;
- duplicate exact `(name, version)` registration fails;
- unknown plugin name/version lookup fails with a clear planner/catalog error;
- catalog contents cannot be mutated after construction;
- deterministic iteration/order, preferably sorted by `(name, version)`.

The D2 catalog contains **specs only**. Do not add model factories or instantiate plugins. Runtime factory/loading is a later phase.

## 7. Static input specifications

Define small immutable app-owned planner input contracts in `planner.py`. Use simple dataclasses; do not create a config framework.

### 7.1 `ModelBindingSpec`

Approximately:

```text
ModelBindingSpec
  slot_name
  plugin_name
  plugin_version
  parameters
  dependencies
    consumer dependency slot -> provider binding slot_name
```

Rules:

- `slot_name`, plugin name/version non-empty;
- parameters use the approved immutable semantic-value vocabulary;
- dependency keys/values are non-empty strings;
- dependency mapping is wiring only; expected artifact types remain model-owned in `ModelSpec`;
- no physical data-source fields;
- no model runtime object/factory.

### 7.2 `DecisionLaneSpec`

Approximately:

```text
DecisionLaneSpec
  lane_id
  asset
  venue
  instrument_id
  decision_timeframe
  trigger_timeframe
  trigger_mode
  authority: authoritative | shadow
  risk_profile_key
  policy_name
  policy_version
  policy_parameters
  bindings: tuple[ModelBindingSpec, ...]
```

Rules:

- identity/timing strings non-empty;
- lane has at least one binding;
- binding slot names unique within lane;
- authoritative lane requires a stable non-empty `risk_profile_key`;
- shadow lane may omit risk key;
- policy identity/version are static metadata only; no DecisionPolicy logic in D2;
- policy parameters are frozen using D1 semantic immutability rules.

Do not add feature-policy or datasource-policy configuration in D2.

## 8. Static output plan

Return immutable structures such as:

```text
ResolvedLanePlan
  lane spec identity
  effective_lane_revision
  resolved bindings
  execution_order: tuple[binding_id, ...]

ResolvedDecisionPlan
  lanes in deterministic order
  authoritative routes / identities as immutable data
```

Keep these structures small and data-only.

Do not create runtime worker/task objects.

## 9. Binding resolution algorithm

For every lane, perform the following deterministic steps.

### 9.1 Resolve catalog specs

For each `ModelBindingSpec`:

1. resolve exact `(plugin_name, plugin_version)` from `PluginCatalog`;
2. verify resolved `ModelSpec.name/version` match configuration;
3. validate decision timeframe / trigger timeframe / trigger mode capabilities;
4. revalidate stateful replay safety for all effective data requirements before constructing a `ResolvedModelBinding`;
5. compile effective feature/data requirements from intrinsic `ModelSpec` requirements only in D2.

D2 does not apply operator FeaturePolicy or physical DataPolicy. Those are later phases.

### 9.2 Dependency wiring validation

Compare configured dependency wiring against `ModelSpec.dependency_requirements`.

Required rules:

- every model-declared dependency slot is wired exactly once;
- no undeclared extra dependency slot is allowed;
- target provider binding slot must exist in the **same lane**;
- self dependency is invalid;
- provider `ModelSpec.produces_artifact_type` must exactly equal the consumer slot's required `artifact_type`;
- dependency resolution outputs named dependency slot -> **resolved provider binding_id** for `ResolvedModelBinding.dependencies`.

Do not support cross-lane lookup syntax.

### 9.3 Binding fingerprint

Use existing D1 `binding_config_fingerprint()`.

The canonical runtime-binding contribution must include all semantics that change a concrete binding, including at least:

```text
lane_id
asset / venue / instrument_id
trigger_timeframe
decision_timeframe
trigger_mode
plugin name/version
dependency wiring by slot name
```

plus configured model parameters.

A dependency rewiring must change the binding fingerprint even when model parameters are unchanged.

### 9.4 Binding ID

Use existing `make_binding_id()` with the deterministic binding fingerprint.

Binding IDs must be independent of input mapping/list insertion order.

### 9.5 Effective lane revision

Use existing `effective_lane_revision()`.

The lane revision must include a canonical representation of all material lane behavior, at least:

```text
lane identity and market identity
trigger/decision timing
lane authority
risk_profile_key
resolved binding identities/fingerprints
binding dependency wiring
policy name/version/parameters
```

Changing model parameters, dependency wiring, timing, risk key, policy version, or policy parameters must change the effective lane revision.

Input ordering alone must not change it.

### 9.6 Construct `ResolvedModelBinding`

Only after validation and identity computation construct the D1 contract.

Populate:

```text
model_spec
binding_config_fingerprint
binding_id
effective_lane_revision
trigger_timeframe
decision_timeframe
trigger_mode
resolved dependencies by binding_id
effective intrinsic feature/data requirements
risk_profile_key
publication_authority derived from lane authority
```

D2 must never construct a partially resolved binding with blank IDs.

## 10. Dependency graph and deterministic topological order

Implement a tiny graph planner directly. Do not introduce NetworkX or a DAG framework.

Requirements:

- graph nodes = resolved binding slots/IDs in one lane;
- edge `provider -> consumer`;
- reject self-cycle;
- reject any cycle;
- cycle error should identify deterministic involved slot names/IDs where practical;
- stable topological order independent of the order bindings were supplied;
- when multiple nodes are simultaneously ready, break ties deterministically using stable binding slot name (or another explicitly documented canonical key);
- an upstream binding referenced by multiple consumers appears once in execution order;
- no duplicate evaluation node is created for shared dependencies.

Representative valid graph:

```text
Boundary
   ├──> Regression
   └──> BreakoutContext
```

Expected order begins with `Boundary`; downstream tie order is deterministic.

## 11. Multi-lane plan validation

Compile multiple lane specs into one static `ResolvedDecisionPlan` and validate global publication authority.

Required rules:

- `lane_id` unique across plan;
- at most one `authoritative` lane for each `(asset, decision_timeframe)`;
- any number of `shadow` lanes may share the same `(asset, decision_timeframe)`;
- zero authoritative lane is allowed for research/shadow-only configuration;
- one lane's bindings cannot depend on bindings in another lane;
- returned lane ordering is deterministic, independent of input lane ordering.

No portfolio/cross-asset decision logic.

## 12. Failure behavior

D2 is a startup/static compiler. Invalid topology must fail immediately and clearly.

Prefer small explicit planner/catalog exception types only if they materially improve tests/callers. Do not create an exception hierarchy framework.

Must fail closed on:

```text
unknown plugin/version
duplicate catalog registration
duplicate lane_id
duplicate binding slot
unsupported decision timeframe
unsupported trigger timeframe
unsupported trigger mode
missing declared dependency
undeclared extra dependency
missing provider slot
self dependency
artifact type mismatch
cycle
authoritative lane collision
invalid/missing risk key for authoritative lane
stateful effective non-replay-safe data requirement
non-deterministic/unsupported parameter value
```

## 13. Important D2 boundary: dynamic model requests

`DecisionModelPlugin.data_requests()` is not executed in D2.

D2 uses `ModelSpec.intrinsic_data_requirements` as the statically declared potential external-data envelope.

Later runtime phases must enforce that a plugin's actual semantic requests are a subset/refinement of its declared envelope and must apply DataPolicy/resolved capability. Do not implement that runtime enforcement now.

## 14. Tests

Add strong synthetic tests. Do not migrate real quant models.

### Catalog tests

Cover:

```text
exact name/version lookup
multiple versions same name
duplicate exact registration rejected
unknown plugin/version rejected
immutable catalog
stable catalog iteration
```

### Capability tests

Cover:

```text
unrestricted empty capability tuples accepted
supported decision timeframe accepted
unsupported decision timeframe rejected
supported trigger timeframe accepted
unsupported trigger timeframe rejected
supported trigger mode accepted
unsupported trigger mode rejected
stateful effective replay safety revalidated
```

### Dependency tests

Use synthetic specs such as:

```text
BoundaryModel
  produces: boundary.v1

RegressionModel
  requires slot `boundary`: boundary.v1
  produces: regression.v1

BreakoutContextModel
  requires slot `boundary`: boundary.v1
  produces: breakout_context.v1
```

Prove:

```text
Boundary -> Regression resolves
shared Boundary -> two consumers resolves once
missing declared slot rejected
undeclared extra slot rejected
missing provider rejected
self dependency rejected
artifact mismatch rejected
A -> B -> A cycle rejected
execution order deterministic under reversed/random input binding order
resolved dependency mapping contains provider binding_id, not raw slot name
```

### Identity tests

Prove:

```text
same semantic lane/bindings in different input order => same binding fingerprints/IDs/lane revision/order
parameter change => binding fingerprint and lane revision change
dependency rewiring => binding fingerprint and lane revision change
trigger/decision timing change => lane revision change
policy version/parameter change => lane revision change
risk_profile_key change => lane revision change
```

### Authority tests

Prove:

```text
one authoritative lane accepted
authoritative + shadow same asset/timeframe accepted
multiple shadow lanes accepted
two authoritative lanes same asset/timeframe rejected
same timeframe on different assets accepted
same asset different decision timeframe accepted
```

### Boundary tests

Prove D2 modules import no:

```text
Valkey/Redis
asyncpg
HTTP clients
scraper app
ingestion runtime
FastAPI
Docker/config loaders
```

No model `evaluate()` call should appear in D2 production code.

## 15. Validation

Use the primary repo interpreter because this cumulative worktree may not have its own `.venv`:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q tests/decision
```

Because D2 extends `ModelSpec`, rerun the existing compatibility surfaces:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then scoped static checks on every D1/D2 Python file touched:

```text
ruff check
ruff format --check
compileall
git diff --check
untracked-file whitespace check where needed
infrastructure-import boundary scan
```

No Docker, Valkey, Timescale, browser, network, FastAPI, or live-market validation in D2.

## 16. Two-pass coder self-review

### Pass 1 — correctness

Review adversarially for:

```text
catalog identity ambiguity
name/version mismatch
capability bypass
blank/resolved identity errors
dependency slot ambiguity
artifact type mismatch
cross-lane leakage
cycle/self-cycle
input-order-dependent topological order
input-order-dependent fingerprints/revisions
stateful replay-safety bypass
authoritative route collision
risk-profile identity drift
```

Directly permute lane/binding input order in tests; do not rely on one fixture order.

If D2 reveals a genuine D0/D1 contradiction, stop with:

```text
DECISION_APP_D2_BLOCKED_ARCHITECTURE_CONFLICT
```

rather than silently redesigning contracts.

### Pass 2 — simplicity / overengineering

Remove or reject:

```text
global mutable registries
auto discovery
plugin factories used before runtime
NetworkX / graph libraries
workflow engines
abstract planner base classes
visitor frameworks
config loader frameworks
generic validation DSLs
cross-lane graph machinery
runtime tasks/workers
I/O
real model adapters
unused extension hooks
```

D2 should be a small explicit catalog plus a deterministic graph compiler.

## 17. Coder handoff

Create/update:

```text
plans/coder-to-orchestrator-decision-app-d2-static-composition-planner-v1.md
```

Use repository-compliant YAML front matter and include:

```text
scope executed / explicitly not executed
files and symbols changed
additive ModelSpec extension
catalog behavior
binding resolution behavior
dependency/artifact validation
topological-order evidence
identity determinism evidence
authoritative-lane evidence
validation commands and exact results
Pass 1 findings
Pass 2 findings
blockers / residual risks
```

Do not claim runtime/model-execution/BarStore/DataResolver/publication parity.

Final line exactly:

```text
DECISION_APP_D2_STATIC_COMPOSITION_PLANNER_READY_FOR_REVIEW
```

Do not start D3 automatically.
