---
goal: Close D4 fail-closed feature-plan and resolution contract gaps before authorizing D5
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d4, remediation, features]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — `decision_app` D4 shared feature remediation

## 1. Objective and evidence

Remediate the bounded D4 contract gaps found during independent review. Preserve the approved D4 architecture: demand-driven shared computation, app-owned feature definitions/policy, exact causal feature histories, once-per-lane/as-of computation, binding-isolated visibility, and no runtime/infrastructure work.

Independent validation of the submitted D4 package passed:

```text
D1-D4 compatibility: 113 passed
focused D4 rerun: 14 passed
Ruff check: passed
Ruff format: passed
compileall: passed
git diff --check: passed
infrastructure boundary: clean
```

The feature fingerprint implementation also passed direct probes for material changes: definition version, history requirement, policy version, and required-vs-optional demand change the fingerprint; calculator object identity does not.

However direct adversarial probes found the following invalid states currently accepted:

```text
required feature downgraded to optional in FeaturePlan
  -> FeatureEngine accepts it
  -> missing feature makes binding available instead of unavailable

undefined feature
  -> simultaneously classified disabled + undefined

FeaturePlan effective feature
  -> may simultaneously appear in disabled_features

compile_feature_bar_store_capacities(..., feature_plans=[])
  -> accepts a full ResolvedDecisionPlan with missing lane feature plans
  -> returns no feature capacity

stale FeaturePlan.base_lane_revision
  -> accepted by feature capacity compilation

FeatureResolution shared F=version 1/value 1
binding-facing F=version 2/future/value 999
  -> accepted

FeatureResolution F present and unavailable simultaneously
  -> accepted

BindingFeatureResolution F present and missing_required simultaneously
  -> accepted
```

D5 must not start until these are closed.

## 2. Scope

Prefer changing only:

```text
src/apps/decision_app/features.py
src/apps/decision_app/feature_engine.py
tests/decision/test_features.py
tests/decision/test_feature_engine.py
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Touch `src/libs/contracts/decision.py`, D3 files, planner, identity, or contracts only if a concrete regression proves a minimal compatibility change is necessary. Do not redesign D0-D3.

## 3. Non-goals

Do not implement or start:

```text
D5 DataResolver / DataPolicy
external data
model execution or dependency execution
state / rewarm
DecisionPolicy
publication
PriceRelay
Valkey / Timescale / HTTP / FastAPI
AssetRuntime / async workers
feature cache/store/stream
incremental feature engine
feature DAG
decision config
real model adapters
```

No commit, merge, push, branch switch, reset, or restore.

## 4. BLOCKER — revalidate binding demand against the resolved lane

`FeatureEngine.compute()` must not trust only feature-plan binding IDs. Before computation, validate each `BindingFeaturePlan` against the corresponding `ResolvedModelBinding.effective_feature_requirements`.

For every resolved binding, derive canonical sets from the D2/D4 contract:

```text
required = {requirement.name | requirement.required is True}
optional = {requirement.name | requirement.required is False}
```

Require exact equality with:

```text
BindingFeaturePlan.required_features
BindingFeaturePlan.optional_features
```

Also require the feature plan contains exactly the resolved lane binding IDs, already intended by the current contract.

A stale/tampered plan must not be able to change required -> optional, optional -> required, add a feature, or remove a feature.

Add regressions:

```text
model requires F
plan says F optional
F runtime history unavailable
=> reject plan before computation; never report binding available

model optional F
plan says F required
=> reject

plan adds undeclared F
=> reject

plan omits declared F
=> reject
```

This validation should be a small reusable pure helper if both engine and capacity compilation need it. Do not create a planner framework.

## 5. HIGH — make feature status classifications disjoint and complete

The compiler currently makes an undefined feature also appear disabled because `disabled = requested - allowed` while policy allow entries must be catalog-defined.

Use disjoint semantics:

```text
undefined = requested - catalog_defined

effective = requested ∩ catalog_defined ∩ operator_allowed

