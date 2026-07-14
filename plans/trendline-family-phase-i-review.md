# Trendline Family Model — Phase I Review

## Current Mode

Independent Phase-I architecture, quant-safety, and persistence review.

## Decision

**Revision required. Real-data optimization and runtime promotion remain blocked.**

The implementation establishes a useful offline package boundary and passes all reported regression suites. Independent adversarial review found five blocking evaluation-integrity defects and one metric correctness defect:

1. multi-parameter trials falsely attribute one observed stage change to every parameter;
2. objective and promotion gates can select unstable or under-covered trials;
3. trial/run identities do not bind the complete semantic evaluation request;
4. tracker and interaction holdout replay cold-start without pre-holdout state;
5. persisted artifacts have no deserialization/cross-artifact truth validation and permit false promotion bundles;
6. the reported `macro_f1` is positive-class F1 rather than macro F1.

No runtime trendline, RegimeV2, signal, strategy, risk, execution, Phase-G, or Phase-H redesign is required.

---

# Review Scope

Reviewed production files:

```text
src/libs/models/trendline_family/optimization/__init__.py
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
```

Reviewed focused tests:

```text
tests/models/trendline_family/optimization/support.py
tests/models/trendline_family/optimization/test_folds_and_contracts.py
tests/models/trendline_family/optimization/test_stage_replays.py
tests/models/trendline_family/optimization/test_ablation.py
tests/models/trendline_family/optimization/test_runner_and_artifacts.py
tests/models/trendline_family/optimization/test_shadow_invariance.py
```

---

# Verified Positive Boundaries

## Offline package isolation

Verified:

- no active runtime module imports `trendline_family.optimization`;
- no optimization module reads YAML;
- no exchange or external-data fetch exists inside objectives;
- no Docker service, worker, database, distributed optimizer, RL, neural model, or live hot-reload was added;
- the caller chooses the artifact output directory;
- runtime config objects are reconstructed immutably rather than mutated;
- runtime YAML is not changed;
- no active RegimeV2, probability, overlay, MoE, selection, strategy, risk, or execution consumption was introduced.

## Dataset and fold foundation

Verified:

- timezone-aware UTC index required;
- strict ordering and duplicate rejection;
- required finite OHLCV validation;
- positive prices, non-negative volume, and OHLC relation checks;
- incomplete-bar marker rejection;
- deterministic dataset hashing;
- expanding and rolling fold construction;
- chronological validation;
- purge must cover the declared label horizon;
- validation embargo and untouched holdout separation;
- content-addressed fold and holdout identities.

## Stage separation

Verified:

- explicit candidate, tracker, interaction, and regime-ablation stages;
- cross-stage parameter names reject;
- candidate replay uses confirmed prefixes;
- tracker replay consumes a frozen candidate stream;
- interaction replay consumes frozen family snapshots;
- MTF remains an immutable shadow feature group;
- bounded deterministic grid enumeration;
- failed and invalid trials are retained by the runner;
- per-file JSON replacement is atomic.

## Shadow invariance

The active RegimeV2 regression remains byte-equal before and after a compact Phase-I fixture run.

---

# Blocking Findings

## P0 — Parameter-effect audits do not isolate individual parameters

Location:

```text
src/libs/models/trendline_family/optimization/evaluator.py
  attach_parameter_effect_audits
```

The implementation calculates one whole-trial stage fingerprint and one whole-trial forbidden-output fingerprint. It then assigns the same comparison result to every parameter in the trial.

Consequences:

- if one parameter changes the output, every co-traveling parameter is marked effective;
- an inert parameter can receive `PROMOTE` merely because another parameter changed the stage;
- a leaking parameter can contaminate every parameter's audit without identifying the source;
- `baseline_value` is read from `baseline.trial.parameter_overrides`, which is empty, so real baseline config values are reported as `None`.

Independent probe:

```text
trial overrides:
  candidate.lookback_bars = 180   # fixture changes stage output
  candidate.min_bars      = 40    # fixture deliberately inert

reported audits:
  candidate.lookback_bars baseline=None effect=True decision=promote
  candidate.min_bars      baseline=None effect=True decision=promote
```

This violates the required rule that every searched parameter must demonstrate an owned-stage effect independently.

### Required correction

For each parameter in a completed trial, create a controlled counterfactual audit.

Recommended marginal audit:

```text
full trial configuration
versus
same configuration with exactly this parameter reverted to its real baseline value
```

Persist and bind:

- actual baseline value from `ResolvedTrendlineFamilyConfig`;
- full-trial value;
- counterfactual trial/result identity;
- expected affected outputs;
- observed affected outputs;
- forbidden output fingerprints;
- effect and leakage decisions.

A multi-parameter finalist is eligible only when every parameter independently passes its owned-stage audit. Do not infer per-parameter effect from one aggregate trial fingerprint.

Add adversarial tests for:

- one effective plus one inert parameter;
- one effective plus one leaking parameter;
- two parameters with the same value as baseline;
- conditional parameter effect under a documented marginal-audit policy;
- true baseline values in persisted audits.

---

## P0 — Objective, stability, and promotion gates can accept invalid finalists

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
  ObjectiveSpec

src/libs/models/trendline_family/optimization/metrics.py
  aggregate_window_metrics

src/libs/models/trendline_family/optimization/evaluator.py
  _eligible_validation_trial
  _improves_over_baseline
  select_validation_finalist
  build_promotion_recommendation
```

### Minimum fold coverage is not enforced

`ObjectiveSpec.minimum_fold_coverage` is validated but never used by selection.

Independent probe:

```text
minimum_fold_coverage = 1.0
defined primary-metric windows = 1
total validation windows = 3
selected = true
```

A trial with two undefined windows out of three was selected because one window produced an improved aggregate value.

### Maximum failure rate is not enforced

`ObjectiveSpec.maximum_failure_rate` is declared but has no selection or recommendation use.

There is no objective-level binding to stage failure metrics, partial invalid windows, or operational failure counts.

### Worst-window semantics are incorrect for minimization

`aggregate_window_metrics` always stores:

```text
<metric>__worst = min(window values)
```

For a minimized metric such as loss, Brier score, or log loss, the worst window is the maximum.

Independent probe:

```text
baseline loss windows:  [1.0, 1.0]
candidate loss windows: [0.0, 1.5]

candidate mean:          0.75
stored loss__worst:      0.0
actual worst loss:       1.5
selected:                true
```

The candidate was selected despite a validation window worse than baseline.

### Guard direction is one-sided

`worst_window_floor` is implemented only as a lower floor. Minimized objectives need an upper ceiling or a direction-aware worst-window guard.

`allowed_degradation` currently behaves as an extra required improvement margin in both directions rather than an explicitly documented tolerated degradation/stability rule.

### Promotion does not reapply complete gates

Holdout promotion checks only mean improvement and minimum sample count. It does not enforce:

- fold/window coverage;
- direction-aware worst-window guard;
- maximum failure rate;
- latency or churn limits;
- comparable evaluated populations;
- complete operational gates.

### Recommendation contract permits impossible promotion evidence

Independent contract probe:

```text
PromotionRecommendation(
    decision=PROMOTE,
    finalist_result_id=None,
    holdout_evidence={},
    parameter_effect_audits=(),
)
```

was accepted with a valid content-addressed recommendation ID:

```text
false_promote_ACCEPTED
```

Content addressing proves the false claim is stable; it does not prove the decision follows policy.

### Required correction

Implement one direction-aware objective evaluator used by validation selection, holdout evaluation, and recommendation construction.

It must derive and persist:

- required fold count;
- defined-primary-metric fold count;
- fold coverage ratio;
- failed/invalid window rate;
- direction-aware worst window;
- sample/row coverage;
- operational gate results;
- comparable-population evidence;
- primary and secondary metric decisions;
- exact rejection reasons.

Use explicit guard semantics, for example:

```text
maximize objective -> worst is minimum, optional lower floor
minimize objective -> worst is maximum, optional upper ceiling
```

A `PROMOTE` recommendation contract must reject unless it has:

- a completed frozen finalist;
- completed baseline and finalist validation evidence;
- completed baseline and finalist untouched-holdout evidence;
- passing parameter-effect/isolation audits;
- passing sample, coverage, worst-window, failure, latency/churn, and causality gates;
- a derived decision matching the persisted evidence.

Add tests for maximize and minimize objectives, partial undefined folds, failure-rate breaches, worst-window breaches, and impossible manually constructed promotion records.

---

## P0 — Trial and run identities omit semantic evaluation inputs

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
  TrialConfig

src/libs/models/trendline_family/optimization/artifacts.py
  RunManifest

src/libs/models/trendline_family/optimization/runner.py
  run_phase_i_evaluation
```

### Trial identity does not bind evaluator semantics

`TrialConfig` can bind caller-supplied `evaluation_context`, but the stage APIs do not populate it with their actual semantic inputs.

Missing trial identity evidence includes:

Candidate stage:

- provider identity/version;
- `CandidateOutcomePolicy` horizon, ATR window, thresholds, and policy version.

