# Trendline Family Model — Phase I Final Remediation Re-review

## Current Mode

Independent Phase-I approval re-review after the final trust-boundary remediation.

## Decision

**Revision required. Real-data optimization, research conclusions, and every runtime/config promotion remain blocked.**

The remediation correctly closes the previously reported generated-path defects:

- anonymous evaluators now fail closed unless an explicit `StageEvaluationSpec` is supplied;
- validation and holdout execution verify the supplied evaluator specification before running a window or registering holdout access;
- persisted aggregates, objective gates, deterministic finalist choice, and promotion recommendations are rederived from persisted window evidence;
- the completion index binds the files currently declared by the run;
- missing and extra artifact path keys reject;
- no runtime, YAML, RegimeV2, selection, signal, strategy, risk, execution, or promotion path changed.

Independent adversarial review found three remaining persisted-evidence blockers.

---

## Review Scope

Reviewed:

```text
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/optimization/runner.py
src/libs/models/trendline_family/optimization/__init__.py

tests/models/trendline_family/optimization/support.py
tests/models/trendline_family/optimization/test_phase_i_remediation.py
tests/models/trendline_family/optimization/test_runner_and_artifacts.py
```

Replayed the previously reported evaluator-substitution, forged-promotion, incomplete-path, objective-gate, counterfactual, and run-identity boundaries.

---

## Verified Closed Findings

### Evaluator identity fails closed during execution

`resolve_evaluation_spec(...)` now requires either:

- an evaluator-owned typed specification; or
- an explicit immutable `StageEvaluationSpec`.

`run_validation_trial(...)` and `evaluate_holdout_once(...)` verify:

```text
resolved evaluator spec ID == trial.evaluation_spec.spec_id
```

Holdout additionally verifies:

```text
resolved evaluator spec ID == finalist_freeze.evaluation_spec_id
```

Mismatch rejects before evaluator execution and before holdout-open registration.

### Aggregate, gate, finalist, and recommendation truth

`VerifiedRunBundle` now rederives:

- aggregate metrics from persisted windows;
- direction-aware objective gates;
- deterministic validation finalist;
- validation/holdout improvement;
- final promotion recommendation.

The earlier forged `PROMOTE` over a worse holdout now rejects.

### Current artifact-path closure

The completion index and verifier reject:

- missing indexed trial paths;
- missing indexed counterfactual paths;
- missing holdout/freeze/audit paths;
- unexpected extra path keys;
- summary/report identity drift;
- mismatched artifact kinds and run IDs.

### Runtime isolation

Verified:

- no runtime imports of the optimization package;
- no YAML reads/writes in optimization;
- no external fetching;
- no RegimeV2 usage for research or promotion;
- no active decision-path changes;
- no real-data trial;
- no Phase-J or runtime-promotion implementation.

---

# Blocking Findings

## P0 — Persisted parameter-effect audits are still trusted, not rederived

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
  ParameterEffectAudit
  TrialResult.__post_init__

src/libs/models/trendline_family/optimization/evaluator.py
  verify_persisted_trial_result

src/libs/models/trendline_family/optimization/artifacts.py
  VerifiedRunBundle._verify_derived_truth
```

The verifier confirms that an audit points to a persisted counterfactual result, but does not independently derive whether that counterfactual actually changed the owned-stage fingerprint or leaked into the forbidden fingerprint.

Independent probe:

```text
real full-trial stage fingerprint:          constant
real counterfactual stage fingerprint:      constant
real effect:                                false
real audit decision:                        reject
```

The audit was changed to:

```text
effect_detected:            true
leakage_detected:           false
observed_changed_outputs:   stage_output_fingerprint
decision:                   promote
```

The parent result, recommendation, completion index, and manifest were reidentified. Result:

```text
forged_parameter_audit_bundle_ACCEPTED
finalist created: true
recommendation: hold
```

The false audit changed the deterministic finalist outcome. A future holdout fixture could therefore turn forged audit evidence into a false promotion candidate.

### Required correction

Add one canonical persisted-audit verifier used by `VerifiedRunBundle`.

For every primary trial override, require exactly one counterfactual and one audit.

Derive and verify:

```text
counterfactual overrides
  == full-trial overrides with exactly the audited parameter reverted

counterfactual.trial.counterfactual_of_trial_id
  == full trial ID

counterfactual.trial.reverted_parameter
  == audit.parameter_name

effect_detected
  == full stage fingerprint != counterfactual stage fingerprint

leakage_detected
  == full forbidden fingerprint != counterfactual forbidden fingerprint
     OR counterfactual did not complete

observed_changed_outputs
  == derived changed owned outputs

decision
  == PROMOTE only when effect is true and leakage is false
```

The true resolved baseline value must also be verifiable. Persist one immutable baseline-parameter audit for the searched stage, or persist the canonical resolved configuration slice needed to prove:

```text
audit.baseline_value == resolved baseline value
counterfactual override value == audit.baseline_value
```

A baseline hash alone cannot prove the decoded parameter value.

Reject:

- missing audit;
- duplicate audit;
- extra audit for an untuned parameter;
- missing counterfactual;
- counterfactual changing more than one override;
- false effect/leakage claims;
- false baseline values;
- forged audit decisions.

---

## P0 — Completion index does not prove the complete attempted grid

Locations:

```text
src/libs/models/trendline_family/optimization/artifacts.py
  CompletionArtifactIndex
  build_completion_artifact_index
  _verify_completion_index
  VerifiedRunBundle

