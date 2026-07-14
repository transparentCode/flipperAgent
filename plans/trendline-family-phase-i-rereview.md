# Trendline Family Model — Phase I Remediation Re-review

## Current Mode

Independent Phase-I remediation re-review.

## Decision

**Revision required. Real-data optimization and every promotion decision remain blocked.**

The remediation correctly closes the original generated-path defects in marginal parameter auditing, direction-aware objective aggregation, typed concrete evaluator identities, warm-state holdout replay, macro F1, and basic artifact deserialization.

Three fail-open trust boundaries remain:

1. custom evaluators can use an empty semantic identity, and holdout can substitute a different evaluator after finalist freeze;
2. objective gates and promotion decisions are still trusted as caller-supplied claims rather than recomputed from persisted results;
3. artifact verification does not bind the complete attempted-trial set, so primary and counterfactual trial artifacts can disappear without invalidating the bundle.

No runtime trendline, RegimeV2, signal-worker, strategy, risk, execution, Phase-G, or Phase-H redesign is required.

---

## Review Scope

Reviewed:

```text
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/folds.py
src/libs/models/trendline_family/optimization/metrics.py
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/candidate_optimizer.py
src/libs/models/trendline_family/optimization/tracker_optimizer.py
src/libs/models/trendline_family/optimization/interaction_optimizer.py
src/libs/models/trendline_family/optimization/ablation.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/optimization/runner.py
src/libs/models/trendline_family/optimization/__init__.py
```

Focused tests reviewed:

```text
tests/models/trendline_family/optimization/test_phase_i_remediation.py
tests/models/trendline_family/optimization/test_runner_and_artifacts.py
tests/models/trendline_family/optimization/test_folds_and_contracts.py
tests/models/trendline_family/optimization/test_stage_replays.py
tests/models/trendline_family/optimization/test_ablation.py
tests/models/trendline_family/optimization/test_shadow_invariance.py
```

---

## Verified Closed Findings

### Marginal parameter-effect audits

The runner now executes one controlled counterfactual per tuned parameter:

```text
full trial
versus
same trial with exactly one parameter reverted to its resolved baseline value
```

Each `ParameterEffectAudit` binds:

- the real resolved baseline value;
- trial value;
- counterfactual trial ID;
- counterfactual result ID;
- stage-output effect;
- forbidden-output leakage.

Independent probe with one effective parameter and one inert, non-leaking parameter:

```text
candidate.lookback_bars
  baseline: 240
  trial:    180
  effect:   true
  leakage:  false
  decision: promote

candidate.min_bars
  baseline: 40
  trial:    50
  effect:   false
  leakage:  false
  decision: reject

finalist selected: false
```

The previous aggregate-attribution defect is closed for the normal runner path.

### Direction-aware objective aggregation

Verified:

- maximized objectives use minimum window value as worst;
- minimized objectives use maximum window value as worst;
- `minimum_fold_coverage` is evaluated;
- `maximum_failure_rate` is evaluated;
- lower floors and upper ceilings are direction-specific;
- allowed degradation is applied to worst-window stability rather than as an undisclosed primary-score margin;
- validation and holdout results receive typed `ObjectiveGate` records.

### Complete concrete evaluator identities

Concrete evaluators now provide typed identities:

```text
CandidateEvaluationSpec
TrackerEvaluationSpec
InteractionEvaluationSpec
RegimeAblationEvaluationSpec
```

Verified bound inputs include:

- candidate provider identity/state and outcome policy;
- frozen candidate stream identity;
- frozen source-snapshot stream identity;
- interaction outcome policy and tick size;
- ablation scorer identity/state, threshold, label column, and feature-frame hashes.

Changing candidate outcome horizon changes the trial identity.

### Stateful holdout window

`HoldoutPlan` now persists a pre-holdout warmup window. Tracker holdout replay begins at:

```text
holdout.warmup.start_position
```

rather than the first holdout row.

Finalist freeze and two typed holdout-open audits are present in the normal runner path.

### Macro F1

Binary metrics now persist:

```text
positive_f1
negative_f1
macro_f1 = mean(positive_f1, negative_f1)
```

Independent fixture result:

```text
positive F1 = 0.6666666667
negative F1 = 0.8
macro F1    = 0.7333333333
```

### Basic artifact contracts

Verified:

- artifact envelopes recompute IDs;
- typed deserializers exist for the main Phase-I contracts;
- envelope run IDs are checked;
- fold plan, trial, evaluator, objective, and baseline-config identities are cross-checked;
- frozen finalist and holdout-open audits are persisted;
- ordinary cross-run envelope substitution rejects;
- runtime YAML remains untouched.