Tracker stage:

- frozen candidate stream ID;
- source candidate-config identity.

Interaction stage:

- frozen family snapshot stream ID;
- label column;
- target event state;
- interaction outcome-policy version;
- tick-size policy.

Regime ablation:

- scorer identity/version/hash;
- scorer parameters;
- threshold;
- label column/policy;
- active baseline feature-frame hash;
- shadow feature-frame hash.

Independent candidate probe:

```text
same TrialConfig / same trial_id
outcome horizon 1 versus outcome horizon 4
evaluation_context = {}
result IDs differ
```

The same semantic trial ID therefore refers to different evaluation requests.

### Run ID does not bind the full run request

`RunManifest` includes objective versions but not complete `ObjectiveSpec` payloads. It also omits:

- `maximum_trial_count`;
- holdout-open policy;
- frozen finalist identity;
- stage evaluator/input audit;
- label/outcome/scorer identities.

Independent probes:

```text
same objective_version, different primary metrics -> same run_id
same validation run, open_holdout false versus true -> same run_id
recommendations: HOLD versus PROMOTE under the same run_id
```

### Required correction

Add immutable typed stage evaluation specifications, for example:

```text
CandidateEvaluationSpec
TrackerEvaluationSpec
InteractionEvaluationSpec
RegimeAblationEvaluationSpec
```

Each must bind all semantic evaluator inputs and upstream frozen artifact IDs.

Include the stage evaluation spec in `TrialConfig.identity_payload`.

Expand the run semantic identity to include:

- complete objective specs;
- maximum trial count and search strategy version;
- stage evaluation specs;
- holdout execution policy;
- finalist-freeze/holdout request identity when holdout is opened;
- label/outcome/scorer/source artifact identities;
- code/objective/schema versions.

Two runs that can produce different semantic recommendations must not share one run ID.

---

## P0 — Stateful holdout replay cold-starts at the holdout boundary

Locations:

```text
src/libs/models/trendline_family/optimization/folds.py
  HoldoutPlan

src/libs/models/trendline_family/optimization/tracker_optimizer.py
  TrackerEvaluator.__call__

src/libs/models/trendline_family/optimization/interaction_optimizer.py
  InteractionEvaluator.__call__

src/libs/models/trendline_family/optimization/evaluator.py
  evaluate_holdout_once
```

Validation tracker and interaction replays use a pre-validation warmup window.

Holdout replay uses:

```text
replay_start = holdout.window.start_position
```

Independent tracker probe:

```text
holdout_start:    48
replay_start:     48
warmup_bars_used: 0
```

Consequences:

- tracker holdout begins with an empty repository rather than the causal family state available before holdout;
- interaction holdout begins with no prior event episode;
- validation and holdout measure different state initialization policies;
- holdout can falsely reject or favor parameters based on cold-start churn and event delay.

`evaluate_holdout_once` also does not enforce that its input is the persisted selected finalist, and repeated calls are not represented by a typed holdout-open/finalist-freeze contract.

### Required correction

Extend `HoldoutPlan` with a causal warmup/seed contract.

Acceptable designs:

1. persist a pre-holdout warmup window and replay it without scoring; or
2. persist a canonical source state/snapshot identity at the holdout boundary.

Required invariants:

- no holdout label/outcome is read during warmup;
- the same initialization policy is used for baseline and finalist;
- tracker and interaction holdout score only holdout positions;
- source state is available exactly as of the holdout start;
- the holdout plan ID binds warmup/seed semantics.

Add a typed `HoldoutOpenAudit` that binds:

- selected validation finalist result ID;
- baseline result ID;
- fold plan and holdout plan IDs;
- reason;
- semantic request ID;
- one-time/idempotent policy;
- operational opened timestamp outside semantic IDs.

Arbitrary completed trials must not be able to open holdout through the public API.

---

## P0 — Persisted artifacts cannot be verified as one truthful run

Locations:

```text
src/libs/models/trendline_family/optimization/contracts.py
src/libs/models/trendline_family/optimization/folds.py
src/libs/models/trendline_family/optimization/artifacts.py
```

There are no public deserializers or artifact verification APIs:

```text
no from_dict implementations
no deserialize_* functions
no artifact-envelope verifier
no run-bundle verifier
```

The required JSON round-trip and stale/forged-ID rejection boundary therefore does not exist for persisted artifacts.

`write_phase_i_artifacts` validates neither cross-artifact identity nor run coherence.

Independent probe wrote one artifact set containing:

```text
manifest requested stage: candidate_geometry
baseline result stage:    candidate_geometry
recommendation stage:     tracker
recommendation decision:  PROMOTE
recommendation baseline:  unrelated-baseline
```

Result:

```text
mismatched_artifact_set_ACCEPTED
```

Every object can be individually content-addressed while the run bundle is causally false.

### Required correction

Add strict public round-trip loaders for:

- objective;
- fold/window/holdout plans;
- trial config;
- metrics and window results;
- trial results;
- parameter-effect audits;
- promotion recommendations;
- run manifests;
- artifact envelopes.

Add one typed verified run bundle or equivalent cross-validation function.

It must require exact agreement across:

- run ID;
- requested stage;
- asset/timeframe;
- dataset hash;
- fold/holdout plan IDs;
- baseline config hash;
- objective and evaluator spec;
- baseline/trial/result identities;
- finalist identity;
- holdout-open audit;
- recommendation stage and referenced result IDs;
- artifact kind and path role.

Persist baseline and finalist holdout results as explicit artifacts, not only nested untyped dictionaries inside the recommendation.

Reject stale or forged IDs even after nested IDs are recomputed when cross-artifact provenance is false.

---

# Major Metric Finding

## P1 — `macro_f1` is not macro F1

Location:

```text
src/libs/models/trendline_family/optimization/ablation.py
  _ablation_metrics
```

The implementation calculates positive-class F1 and stores it under `macro_f1`.

Independent probe:

```text
truth:       [1, 1, 0, 0]
prediction:  [1, 0, 0, 0]

reported macro_f1: 0.6666666667
true macro F1:     0.7333333333
```

Required correction:

- calculate positive-class F1;
- calculate negative-class F1;
- define `macro_f1` as their unweighted mean;
- handle one-class/undefined denominators explicitly;
- add confusion-matrix and asymmetric-class tests.

Do not use the current metric for promotion review.

---

# Validation Reproduced

## Optimization-focused suite

```text
12 passed
```

## Full trendline-family suite

```text
305 passed
```

## Trendline-family plus adapters and projected runtime

```text
333 passed
```

## Active RegimeV2, selection, and signals

```text
148 passed, 1 warning
```

The warning is the existing OpenTelemetry `LoggingHandler` deprecation.

## Static checks

```text
Ruff: passed
compileall: passed
git diff --check: passed
```

## Codebase-memory

```text
project: Users-aloobhujia-flipperAgent
nodes: 41,330
edges: 136,590
status: ready
```

The index confirms the new runner is offline-only and has no active-runtime caller. `detect_changes` still omits the untracked canonical package, so direct source inspection, tests, and git status remain the scope evidence of record.

---

# Blast Radius

Expected remediation remains within:

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
focused optimization tests
```

No changes are expected in:

```text
single-timeframe tracker runtime
Phase-F event runtime
Phase-G grouping/runtime persistence
Phase-H MTF runtime composition
RegimeV2 runtime
signal worker
probability/overlay/MoE
SelectionLayer
strategy/risk/execution
configs/trendline_family.yaml
```

Do not begin a real-data optimization run until this remediation is approved.

---

# Required Adversarial Tests

Add focused tests for:

1. effective parameter plus inert parameter does not promote the inert parameter;
2. real baseline values are persisted in every parameter audit;
3. one leaking parameter is identified independently;
4. minimum fold coverage rejects one-defined-of-three windows;
5. maximum failure-rate breach rejects;
6. minimized objective uses maximum as worst window;
7. maximized objective uses minimum as worst window;
8. direction-aware worst-window floor/ceiling;
9. validation and holdout apply identical hard gates;
10. false manual `PROMOTE` without finalist/holdout rejects;
11. two candidate outcome policies produce different trial IDs;
12. two frozen candidate/source streams produce different trial IDs;
13. two ablation scorers, thresholds, labels, or feature-frame hashes produce different trial IDs;
14. different full objective specs produce different run IDs;
15. holdout closed versus opened produces distinct typed run/holdout identities;
16. tracker holdout replays causal warmup/seed state;
17. interaction holdout carries causal prior event state;
18. arbitrary non-finalist cannot open holdout;
19. repeated conflicting holdout opens reject while identical replay is idempotent;
20. every contract JSON round-trips;
21. stale forged nested IDs reject;
22. artifact envelope ID mismatch rejects;
23. mismatched manifest/fold/result/recommendation bundle rejects;
24. recommendation result references must exist in the same verified bundle;
25. true macro F1 for asymmetric confusion matrices;
26. active outputs remain byte-identical after the remediated offline run.

---

# Codex Remediation Prompt

```text
Apply Phase-I remediation only.

