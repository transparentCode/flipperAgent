---
goal: Close the remaining D4 FeaturePlan fingerprint self-integrity gap without changing D4 architecture
stage: architect-to-coder
date_created: 2026-08-13
last_updated: 2026-08-13
owner: Quant Orchestrator
status: Ready
source_agent: quant-orchestrator
target_agent: quant-coder
tags: [handoff, quant, decision-app, d4, remediation, fingerprint]
source_base: 4fc0de62515112dc371e08a6cde503746c54f7f7
source_worktree: /Users/kajukatli/projects/flipperAgent/.worktrees/decision-app-d0
---

# Architect-to-coder — D4 FeaturePlan fingerprint integrity remediation

## Objective

Fix one remaining D4 fail-closed invariant: a materially modified `FeaturePlan` must not retain an old `feature_plan_fingerprint` and still be accepted by `FeatureEngine` or feature-capacity compilation.

The broader D4 remediation is otherwise accepted by review: resolved-binding demand validation, disjoint effective/disabled/undefined classification, complete current feature-plan enforcement, and `FeatureResolution` snapshot/missing consistency are present and passing.

Do not start D5.

## Verified defect

A valid compiled plan can currently be modified with `dataclasses.replace(...)` while keeping the old fingerprint. These all remain accepted by `FeatureEngine.compute()`:

```text
feature_policy_name:    operator -> other
feature_policy_version: 1 -> 2
operator_allowed_features: (F) -> (F, UNUSED)
```

The old `feature_plan_fingerprint` is unchanged in every case.

This violates the approved D4 identity contract: feature policy name/version/allowlist are material fingerprint inputs, and the fingerprint is explicitly carried forward for final authoritative identity before D8.

## Scope

Prefer changes only in:

```text
src/apps/decision_app/features.py
tests/decision/test_features.py
tests/decision/test_feature_engine.py
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Touch `feature_engine.py` only if needed to call a shared validator. Do not alter D0-D3 behavior, model execution, DataResolver, runtime, infrastructure, or publication.

## Selected design

Make `FeaturePlan.feature_plan_fingerprint` self-validating from the semantic fields already stored on the plan.

Add one small deterministic helper, for example:

```text
compute_feature_plan_fingerprint_from_plan(plan) -> str
validate_feature_plan_fingerprint(plan) -> None
```

or equivalent.

It must recompute the same canonical payload used by `compile_feature_plan()` using only plan-owned semantic values:

```text
lane_id
base_lane_revision
feature policy name/version
operator allowlist
per-binding required/optional/enabled/disabled/undefined demand
feature versions
resolved feature history requirements
static effective/disabled/undefined classification
```

Do not hash calculator repr/identity and do not add a second serialization framework; reuse existing `sha256_fingerprint()`.

Refactor `_feature_fingerprint_payload` if useful so compile-time and validation-time hashing share one canonical implementation rather than duplicating payload logic.

The strongest/simple boundary is to validate inside `FeaturePlan.__post_init__` after normalization so any manually constructed or replaced plan with a stale fingerprint fails immediately. If implementation constraints make that awkward, both `FeatureEngine.compute()` and `compile_feature_bar_store_capacities()` must call the shared validator before trusting the plan. Prefer the self-validating data contract.

## Acceptance tests

Add regressions proving each material mutation with the old fingerprint is rejected:

```text
feature_policy_name change
feature_policy_version change
operator_allowed_features change
required/optional binding demand change (already covered, keep it)
feature version/history change where a manually constructed plan preserves old fingerprint
classification/effective-set change with old fingerprint
```

Also prove unchanged semantic reconstruction accepts the original fingerprint, and existing properties remain true:

```text
input ordering does not affect fingerprint
calculator object identity does not affect fingerprint
unrequested catalog addition alone does not affect fingerprint
```

Do not weaken the existing demand/capacity/resolution regressions.

## Validation

Run:

```text
pytest -q tests/decision/test_features.py tests/decision/test_feature_engine.py
pytest -q tests/decision tests/commons/test_model_runtime_contract.py tests/models/test_strategy_model_v2.py
ruff check src/libs/contracts/decision.py src/apps/decision_app tests/decision
ruff format --check src/libs/contracts/decision.py src/apps/decision_app tests/decision
python -m compileall -q src/libs/contracts/decision.py src/apps/decision_app tests/decision
git diff --check
infrastructure boundary scan
remove generated repo-local __pycache__ directories after validation
```

No Docker, Valkey, Timescale, HTTP, FastAPI, network, model execution, or D5 work.

## Expected handoff

Update:

```text
plans/coder-to-orchestrator-decision-app-d4-shared-feature-plan-engine-v1.md
```

Include the fingerprint-integrity regressions and exact validation counts.

Final status:

DECISION_APP_D4_SHARED_FEATURE_ENGINE_READY_FOR_REVIEW