---

# Remaining Blocking Findings

## P0 — Evaluator identity remains fail-open and holdout semantics can be substituted

Locations:

```text
src/libs/models/trendline_family/optimization/evaluator.py
  resolve_evaluation_spec
  run_validation_trial
  evaluate_holdout_once
```

### Empty generic evaluator identity

When an evaluator does not implement `evaluation_spec()`, the resolver returns:

```text
StageEvaluationSpec(
    spec_type="generic_offline_evaluator",
    semantic_inputs={},
)
```

Two different evaluators therefore receive the same semantic evaluator identity.

Independent probe:

```text
generic_spec_same true
trial_id_same     true
result_id_same    false
metric A          0.7
metric B          0.9
```

The same trial ID can describe different evaluation behavior.

This also affects `run_phase_i_evaluation`, because its run ID binds that empty generic spec rather than the actual callable semantics.

### Holdout evaluator substitution

`evaluate_holdout_once` validates freeze/audit/result identities but does not resolve the supplied evaluator and compare its spec with:

```text
validation_finalist.trial.evaluation_spec.spec_id
finalist_freeze.evaluation_spec_id
```

A validation finalist created with evaluator A was opened on holdout using evaluator B with a different typed spec:

```text
validation evaluator spec:
trendline-family-stage-evaluation-spec_56c158...

holdout evaluator spec:
trendline-family-stage-evaluation-spec_4e4fe0...

mismatched_holdout_evaluator_ACCEPTED
holdout metric = 0.95
```

The audit proves that a frozen trial was opened, but not that the frozen evaluator semantics were used.

### Required correction

Fail closed on evaluator identity.

1. Remove the empty `generic_offline_evaluator` fallback from semantic execution paths.
2. Require either:
   - an evaluator implementing `evaluation_spec()`; or
   - an explicit immutable `StageEvaluationSpec` supplied by the caller and verified against the stage.
3. Before any validation or holdout evaluation, require:

```text
resolved supplied evaluator spec ID == trial.evaluation_spec.spec_id
```

4. Before registering a holdout opening, additionally require:

```text
resolved supplied evaluator spec ID == finalist_freeze.evaluation_spec_id
```

5. A mismatch must reject before evaluating a window or recording the holdout-open request.
6. Do not derive semantic identity only from a callable module/name; custom callable behavior must be represented by an explicit typed spec/version/hash.

Required adversarial tests:

- two different callables without explicit specs reject;
- two explicit custom specs produce different trial and run IDs;
- validation trial executed with a mismatched evaluator rejects;
- holdout evaluator-spec substitution rejects before opening;
- concrete candidate/tracker/interaction/ablation evaluators still pass;
- identical audited evaluator replay remains deterministic.

---

## P0 — Objective and promotion truth is self-declared, not derived during deserialization

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
  ObjectiveGate.__post_init__
  TrialResult.__post_init__
  PromotionRecommendation.__post_init__

src/libs/models/trendline_family/optimization/artifacts.py
  VerifiedRunBundle.__post_init__
  verify_artifact_bundle

src/libs/models/trendline_family/optimization/evaluator.py
  build_objective_gate
  build_promotion_recommendation