Read:
- plans/trendline-family-phase-i-review.md
- plans/trendline-family-phase-h-approval.md
- plans/trendline-family-codex-phase-execution-plan.md
- plans/trendline-family-model-architecture-plan.md

Do not run real-market optimization.
Do not promote parameters or features.
Do not modify runtime YAML or active decision behavior.

Objective:
Make Phase-I evaluation and promotion artifacts causally truthful, independently verifiable, and safe for later real-data use.

Required outcomes:

1. Replace aggregate multi-parameter effect attribution with an independently controlled per-parameter audit.
   - Persist actual baseline values.
   - For each parameter, compare the full trial against a counterfactual with exactly that parameter reverted to baseline while other trial values remain fixed, or another equally isolated documented method.
   - Bind counterfactual trial/result IDs.
   - A finalist is ineligible unless every parameter independently demonstrates an owned-stage effect and no leakage.

2. Implement one direction-aware objective gate used consistently for validation, holdout, and promotion.
   - Enforce minimum fold coverage.
   - Enforce maximum failure rate.
   - Use minimum as worst for maximize objectives and maximum as worst for minimize objectives.
   - Add explicit lower-floor/upper-ceiling semantics.
   - Correct allowed-degradation semantics.
   - Enforce sample, coverage, worst-window, operational, and comparable-population gates on holdout too.

3. Make PromotionRecommendation semantically validated.
   - PROMOTE requires completed baseline/finalist validation and untouched-holdout evidence.
   - Require all causal, parameter-effect, coverage, failure, worst-window, latency/churn, and isolation gates.
   - Reject impossible manual promotion payloads even after recomputing recommendation IDs.

4. Bind complete evaluation semantics into trial identity.
   - Candidate provider and CandidateOutcomePolicy.
   - Frozen candidate stream for tracker.
   - Frozen source snapshot stream, label policy, target event state, and tick-size policy for interaction.
   - Scorer identity/parameters, threshold, label policy, baseline feature hash, and shadow feature hash for ablation.
   - Add typed immutable stage evaluation specs.

5. Bind the complete run request into RunManifest identity.
   - Full objective specs, not only version strings.
   - Maximum trial count/search strategy.
   - Stage evaluation specs.
   - Holdout execution/finalist-freeze policy.
   - Outcome/scorer/source artifact identities.
   - Runs with different semantic recommendations must not share a run ID.

6. Fix stateful holdout initialization.
   - Add a causal pre-holdout warmup window or canonical state seed to HoldoutPlan.
   - Tracker and interaction must replay/restore pre-holdout state without scoring or reading holdout labels.
   - Baseline and finalist must use identical initialization.
   - Persist a typed HoldoutOpenAudit bound to the selected validation finalist.
   - Reject arbitrary or conflicting repeated holdout opens; identical replay may be idempotent.

7. Add strict persistence verification.
   - Public from_dict/deserialization for all contracts.
   - Artifact-envelope verifier.
   - Typed run-bundle cross-validation.
   - Cross-bind run/stage/asset/timeframe/dataset/fold/config/objective/trial/result/finalist/holdout/recommendation identities.
   - Persist explicit baseline and finalist holdout artifacts.
   - Reject mismatched artifact bundles and stale/forged IDs.

8. Correct ablation macro F1.
   - Compute positive and negative class F1 separately and average them.
   - Preserve typed undefined reasons.

9. Preserve all current offline-only and runtime-invariance guarantees.

Do not implement MTF policy search in this remediation unless required for a contract test.
Do not add external fetching, services, databases, distributed optimization, or runtime imports.

Run:

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family/optimization \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py \
  -q -p no:cacheprovider

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i \
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals \
  -q -p no:cacheprovider

ruff check \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters/trendline_family_feature_producer.py \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent_phase_i_compile \
PYTHONPATH=src .venv/bin/python -m compileall -q \
  src/libs/models/trendline_family \
  src/libs/models/regime_v2/adapters

git diff --check

Reindex codebase-memory and report project, node count, edge count, status, direct changed-file scope, and impacted symbols.

Stop after Phase-I remediation and compact synthetic fixtures.
Do not begin a real-data trial or runtime promotion.
```

---

# Approval Status

**Request changes.**

The package is safe with respect to active runtime isolation, but it is not yet safe to use for real optimization or promotion recommendations because current contracts can misattribute parameter effects, mishandle stability gates, collide semantic identities, cold-start holdout state, and persist incoherent promotion artifacts.