src/libs/models/trendline_family/optimization/runner.py
  run_phase_i_evaluation
```

The completion index exactly binds the `trials` sequence supplied to it, but it does not derive the expected trial request set from the manifest search space.

Independent probe:

```text
manifest search space:
  candidate.lookback_bars = [180, 200]

original primary trials: 2
persisted primary trials: 1
```

After removing one primary trial, the recommendation and completion index were recomputed. The manifest retained the same semantic run ID and the original two-value search space.

Result:

```text
recomputed_index_missing_attempt_ACCEPTED
original trial count: 2
persisted trial count: 1
same run ID: true
```

The current missing-path tests only prove that files cannot disappear while the old completion index remains unchanged. They do not prove that the completion index itself represents every trial required by the semantic run request.

### Required correction

Bind the expected primary trial request set before execution.

Recommended approach:

1. Deterministically enumerate the manifest search space with the declared search strategy and `maximum_trial_count`.
2. Build every expected primary `TrialConfig` identity from:
   - stage;
   - dataset hash;
   - fold-plan ID;
   - baseline config hash;
   - complete objective;
   - evaluator specification;
   - seed;
   - model/config versions;
   - parameter overrides.
3. Persist the sorted expected primary trial IDs in the semantic run manifest, or in a pre-execution request index whose ID participates in the run ID.
4. Require the finalized completion index to contain exactly that set, including failed and invalid trials.
5. Reject a recomputed completion index that omits or adds any expected request.

Counterfactual request completeness should be derived from the independently verified primary-trial audit plan.

Add adversarial tests that remove one trial and recompute:

- result IDs;
- recommendation;
- completion index;
- manifest envelope;
- all artifact envelope IDs.

The bundle must still reject because the semantic request requires the missing trial.

---

## P1 — Persisted finalist-freeze evaluator identity is not cross-bound to the winner

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
  FinalistFreeze

src/libs/models/trendline_family/optimization/artifacts.py
  VerifiedRunBundle.__post_init__
  VerifiedRunBundle._verify_derived_truth
```

The generated holdout path correctly verifies evaluator continuity. The persisted bundle does not independently require:

```text
finalist_freeze.evaluation_spec_id
  == deterministic winner.trial.evaluation_spec.spec_id
  == manifest stage evaluation spec ID
```

Independent probe changed the freeze evaluator specification to an unrelated ID, then recomputed the freeze, audits, manifest, completion index, and run ID.

Result:

```text
forged_freeze_evaluator_spec_ACCEPTED
winner spec:  canonical typed spec ID
freeze spec:  forged-spec-id
```

The false bundle received a different run ID, but it was still accepted as internally valid holdout provenance.

### Required correction

During bundle verification require:

```text
finalist_freeze.stage == deterministic winner stage
finalist_freeze.objective == deterministic winner objective
finalist_freeze.evaluation_spec_id == winner.trial.evaluation_spec.spec_id
finalist_freeze.evaluation_spec_id == manifest stage evaluation spec ID
```

Require the baseline and finalist holdout trial specifications to equal the same frozen evaluator specification.

Add equivalent checks for the frozen objective and fold plan.

---

## Bounded Remediation Scope

Expected files:

```text
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/evaluator.py
src/libs/models/trendline_family/optimization/artifacts.py
src/libs/models/trendline_family/optimization/runner.py
src/libs/models/trendline_family/optimization/__init__.py

tests/models/trendline_family/optimization/test_phase_i_remediation.py
focused support/tests only
```

No changes are required in:

```text
candidate provider/runtime
tracker runtime
interaction lifecycle runtime
MTF runtime
RegimeV2 or its adapters
signal worker
SelectionLayer
strategy/risk/execution
configs/trendline_family.yaml
```

The regime module remains WIP and excluded from all real-data Phase-I research.

---

## Mandatory Adversarial Tests

Add tests proving:

1. An audit claiming an effect when full and counterfactual stage fingerprints are equal rejects.
2. An audit hiding forbidden-output leakage rejects.
3. A counterfactual changing two parameters rejects.
4. A counterfactual not reverting to the canonical baseline value rejects.
5. Missing, duplicate, and extra audits reject.
6. Removing one expected primary trial and recomputing every downstream ID still rejects.
7. Failed and invalid expected trials remain mandatory artifacts.
8. A completion index with a trial not requested by the manifest rejects.
9. A finalist freeze with a mismatched evaluator specification rejects after all IDs are recomputed.
10. A finalist freeze with a mismatched objective rejects.
11. Existing valid bundles remain order-invariant and round-trip cleanly.

---

## Validation Evidence

Independent suites reproduced:

```text
Optimization:                              26 passed
Full trendline-family:                    319 passed
Family + adapters + projected runtime:    347 passed
Active RegimeV2/selection/signals:        148 passed, 1 existing warning
```

Static checks:

```text
Ruff:             passed
compileall:       passed
git diff --check: passed
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   41,495
edges:   137,459
status:  ready
```

`run_phase_i_evaluation` has no inbound production callers. Direct source inspection remains necessary because the canonical package is untracked and `detect_changes` omits it.

---

## Approval Boundary

Phase I is not yet approved.

Real-data research remains blocked, including:

- candidate/geometry trials;
- tracker trials;
- interaction/event trials;
- MTF policy trials;
- all promotion recommendations used for decision-making.

RegimeV2 ablation remains separately deferred because the regime module is WIP.

After this bounded correction, rerun the full approval gate. Do not create the research notebook, run real-market optimization, or modify runtime configuration until approval.
