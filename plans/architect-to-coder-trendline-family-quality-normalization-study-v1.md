# Architect → Coder: Trendline-Family Candidate Quality Normalization Study v1

## Objective

Build one bounded, read-only architecture study that isolates the lookback dependence of `anchor_span_coverage_v1` and compares fixed-policy, lookback-invariant normalization families on the exact same persisted candidate geometries.

The study must answer:

- whether the current candidate quality is exactly a lookback-relative rescaling of the same structural anchor span;
- whether the 576 persisted candidates form complete matched triplets across lookbacks `120`, `180`, and `240`;
- which normalization families are structurally eligible for a separately approved fresh-window candidate trial;
- how fixed-horizon linear and saturating transforms affect score distributions, saturation, tie rates, fold/role balance, and descriptive candidate support;
- which aspects belong in candidate structural quality and which must remain separate downstream relevance evidence.

This is an offline architecture study over already observed validation evidence. It must not change canonical quality logic, select a runtime formula, select a scale, tune a threshold, rerun the provider, or open holdout.

## Fixed Source Identity

Consume only the already approved bundles:

```text
artifacts/trendline_family_candidate_diagnostics/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/

artifacts/trendline_family_candidate_density_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Validate them before analysis through:

```python
validate_diagnosis_bundle(...)
validate_density_study_bundle(...)
```

Require these identities:

```text
asset:                         BTCUSDT
timeframe:                     4h
timeframe seconds:             14,400
confirmed rows:                732
dataset hash:                  trendline-family-dataset_ccaf20405ffc4b84ea98f79e97053e3ee6be4b0c571999dcbf5fc0e0bca1ad53
resolved config hash:          da15ebbcb42a9148714394b35d94e246c412af964c53024d43f221c30bd8a08f
Phase-I run ID:                trendline-family-phase-i-run_6393c4d86edb7558045b96e5c5be39fd915d8a8dde29b44e66515fdbf44b37e7
report ID:                     trendline-family-candidate-evidence-report_5e01522b2ac82f67e6a722372e6deba4ea77c7fe9ea47b5415ef7d65bc3d2d41
recommendation ID:             trendline-family-promotion-recommendation_fdcf8d4b39ffda53b3f09b26ff28bec40056677ce18cc90eb2292b310005ccbc
diagnosis ID:                  trendline-family-candidate-rejection-diagnosis_d45c7463e1e8410a4fb9004ee7ad83b26d3c994d3a44ce781f7ff38a5025ecbf
diagnosis source-binding ID:   trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a
density study ID:              trendline-family-candidate-density-study_a1160637adbf58bc9a3b8a40cd4b79aa817f2749235ca883c799e03b1b429941
density source-binding ID:     trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6
validation windows:            252-347, 360-455, 468-563
planned holdout start:         636
provider calls in this study:  0
```

Any mismatch must fail closed. Do not repair, regenerate, or reinterpret either approved source bundle.

## Research Status and Bias Boundary

The candidate population and validation windows have already been observed.

Therefore:

- every result is exploratory and post-diagnostic;
- no formula, scale, or score threshold may be promoted on this dataset;
- structural eligibility means only “safe to carry into a separately approved fresh unseen trial”;
- the planned holdout at positions `636-731` remains sealed;
- no result may be described as OOS confirmation, alpha evidence, or runtime evidence.

Persist these limitations prominently in JSON and Markdown.

## Scope Boundaries

### In scope

- strict validation of the approved diagnosis and density-study bundles;
- candidate-level reconstruction from persisted diagnosis records only;
- exact matched-triplet analysis across lookbacks `120`, `180`, and `240`;
- exact reconstruction of the current quality formula;
- analytic comparison of predeclared fixed-horizon normalization families;
- deterministic score-distribution, invariance, saturation, tie, fold, role, and support summaries;
- architecture eligibility classification under predeclared non-outcome gates;
- deterministic external artifacts and focused tests.

### Out of scope

- `NativeDeterministicLineProvider` or any `generate(...)` call;
- pivot extraction or path fitting;
- `CandidateGeometryEvaluator` or future-outcome calculation;
- Phase-I, optimization, trial enumeration, finalist creation, or holdout access;
- network or Binance access;
- any new asset, timeframe, or data window;
- canonical `fitting.py`, `provider.py`, contracts, config, or YAML changes;
- selecting one transform, one horizon, one threshold, or one lookback for runtime;
- tracker, interaction/event, MTF, RegimeV2, signals, selection, strategy, risk, execution, or portfolio work;
- PnL, directional, or trading claims.

## Expected Implementation Scope

Create only:

```text
scripts/analyze_trendline_family_candidate_quality_normalization.py

