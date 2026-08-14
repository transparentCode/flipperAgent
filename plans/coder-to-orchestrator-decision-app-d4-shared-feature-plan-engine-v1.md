---
goal: Implement the deterministic demand-driven shared FeaturePlan and offline FeatureEngine for decision_app
stage: coder-to-orchestrator
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Coder
status: Ready
source_agent: quant-coder
target_agent: quant-orchestrator
tags: [handoff, quant, decision-app, d4, features, feature-engine]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Coder-to-orchestrator — `decision_app` D4 shared FeaturePlan + offline FeatureEngine

## Scope executed

Implemented and remediated the approved D4 offline shared-feature layer in the
cumulative D0 worktree. The change remains synchronous, deterministic, causal
and infrastructure-free. No model is instantiated or evaluated by the
application runtime, and no external state was touched.

## Files and symbols changed

Added:

```text
src/apps/decision_app/features.py
src/apps/decision_app/feature_engine.py
tests/decision/test_features.py
tests/decision/test_feature_engine.py
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Updated:

```text
src/libs/contracts/decision.py
src/apps/decision_app/contracts.py
tests/decision/test_plugin_contract.py
tests/decision/test_semantic_contracts.py
```

Core additions are `FeatureRequirement`, `FeatureSnapshot`,
`FeatureHistoryRequirement`, `SharedFeatureDefinition`, `FeatureCatalog`,
`FeaturePolicy`, `BindingFeaturePlan`, `FeaturePlan`, `SharedFeatureContext`,
`FeatureEngine`, `BindingFeatureResolution` and `FeatureResolution`.

## Remediation closure

The D4 remediation closes the independently identified fail-closed gaps:

- `validate_feature_plan_against_lane()` revalidates every binding's required
  and optional demand against the current `ResolvedModelBinding`, including
  lane revision and binding identity. Both `FeatureEngine` and capacity
  compilation use this same validator.
- Effective, disabled and undefined feature classifications are disjoint and
  complete. An undefined feature is never also reported as disabled, and
  binding-level classifications are checked against the lane-level partition.
- Capacity compilation requires exactly one current `FeaturePlan` per resolved
  lane, rejects missing/extra/duplicate plans and stale revisions, and ignores
  disabled/undefined/unrequested features.
- `BindingFeatureResolution` rejects present/missing contradictions, while
  `FeatureResolution` rejects shared/unavailable contradictions and requires
  binding-visible snapshots to be semantically equal to the shared snapshot.
  Missing binding features must have corresponding unavailable evidence.

The follow-up fingerprint-integrity remediation makes `FeaturePlan` self-
validating. Construction normalizes the plan's semantic fields, recomputes the
existing SHA-256 payload from those fields, and rejects a supplied fingerprint
that does not match. This also protects `dataclasses.replace()` paths: policy
name/version/allowlist, feature version/history, effective/classification and
binding-demand drift cannot retain an old plan identity. The canonical payload
helper is shared by compilation and validation; no second identity scheme was
introduced.

Focused regressions cover required/optional demand tampering, added/omitted
demand, undefined-only classification, incomplete/extra/stale capacity plans,
shared snapshot mismatch, present/missing/unavailable contradictions and
semantic snapshot reuse. Fingerprint regressions cover feature version,
history, policy name/version/allowlist, effective/classification drift,
required-vs-optional demand, unused catalog entries and calculator identity.

## Contract migration

`ModelSpec.intrinsic_feature_requirements` and
`ResolvedModelBinding.effective_feature_requirements` now contain typed,
strictly-boolean `FeatureRequirement` values. Duplicate names are rejected and
requirements are normalized deterministically.

`ModelRequestContext.shared_features` and `DecisionContext.shared_features`
now require a key-to-`FeatureSnapshot` mapping. The snapshot carries only
causal `market_as_of`, immutable semantic value and immutable provenance; no
completion timestamp or infrastructure handle is introduced.

## Catalog, policy and static plan

`FeatureCatalog` is explicit, sorted and immutable, with one definition per
semantic feature name and no discovery or global registry. `FeaturePolicy` is a
strict operator allowlist; unknown allowlist entries fail during plan
compilation.

`compile_feature_plan()` preserves per-binding required/optional demand while
deduplicating effective lane-level computation. Required disabled/undefined
features make only the affected binding statically unavailable; optional
disabled/undefined features remain explicit absence evidence. Unrequested
allowed/catalogued features are not effective and are not computed.

The full-SHA256 `feature_plan_fingerprint` includes the lane/base revision,
policy identity and allowlist, per-binding required/optional demand, static
disabled/undefined results, active feature versions and resolved history
requirements. It is independent of input ordering and callable identity.

## History and capacity evidence

`resolve_feature_history_requirements()` supports only decision, trigger and
fixed timeframe sources. Duplicate resolved series use the maximum lookback.
`compile_feature_bar_store_capacities()` and
`merge_bar_store_capacities()` extend D3 physical shared capacity by maximum,
never by sum, and ignore disabled, undefined and unrequested features.

The feature capacity path does not alter D3 `LaneMarketRequirements` or
`DecisionViewBuilder` visible history. Feature calculators receive their own
exact bounded canonical history slice from `BarStore`.

## FeatureEngine evidence

`FeatureEngine.compute(feature_plan, resolved_lane, lane_market_view)` validates
lane identity, revision, binding set, catalog versions and resolved history
geometry before computing. It iterates effective features in sorted order,
builds one immutable `SharedFeatureContext` per feature, invokes each
calculator once, creates one immutable `FeatureSnapshot`, and reuses that
object for every requesting binding.

Feature histories are read only through causal cutoff queries, require exact
counts, expected canonical cutoff, contiguous recent bars and valid configured
timeframe geometry. Missing history/cutoff/gap produces explicit unavailable
evidence without invoking the calculator. Geometry corruption propagates as a
timeframe geometry error. Calculator exceptions and unsupported/non-finite
outputs become identified `FeatureComputationError` failures.

Binding-facing resolutions expose only each binding's enabled feature subset;
shared lane computation is not a universal feature vector. Projected D3
decision bars remain ephemeral and are passed through unchanged; D4 never
creates or writes a canonical higher-timeframe bar.

## Explicitly not executed

No D4 implementation was added for:

```text
model execution or dependency execution
DataResolver / external data
state, rewarm, DecisionPolicy or publication
PriceRelay
Valkey, Timescale, scraper, HTTP or FastAPI
AssetRuntime, async workers or scheduling
feature cache/store, feature stream, feature DAG or incremental engine
real model adapters, decision configuration or downstream migration
```

Before authoritative publication, final effective lane/decision identity must
incorporate this approved `feature_plan_fingerprint` and later material data
policy/runtime configuration. D4 does not mutate or publish `decision_id`.

## Validation

Using the primary repository interpreter and Ruff installation:

```text
pytest -q tests/decision/test_features.py tests/decision/test_feature_engine.py
26 passed