disabled = requested ∩ catalog_defined - operator_allowed
```

Therefore:

```text
effective ∩ disabled = empty
effective ∩ undefined = empty
disabled ∩ undefined = empty
union(effective, disabled, undefined) == requested
```

Apply the same partition to every `BindingFeaturePlan`, separately for required and optional demands.

For each requested binding feature, exactly one static classification is allowed:

```text
enabled
OR disabled
OR undefined
```

Required/optional demand remains a separate axis.

Strengthen `FeaturePlan.__post_init__` / `BindingFeaturePlan.__post_init__` so contradictory manually constructed objects fail closed, including:

```text
feature both enabled and disabled
feature both disabled and undefined
feature enabled but not globally effective
binding disabled feature not globally disabled
binding undefined feature not globally undefined
classification does not cover all requested binding features
```

Keep `statically_available` derived from required disabled/undefined features.

Add a regression proving an undefined request is **undefined only**, not also disabled.

## 6. HIGH — require a complete, current feature-plan set for capacity compilation

`compile_feature_bar_store_capacities()` receives the full `ResolvedDecisionPlan`; it must not silently accept an incomplete or stale feature-plan set because that can under-allocate shared history before runtime.

Require:

```text
set(feature_plan.lane_id) == set(resolved_decision_plan lane IDs)
```

Exactly one `FeaturePlan` per resolved lane, including lanes with zero effective features.

For every plan/lane pair validate at least:

```text
feature_plan.base_lane_revision == lane.effective_lane_revision
feature_plan binding IDs == resolved lane binding IDs
binding required/optional demand == resolved binding effective_feature_requirements
```

Retain the existing version/history checks against `FeatureCatalog` and `TimeframeGrid`.

Fail closed on:

```text
missing lane feature plan
extra/unknown lane plan
duplicate lane plan
stale base lane revision
stale/mismatched binding IDs
stale required/optional binding demand
```

Do not require feature capacity from disabled/undefined/unrequested features.

## 7. HIGH — make FeatureResolution a trustworthy D6 boundary

D6 will consume `FeatureResolution` directly, so it must be internally self-consistent even if manually constructed.

### BindingFeatureResolution

Require:

```text
features keys are disjoint from missing_required_features
features keys are disjoint from missing_optional_features
missing_required_features and missing_optional_features are disjoint
```

Current availability rule remains:

```text
available == (missing_required_features is empty)
```

### FeatureResolution

Require:

```text
shared_features keys ∩ unavailable_features keys == empty
```

For every binding-visible feature:

```text
name exists in shared_features
binding snapshot == shared_features[name]
```

Semantic equality is sufficient; do not rely on object identity for a future serialized boundary. This guarantees same name/version/market_as_of/value/provenance.

This also ensures a binding cannot receive a future or different-version snapshot while lane-level shared evidence says something else.

Add regressions for:

```text
shared F v1 vs binding F v2/future/value-different => reject
F both shared and unavailable => reject
F both present and missing_required => reject
F both present and missing_optional => reject
same valid shared FeatureSnapshot reused/equal across two bindings => accept
```

Do not add a FeatureResolution registry or persistence layer.

## 8. Fingerprint acceptance regressions

The implementation already passes direct independent probes. Add focused tests so these D4 acceptance criteria remain protected:

```text
feature definition version change -> fingerprint changes
history requirement change -> fingerprint changes
policy name/version or allowlist material change -> fingerprint changes
required vs optional model demand change -> fingerprint changes
unrequested catalog definition addition -> fingerprint unchanged
calculator callable identity/repr change with same name/version/history -> fingerprint unchanged
```

No second identity framework.

## 9. Preserve causal and capacity behavior

Do not regress the already-correct D4 behavior:

```text
exact bounded feature histories
canonical geometry validation
continuous-UTC recent-history contiguity
projected decision_bar remains ephemeral and causal
canonical HTF history never includes a future bucket
shared feature computed once per lane/as_of
binding visibility remains isolated
feature history capacity merges by max, not sum
D3 LaneMarketView visible history remains lane-local
FeatureSnapshot deep immutability
calculator errors remain FeatureComputationError
```

## 10. Validation

Use:

```text
/Users/kajukatli/projects/flipperAgent/.venv/bin/python
```

Run focused D4 first:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision/test_features.py \
  tests/decision/test_feature_engine.py
```

Then full current decision compatibility:

```bash
/Users/kajukatli/projects/flipperAgent/.venv/bin/python -m pytest -q \
  tests/decision \
  tests/commons/test_model_runtime_contract.py \
  tests/models/test_strategy_model_v2.py
```

Then:

```text
ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
compileall changed/current decision_app packages
git diff --check
untracked whitespace checks as needed
infrastructure boundary scan
remove generated repository-local caches after validation
```

No Docker/network/database/broker validation.

## 11. Two-pass coder self-review

Pass 1 — correctness:

```text
resolved binding demand cannot be downgraded/upgraded by FeaturePlan
feature static statuses are a disjoint complete partition
capacity compilation cannot omit or use stale lane plans
FeatureResolution cannot contradict shared evidence
PIT/history/projected semantics unchanged
fingerprint material-change behavior remains deterministic
```

Pass 2 — simplicity:

```text
no new framework
no generic feature graph
no cache/store
no runtime integration
no policy DSL
no new production module unless unavoidable
```

## 12. Handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Include exact remediation tests/results and adversarial evidence.

Final line exactly:

```text
DECISION_APP_D4_SHARED_FEATURE_ENGINE_READY_FOR_REVIEW
```