tests/scripts/test_trendline_family_candidate_quality_normalization.py

artifacts/trendline_family_candidate_quality_normalization_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
    source_binding.json
    quality_normalization_study.json
    quality_normalization_study.md
    study_manifest.json

plans/coder-to-review-trendline-family-candidate-quality-normalization-study-v1.md
```

Generated `.codebase-memory/` files may change. Do not modify any existing trial, report, diagnosis, density-study, canonical model, optimizer, notebook, config, runtime, or Regime file.

## Mandatory Read Boundary

The new script may import only pure validation/analysis helpers from the approved external-study scripts and canonical serialization contracts.

It must not import or contain any of these execution boundaries:

```text
BinanceNativeAdapter
get_historical_ohlcv
NativeDeterministicLineProvider
provider.generate
PathfindingLineFitter
CausalFractalPivotProvider
run_phase_i_evaluation
run_stage_grid
run_validation_trial
CandidateGeometryEvaluator
evaluate_holdout_once
TrendlineFamilyTracker
advance_interaction_events
RegimeV2
```

Static tests must enforce this list.

## Canonical Matched Population

Use the threshold-zero shadow candidates from the approved diagnosis records for the three `0.40` configurations.

Define the structural match key:

```text
(
  fold_id,
  position,
  observed_at,
  role,
  candidate_id,
  ordered_anchor_ids,
  ordered_anchor_timestamps,
  anchor_span_seconds,
)
```

Require:

```text
lookbacks:                         120, 180, 240
validation bars per lookback:      288
candidates per lookback:           576
matched structural keys:           576
complete matched triplets:         576
support candidates per lookback:   288
resistance candidates per lookback:288
quality method:                    anchor_span_coverage_v1
holdout positions:                 0
```

For each matched triplet, require exact equality across lookbacks for:

- fold, position, timestamp;
- role;
- candidate ID;
- anchor IDs and anchor timestamps;
- anchor span seconds and anchor span bars;
- geometry-defining structural identity already bound by candidate ID.

Path length is expected to differ and must be retained as an audit field only.

If any matched triplet is missing, duplicated, or structurally inconsistent, stop the study.

## Raw Structural Evidence

Derive exactly:

```text
anchor_span_bars = anchor_span_seconds / 14,400
```

Require:

- exact integer bar spans;
- positive values;
- equality across all three lookbacks for every matched triplet;
- no empirical fitting or percentile transformation.

Retain these additional audit fields without using them in candidate-quality formulas:

- path length per lookback;
- path-length deltas across lookbacks;
- role;
- fold;
- last-anchor age in exact 4h bars when derivable from persisted timestamps.

Recency and current relevance are architecturally separate from structural candidate quality. Do not combine last-anchor age with the candidate-quality formulas in this study.

Path length is also excluded from formula construction because the approved evidence shows that it changes with the supplied historical window even when candidate geometry is identical.

## Current Method Audit

For every one of the `576 × 3 = 1,728` candidate instances, reconstruct:

```text
current_quality_expected = anchor_span_bars / (lookback_bars - 1)
```

Use `Decimal`; do not use accumulated binary-float arithmetic.

Require persisted quality and coverage to equal this expected value within the canonical `1e-12` contract tolerance.

Report for each lookback pair:

- exact score-ratio expectation;
- observed min/max/mean ratio;
- maximum absolute score difference for matched candidates;
- candidate rank-order equality;
- threshold-support differences inherited solely from score scaling.

Expected ratio identities:

```text
q120 / q180 = 179 / 119
q120 / q240 = 239 / 119
q180 / q240 = 239 / 179
```

The study must distinguish:

- structural ranking stability, which may remain identical;
- absolute score comparability, which currently fails across lookbacks.

## Predeclared Normalization Families

Evaluate only these analytic families. Do not add formulas after inspecting results.

### 1. Current control

```text
formula_id: lookback_relative_anchor_span_coverage_v1
score(L) = anchor_span_bars / (L - 1)
```

This is the control and is expected to fail exact lookback invariance.

### 2. Fixed-horizon linear family

For each fixed horizon `H`:

```text
formula_id: fixed_horizon_linear_v1_h{H}
score = min(anchor_span_bars / H, 1)
```

### 3. Fixed-horizon saturating family

For each fixed half-saturation horizon `H`:

```text
formula_id: fixed_horizon_saturating_v1_h{H}
score = anchor_span_bars / (anchor_span_bars + H)
```

Use exactly:

```text
H in {12, 24, 48, 96} bars
```

At 4h these correspond to fixed policy horizons of approximately 2, 4, 8, and 16 days. They are predeclared policy scales, not values fitted from the observed distribution.

Do not evaluate:

- empirical CDF or percentile scores;
- fold-specific normalization;
- role-specific normalization;
- asset-sample-fitted scales;
- lookback-derived scales;
- outcome-weighted formulas;
- recency/path-length composites;
- learned or optimized formulas.

## Formula Arithmetic

Use exact `Decimal` arithmetic from integer `anchor_span_bars` and integer `H`.

Persist decimal scores as canonical strings plus a numeric projection for summaries where needed.

Every candidate score must be in `[0, 1]`.

For all fixed-horizon formulas, require exact score equality across the three lookbacks for every matched candidate triplet.

## Required Study Outputs

### 1. Source and bias identity

Persist:

- every fixed source identity;
- diagnosis and density-study file inventories;
- exact validation windows;
- planned holdout boundary;
- `holdout_accessed: false`;
- `provider_calls: 0`;
- `evaluator_calls: 0`;
- exploratory/post-diagnostic status;
- fresh unseen confirmation requirement.

### 2. Matched-population audit

Persist:

- candidate counts by lookback, fold, and role;
- complete matched-triplet count;
- missing/duplicate/mismatched structural key counts;
- cross-lookback equality results for IDs, anchors, timestamps, spans, and roles;
- path-length delta distributions;
- raw anchor-span distribution.

Do not persist all candidate records if a bounded content-addressed audit table is sufficient, but retain enough deterministic evidence to independently verify the complete 576-triplet reconciliation.

### 3. Current-method decomposition

Persist:

- formula identity;
- exact denominator per lookback;
- reconstructed-versus-persisted error summary;
- cross-lookback score ratios;
- rank-order equality;
- proof that matched geometry remains identical while absolute score changes.

### 4. Formula catalog

For every formula instance, persist:

- formula family and version;
- horizon parameter when applicable;
- exact equation;
- input fields;
- whether it depends on lookback;
- whether it depends on empirical data distribution;
- whether it uses path length, role, fold, recency, or outcomes;
- boundedness and monotonicity properties.

### 5. Invariance audit

For every formula instance, persist across matched triplets:

- maximum absolute score difference across lookbacks;
- unequal-score triplet count;
- exact-equality result;
- rank-order equality;
- per-role and per-fold invariance results.

Expected:

- current control: non-zero score differences;
- every fixed-horizon formula: zero unequal triplets under exact Decimal comparison.

### 6. Score distributions

For every formula instance, aggregate and retain per fold and role:

- count;
- min, max, mean, median;
- fixed quantiles `0.10`, `0.25`, `0.50`, `0.75`, `0.90`;
- unique-score count;
- largest tie-group count and share;
- zero-score fraction;
- one-score saturation fraction;
- score range and interquartile range.

### 7. Descriptive support curves

For every formula instance, build a deterministic score threshold grid:

```text
threshold_bps: 0, 100, 200, ..., 10,000
threshold:     0.00, 0.01, 0.02, ..., 1.00
```

A candidate survives when:

```text
score >= threshold
```

Retain aggregate and per-fold/per-role:

- accepted candidate count;
- producing-bar count;
- support/resistance counts;
- both-role/no-role bar counts;
- smallest and largest fold counts;
- largest-fold concentration;
- descriptive highest threshold with at least 100 aggregate candidates;
- whether every fold is non-empty at that threshold.

This is analytic support only. Do not turn it into a selected threshold or gate recommendation.

### 8. Structural eligibility table

Classify each formula instance under only these predeclared architecture gates:

1. deterministic from persisted causal structural fields;
2. bounded in `[0, 1]`;
3. monotonic non-decreasing in anchor span;
4. exact lookback invariance for matched candidate geometry;
5. no role/fold-specific behavior;
6. no empirical-distribution fitting;
7. no future outcomes;
8. no recency or path-length mixing;
9. no runtime or YAML implication.

Persist:

```text
eligible_for_fresh_unseen_research: true | false
failed_architecture_gates: [...]
```

This eligibility flag is not promotion and must not select one horizon or transform.

Expected family-level interpretation:

- current lookback-relative control fails the lookback-invariance gate;
- fixed-horizon linear and saturating variants may pass structural eligibility if all invariants hold;
- no eligible formula is automatically preferred over another.

### 9. Observations and hypotheses

Keep separate arrays:

```text
observations
research_hypotheses
architecture_implications
```

Allowed architecture implications include:

- raw anchor span should remain explicit evidence;
- bounded normalization should use an explicit fixed policy scale independent of provider lookback;
- current relevance/recency should remain downstream from candidate structural quality;
- a later fresh-window trial may compare a bounded subset of structurally eligible formula families.

Forbidden language:

- selected threshold;
- selected horizon;
- promoted formula;
- runtime-ready;
- profitable;
- OOS-confirmed;
- tracker-ready.

## External Artifact Contract

Output root:

```text
artifacts/trendline_family_candidate_quality_normalization_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
```

Required files:

```text
source_binding.json
quality_normalization_study.json
quality_normalization_study.md
study_manifest.json
```

### Source binding

Bind both approved source bundles:

- exact four-file diagnosis inventory;
- exact four-file density-study inventory;
- their aggregate hashes;
- diagnosis and density IDs;
- diagnosis and density source-binding IDs;
- content-addressed quality-study source-binding ID.

Require canonical sorted unique safe paths, non-negative integer sizes, and lowercase 64-character SHA-256 values.

### Study identity

The study ID must be content-addressed from the complete semantic study payload excluding only its own ID field.

### Independent validation

Implement a strict pure validator that independently rederives:

- both source inventory hashes;
- quality-study source-binding ID;
- quality-study ID;
- JSON and Markdown hashes;
- manifest identity claims;
- external-versus-embedded source binding equality;
- current live validated diagnosis and density-study byte equality.

Copied-bundle attacks that jointly rebind nested inventory, binding, study, and manifest claims must still reject because they differ from the approved live source bytes.

### Writes

- deterministic canonical JSON;
- atomic writes;
- identical reruns idempotent;
- non-identical overwrite rejected;
- all outputs outside protected roots.

## Source Immutability

Before and after the study, capture and require byte identity for:

```text
v1 trial root:          1 file
v2 trial root:         30 files
approved report:        4 files
approved diagnosis:     4 files
approved density study: 4 files
configs/trendline_family.yaml
```

The approved config SHA must remain:

```text
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