pytest -q tests/decision tests/commons/test_model_runtime_contract.py tests/models/test_strategy_model_v2.py
125 passed

ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
passed

ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
21 files already formatted

python -m compileall -q src/libs/contracts/decision.py src/apps/decision_app tests/decision
passed
```

`git diff --check`/whitespace validation is clean for the cumulative worktree.
The production D4 import boundary scan found no references to Valkey/Redis,
asyncpg, HTTP clients, FastAPI, scraper or ingestion runtime, database pools,
Pandas/Polars, downstream applications, `ModelOutcome`, `DataResolver` or
BarStore mutation in the two D4 production modules.

Validation generated repository-local bytecode caches; they were removed after
the test/compile runs. No Docker, broker, database, network or live-market
validation was run, as required by D4.

## Pass 1 — correctness / PIT / determinism

Reviewed and tested required-vs-optional policy behavior, unknown policy names,
shared compute deduplication, binding visibility isolation, exact feature
lookbacks, maximum capacity merging, future/cutoff filtering, gap handling,
canonical geometry rejection, projected-bar causality, immutable outputs,
non-finite/unsupported values and calculator failure identification.

## Pass 2 — simplicity / scope

No feature DAG, cache/store, DataFrame, discovery framework, async worker,
runtime scheduler, parameter DSL, external data path or model execution path
was added. The implementation is limited to one static planning module and one
synchronous computation module, with focused tests.

## Residual risks / carry-forward

The feature calculator boundary is a synchronous callable and purity remains a
code-review property, as authorized by D4. D5 owns the external DataResolver.
D6 owns complete model-context assembly and execution. Feature-plan identity
must be incorporated into final authoritative publication identity before that
boundary is implemented.

## Worktree state

The worktree remains detached and uncommitted. Existing cumulative D0-D3
untracked artifacts are preserved. No commit, merge, push, branch switch,
reset, restore, production database or broker mutation was performed.

DECISION_APP_D4_SHARED_FEATURE_ENGINE_READY_FOR_REVIEW
