# Architect → Coder: Phase-I Recommendation Ordering Remediation

## Objective

Fix the canonical Phase-I no-finalist recommendation ordering defect so recommendation identity is invariant to the order in which semantically identical primary validation trials are supplied.

Then independently verify the already persisted BTCUSDT 4h v2 artifact bundle without any network request, Phase-I rerun, artifact rewrite, holdout action, or trial-report generation.

## Scope Boundaries

### In scope

- canonicalize the no-finalist `validation_trials` ordering before collecting recommendation audits;
- add focused permutation-invariance regression tests;
- prove recommendation decision and evidence contents are unchanged;
- independently reload and verify the existing v2 bundle read-only;
- preserve byte identity of the complete v1 and v2 trial roots;
- produce a coder-to-review handoff.

### Out of scope

- any Binance request;
- rerunning `run_phase_i_evaluation` on the real dataset;
- rewriting, repairing, regenerating, or deleting persisted v2 artifact files;
- changing candidate metrics, objective gates, finalist selection, holdout rules, recommendation decisions, or audit semantics;
- changing `PromotionRecommendation` content schema or existing artifact schema version;
- changing runtime YAML or model configuration;
- tracker, interaction/event, MTF, RegimeV2, signal, selection, strategy, risk, execution, or portfolio work;
- reporting candidate metrics or recommendation before the existing bundle verifies.

## Diagnosed Cause

For no-finalist runs, `build_promotion_recommendation()` currently gathers audits from `validation_trials` in caller-provided order.

The original runner supplied grid-enumeration order. Artifact reload supplies trial-ID order. `PromotionRecommendation.__post_init__()` sorts audits only by `parameter_name`, preserving different tie order within each parameter. The evidence set is identical, but the serialized audit order and `recommendation_id` differ.

Independent probe:

```text
winner: None
different_top_level: parameter_effect_audits, recommendation_id
same_audit_set: true
```

## Selected Design

Canonicalize primary validation trials inside `build_promotion_recommendation()` before the no-finalist audit flattening step.

Use a stable semantic key derived from the complete parameter overrides, with trial ID as a deterministic tie-breaker. Prefer the repository's existing canonical serializer:

```python
(
    canonical_json(trial.trial.parameter_overrides),
    trial.trial.trial_id,
)
```

Then gather audits from this canonical trial sequence.

This design is selected because it:

- fixes the order dependence at the recommendation-construction boundary;
- leaves `PromotionRecommendation` schema and existing audit object semantics unchanged;
- preserves the v2 persisted recommendation's original canonical grid order;
- allows the existing content-addressed recommendation ID to verify without rewriting artifacts;
- avoids coupling generic recommendation construction to artifact manifests or filesystem path ordering.

Do not solve this by:

- making verifier comparison order-insensitive;
- changing or dropping `recommendation_id` validation;
- sorting audits by a new key in `PromotionRecommendation.__post_init__()` that changes existing persisted identity;
- special-casing the v2 run ID or artifact path;
- modifying the persisted recommendation JSON.

## Affected Symbols / Modules / Flows

Expected code scope:

```text
src/libs/models/trendline_family/optimization/evaluator.py
  build_promotion_recommendation

tests/models/trendline_family/optimization/
  focused recommendation/artifact regression tests

plans/coder-to-review-trendline-family-phase-i-recommendation-ordering-v1.md
.codebase-memory/
```

Read before editing:

```text
plans/review-to-architect-trendline-family-phase-i-recommendation-ordering-v1.md
plans/coder-to-review-trendline-family-candidate-real-data-trial-v2.md
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/research_lab/artifacts.py
```

Use codebase-memory impact analysis before modifying `build_promotion_recommendation`.

## Required Regression Tests

Add tests proving all of the following:

1. A no-finalist recommendation built from the same primary trials in grid order, reversed order, and trial-ID order has identical:
   - `to_dict()`;
   - `recommendation_id`;
   - decision and rationale;
   - parameter-effect audit sequence.

2. The test must include at least:
   - two tuned parameters;
   - multiple trials sharing the same `parameter_name` audit;
   - enough tied audit names to reproduce the stable-sort defect.

3. Changing audit content, trial overrides, or an audit ID still changes/rejects recommendation identity. Do not weaken integrity checks.

4. Finalist-present recommendation behavior remains unchanged.

5. Existing artifact attack/tamper tests remain green.

## Existing V2 Bundle Verification

Before any code change, capture a deterministic SHA-256 inventory of every file under:

```text
artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v1/

artifacts/trendline_family_candidate_trials/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

After tests pass, execute only read-only independent loading:

```python
load_verified_phase_i_artifacts(
    "artifacts/trendline_family_candidate_trials/"
    "btcusdt_4h_20250801_20251201_candidate_geometry_v2/phase_i"
)
```

Required outcome:

```text
bundle verification: pass
winner: None
recommendation decision: REJECT
rationale: no_validation_trial_passed_stage_owned_gates
```

These expected decision fields are already present in persisted evidence. Verification passing does not authorize metric interpretation or config promotion.

After verification, recalculate the full v1/v2 SHA-256 inventories. They must be byte-identical to the pre-change inventories.

Do not call the runner's report writer and do not create files inside either trial root.

## Validation Checklist

Run focused optimization tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_ordering \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab \
  -q -p no:cacheprovider
```

Run full trendline-family tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_ordering \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider
```

Run integration/non-interference:

```bash
PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_ordering \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_ordering \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider
```

Static checks:

```bash
ruff check \
  src/libs/models/trendline_family/optimization/evaluator.py \
  tests/models/trendline_family/optimization

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_ordering_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family/optimization

git diff --check
```

Reindex codebase-memory and confirm `run_phase_i_evaluation` still has no production runtime callers.

## Acceptance Criteria

- no network access occurred;
- no Phase-I real-data rerun occurred;
- no trial-root file changed;
- no artifact schema or recommendation decision semantics changed;
- no-finalist recommendation identity is invariant to trial ordering;
- tamper/integrity checks remain strict;
- existing v2 bundle passes independent verification;
- verified decision remains `REJECT` with no finalist;
- all focused/full/non-interference tests pass;
- no runtime, YAML, RegimeV2, signal, or selection changes.

## Stop Conditions

Stop and report without widening scope if:

- canonical trial ordering does not reproduce the existing persisted recommendation ID;
- the existing v2 bundle fails for any second reason after ordering remediation;
- a fix would require changing persisted artifacts or recommendation schema;
- any real-data evaluation, network request, holdout action, or runtime modification would be required;
- codebase-memory reveals a production runtime dependency.

## Mandatory Completion Report

Return:

- Scope Executed
- Root Cause Confirmed
- Canonical Ordering Change
- Files Changed
- Regression Tests
- Existing V2 Bundle Verification
- Trial-Root Byte Integrity
- Recommendation Decision
- Runtime And Regime Isolation
- Validation Results
- Codebase-Memory
- Known Gaps
- Next Handoff

Write:

```text
plans/coder-to-review-trendline-family-phase-i-recommendation-ordering-v1.md
```

Stop after verification. Do not interpret candidate metrics, generate the trial report, request market data, or begin tracker work.