## Test Requirements

Focused tests must cover at minimum:

1. forbidden provider/evaluator/network/holdout/tracker/Regime boundaries are absent;
2. diagnosis and density bundles validate before analysis;
3. every fixed identity rejects drift;
4. exact 576 complete matched triplets across all three lookbacks;
5. candidate ID, role, anchors, timestamps, and span equality across lookbacks;
6. path length is retained only as audit evidence and excluded from formula definitions;
7. current formula reconstructs all 1,728 persisted scores within `1e-12`;
8. exact expected lookback score ratios;
9. raw anchor span in 4h bars is exact and lookback invariant;
10. exact formula catalog and horizon grid `{12, 24, 48, 96}`;
11. fixed-horizon formulas are exactly lookback invariant under Decimal arithmetic;
12. all formulas are bounded and monotonic;
13. score distributions, saturation, ties, and quantiles are deterministic;
14. support curves are monotonic non-increasing;
15. architecture eligibility uses only predeclared non-outcome gates;
16. no formula/horizon/threshold selection or promotion semantics appear;
17. holdout remains sealed and no non-validation positions enter the population;
18. deterministic rerender and non-identical overwrite rejection;
19. protected source bytes remain unchanged;
20. forged diagnosis or density inventory with rebound outer claims rejects;
21. forged quality-study source-binding ID rejects;
22. external-versus-embedded source-binding mismatch rejects;
23. missing/extra fields, unsafe/duplicate/unsorted paths, invalid sizes, and malformed hashes reject.