```

The normal runner derives correct gates and recommendations. The persisted contracts and bundle verifier do not independently reproduce that derivation.

### Internally impossible passing objective gate

This gate was accepted:

```text
required folds:          3
defined primary folds:   0
failed/invalid windows:  3
fold coverage:           0.0
failure rate:            1.0
primary value:           None
worst loss:              99.0
required worst ceiling:  1.0
comparable population:   false
passed:                  true
rejection reasons:       ()
```

Result:

```text
self_declared_false_PROMOTE_ACCEPTED
```

`ObjectiveGate` checks only that a passing gate has no rejection reasons. It does not derive whether the fields require rejection.

### Worse holdout can be relabeled PROMOTE

A valid offline run produced:

```text
validation: candidate improved
holdout baseline:  0.5
holdout finalist:  0.4
objective: maximize
actual recommendation: REJECT
```

All four hard gates were `passed=True`, because the gates represent sample/coverage/stability validity and not relative improvement.

The recommendation was changed to `PROMOTE`, the recommendation ID and artifact-envelope ID were recomputed, and the bundle verifier accepted it:

```text
worse_holdout_PROMOTE_bundle_ACCEPTED
```

`VerifiedRunBundle` verifies that referenced results exist, but it does not recompute:

- each result's aggregate metrics from its windows;
- each result's objective gate from windows and the fold plan;
- validation finalist eligibility and ranking;
- validation improvement;
- holdout improvement;
- recommendation audits against the actual finalist;
- the expected final `PROMOTE/HOLD/REJECT` decision.

Content addressing therefore stabilizes a false promotion claim instead of rejecting it.

### Required correction

Create one shared pure truth path used by runtime generation and persisted verification.

At minimum:

1. Recompute aggregate metrics from every persisted `WindowResult` and require exact equality with `TrialResult.aggregate_metrics`.
2. For validation results, require the exact window set:

```text
one validation window for every FoldPlan.fold_id
no missing, duplicate, unrelated, or holdout windows
```

3. For holdout results, require exactly one window bound to:

```text
FoldPlan.holdout.holdout_plan_id
window_kind == "holdout"
```

4. Recompute each `ObjectiveGate` from the persisted result, expected window count, objective, and baseline population. Require exact semantic equality.
5. Make `ObjectiveGate` reject obviously inconsistent `passed/rejection_reasons` from its own fields even before bundle verification.
6. Recompute the validation finalist from the complete persisted primary-trial set and require it to equal the frozen/recommended finalist.
7. Require the finalist to be:
   - distinct from baseline;
   - a primary trial in the persisted trial set;
   - completed;
   - validation-gate passing;
   - independently parameter-audited;
   - selected by the documented deterministic ranking.
8. Require recommendation audits to equal the finalist's persisted audits exactly.
9. Rebuild the expected recommendation from loaded validation and holdout results and require complete semantic equality, including the decision.
10. A `PROMOTE` bundle must independently prove direction-aware validation and holdout improvement, not merely four `passed=True` hard gates.

Required adversarial tests:

- impossible passing `ObjectiveGate` rejects;
- aggregate metric changed with recomputed result ID rejects at bundle verification;
- one validation fold removed with all IDs recomputed rejects;
- validation window replaced by holdout-kind window rejects;
- worse holdout relabeled `PROMOTE` with recomputed IDs rejects;
- recommendation audits differing from finalist audits reject;
- baseline used as its own finalist rejects;
- non-winning trial frozen as finalist rejects;
- valid generated `PROMOTE`, `HOLD`, and `REJECT` bundles verify.

---

## P0 — Artifact verification does not bind the complete attempted-trial set

Locations:

```text
src/libs/models/trendline_family/optimization/artifacts.py
  RunManifest
  _summary_payload
  write_phase_i_artifacts
  verify_artifact_bundle
```

The verifier loads whichever `trial:*` and `counterfactual:*` entries are present in the caller-supplied path mapping.

Neither the manifest nor a required typed artifact index binds the exact attempted trial/result set.

Independent probe:

```text
actual attempted primary trials: 1

verification paths supplied:
- manifest
- fold_plan
- baseline
- recommendation

trial artifact omitted
counterfactual artifact omitted
summary omitted

missing_attempted_trials_ACCEPTED
```

This violates the Phase-I rule that all attempted, failed, invalid, and counterfactual trials remain persisted and auditable.

The current `stage_summary` contains trial result IDs, but:

- it is not required by `verify_artifact_bundle`;
- its content is not cross-validated;
- counterfactual IDs are not fully indexed;
- it is not used to reject missing or extra artifacts.

### Required correction

Add one typed content-addressed completion/artifact index.

It must bind at least:

```text
run ID
baseline validation result ID
ordered primary trial ID -> result ID pairs
ordered counterfactual trial ID -> result ID pairs
finalist validation result ID or None
baseline/finalist holdout result IDs or None
finalist freeze ID or None
holdout-open audit IDs
recommendation ID
summary/report semantic IDs where applicable
completion status
```

The verifier must require exact set equality:

```text
indexed primary trials       == persisted primary trial artifacts
indexed counterfactuals      == persisted counterfactual artifacts
nested counterfactuals       == indexed counterfactuals
indexed holdout/freeze/audit == persisted holdout/freeze/audit artifacts
```

No required artifact may disappear merely because its path entry was omitted.
No unexpected extra trial artifact may be accepted.

The typed index should be part of the finalized run identity or be explicitly bound by the finalized manifest.

Required adversarial tests:

- remove one completed primary trial artifact -> reject;
- remove one failed/invalid primary trial artifact -> reject;
- remove one counterfactual artifact -> reject;
- add an unrelated trial artifact -> reject;
- alter stage summary/index with recomputed envelope ID -> reject;
- omit the summary/index path -> reject;
- valid complete bundle verifies independent of input mapping order.

---

## Blast Radius

Expected remediation remains confined to:

```text
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/optimization/runner.py
src/libs/models/trendline_family/optimization/ablation.py  # only for explicit evaluator-spec flow
focused Phase-I tests
```

Small changes to the concrete evaluator files are acceptable only to expose or verify their existing typed evaluation specs.

Do not modify:

```text
configs/trendline_family.yaml
single-timeframe tracker runtime
Phase-F event runtime
Phase-G grouping/runtime
Phase-H MTF runtime
RegimeV2 active code
signal worker
probability/overlay/MoE
SelectionLayer
strategy/risk/execution
```

---

## Validation Evidence

Independent regression results:

```text
Phase-I optimization suite:
20 passed