Copied-bundle tests must not rebuild diagnosis/density artifacts or run any provider/evaluator path.

## Implementation Order

1. Validate both approved source bundles and fixed identities.
2. Capture protected source inventories.
3. Build the exact 576-triplet matched population.
4. Reconstruct and audit `anchor_span_coverage_v1`.
5. Compute raw span evidence and predeclared formula scores.
6. Build invariance, distribution, support, and eligibility tables.
7. Create deterministic content-addressed artifacts.
8. Independently validate the artifact bundle.
9. Rerender once and require byte-identical idempotence.
10. Recheck all protected source inventories.
11. Run focused and broad tests.
12. Reindex codebase-memory.
13. Write coder-to-review handoff and stop.

## Validation Checklist

Run:

```text
PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/scripts/test_trendline_family_candidate_quality_normalization.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family/optimization \
  tests/models/trendline_family/research_lab

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/trendline_family \
  tests/models/regime_v2/adapters \
  tests/signals/test_trendline_family_shadow_projected_runtime.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache PYTHONPATH=src \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/models/regime_v2/adapters \
  tests/test_regime_v2.py \
  tests/test_regime_v2_trendline_feature_producer.py \
  tests/test_selection_layer.py \
  tests/signals

/Users/aloobhujia/.local/bin/ruff check \
  scripts/analyze_trendline_family_candidate_quality_normalization.py \
  tests/scripts/test_trendline_family_candidate_quality_normalization.py

PYTHONPYCACHEPREFIX=/tmp/flipperagent-pycache \
  .venv/bin/python -m compileall -q \
  scripts/analyze_trendline_family_candidate_quality_normalization.py \
  tests/scripts/test_trendline_family_candidate_quality_normalization.py

git diff --check
```