Full trendline-family suite:
313 passed

Trendline-family + adapters + projected runtime:
341 passed

Active RegimeV2 + selection + signals:
148 passed, 1 pre-existing OpenTelemetry warning
```

Static validation:

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,451
edges:   137,269
status:  ready
```

`run_phase_i_evaluation` has no inbound production callers.

`detect_changes` remains unreliable for the untracked canonical package and returned `project not found` through the bare CLI invocation. Direct source inspection, git status, and codebase-memory traces were used.

Verified absent:

```text
runtime imports of trendline_family.optimization
YAML reads in optimization code
legacy trendline runtime imports
external market-data fetching
active decision-path changes
runtime config promotion
real-data optimization execution
```

---

## Approval Status

**Request changes.**

The package is not yet safe to use for real-data research selection because the same semantic trial can execute different evaluator logic, a frozen validation result can be evaluated on holdout with substituted semantics, and a tampered artifact set can claim `PROMOTE` over worse holdout evidence while omitting attempted trials.

---

## Bounded Codex Remediation Prompt

```text
Implement only the final Phase-I trust-boundary remediation described in:

- plans/trendline-family-phase-i-review.md
- plans/trendline-family-phase-i-rereview.md
- plans/trendline-family-phase-h-approval.md

Do not run real-market optimization.
Do not promote any parameter or feature.
Do not modify runtime YAML or active decision paths.

Required corrections:

1. Make evaluator identity fail closed.
   - Remove the empty generic evaluator semantic identity from executable paths.
   - Require evaluator.evaluation_spec() or an explicit immutable StageEvaluationSpec.
   - Verify the supplied evaluator spec against TrialConfig before validation.
   - Verify it against both TrialConfig and FinalistFreeze before holdout opening.
   - Reject mismatches before evaluator execution or holdout registration.

2. Make persisted objective and promotion evidence derived truth.
   - Recompute aggregate metrics from persisted windows.
   - Validate exact validation fold IDs/kinds and exact holdout window ID/kind.
   - Recompute direction-aware ObjectiveGate records from results and FoldPlan.
   - Require exact equality with persisted gates.
   - Recompute finalist eligibility/ranking from the complete primary-trial set.
   - Require the frozen/recommended finalist to be the deterministic winner, distinct from baseline.
   - Require recommendation audits to equal finalist audits.
   - Rebuild the expected promotion recommendation from persisted validation and holdout evidence.
   - Reject any semantic mismatch, including worse-holdout PROMOTE relabeling with all IDs recomputed.
   - Make ObjectiveGate reject internally impossible passed states.

3. Bind complete artifact-set membership.
   - Add a typed content-addressed completion/artifact index.
   - Bind every primary trial and result, every counterfactual, holdout result, finalist freeze, holdout audit, recommendation, and required summary/index artifact.
   - Require exact set equality during verification.
   - Missing failed/invalid/completed/counterfactual artifacts must reject.
   - Unexpected artifacts must reject.

4. Preserve all currently passing counterfactual, direction-aware objective,
   holdout warmup, typed concrete evaluator, macro-F1, runtime-invariance,
   and atomic-write behavior.

Required new adversarial tests:

- different custom evaluators without explicit specs reject;
- validation evaluator-spec mismatch rejects;
- holdout evaluator substitution rejects before opening;
- impossible passing ObjectiveGate rejects;
- missing/retyped validation fold rejects after all IDs are recomputed;
- worse holdout relabeled PROMOTE rejects after recommendation/envelope IDs are recomputed;
- recommendation/finalist audit mismatch rejects;
- non-winning or baseline finalist rejects;
- omitted primary trial rejects;
- omitted failed/invalid trial rejects;
- omitted counterfactual rejects;
- extra unrelated trial rejects;
- valid complete bundles for PROMOTE/HOLD/REJECT verify.

Run:

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_final \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

/Users/aloobhujia/.local/bin/ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_final_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters

git diff --check

Reindex codebase-memory and report project, node count, edge count, status,
changed-file scope, and impacted symbols.

Stop after Phase-I remediation and synthetic fixtures.
Do not run a real-data candidate trial.
Do not begin runtime promotion.
```