Also:

- call the quality-study bundle validator read-only;
- rerun generation once and require all four output files byte-identical;
- verify protected source inventories before/after;
- verify zero provider/evaluator/holdout/network calls;
- reindex codebase-memory and report node/edge counts and `ready` status;
- confirm the new build function has no production runtime caller.

## Acceptance Criteria

The task passes only when:

1. no provider, fitter, pivot, evaluator, network, holdout, tracker, runtime, YAML, or Regime path executes;
2. both approved source bundles validate unchanged;
3. exactly 576 complete structural triplets reconcile across three lookbacks;
4. the current formula is proven to be lookback-relative on all 1,728 candidate instances;
5. raw anchor span is proven lookback invariant;
6. every fixed-horizon formula is deterministic and exactly lookback invariant;
7. eligibility is architecture-only and does not choose a formula, scale, threshold, or lookback;
8. study artifacts are content-addressed, provenance-safe, idempotent, and external;
9. all protected source bytes remain unchanged;
10. all validation commands pass.

## Explicit Non-Goals

Do not:

- modify `anchor_span_coverage_v1`;
- add a canonical quality method;
- change `FittedPath`, `LineDiagnostics`, or provider metadata;
- select a formula family, horizon, threshold, or lookback;
- create a candidate trial, finalist, gate, or recommendation;
- fetch data or open holdout;
- modify YAML or runtime consumption;
- begin tracker, interaction, MTF, or Regime work;
- make trading or performance claims.

## Coder Handoff

Return:

```text
plans/coder-to-review-trendline-family-candidate-quality-normalization-study-v1.md
```

The handoff must include:

- exact files created;
- fixed source identities;
- source immutability evidence;
- matched-triplet reconciliation;
- current-method decomposition;
- formula catalog and invariance results;
- structural eligibility table without formula selection;
- study and source-binding IDs;
- artifact hashes;
- tests and exact counts;
- codebase-memory status;
- known gaps;
- explicit confirmation that no provider, fitter, evaluator, network, Phase-I, holdout, tracker, runtime, YAML, or Regime work occurred.

Stop after the study. Do not begin a fresh-data trial or canonical quality implementation.
