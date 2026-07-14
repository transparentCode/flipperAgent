# Review → Approval: Trendline-Family Candidate Quality Normalization Study v1

## Reviewed Scope

Independent review of:

```text
scripts/analyze_trendline_family_candidate_quality_normalization.py
tests/scripts/test_trendline_family_candidate_quality_normalization.py
artifacts/trendline_family_candidate_quality_normalization_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
plans/coder-to-review-trendline-family-candidate-quality-normalization-study-v1.md
```

The review covered source identity, diagnosis/density-only read boundaries, exact matched-triplet reconstruction, current-score reproduction, predeclared formula arithmetic, lookback invariance, tie and saturation behavior, fold/role support evidence, architecture-only eligibility, provenance rebinding resistance, holdout isolation, protected-source immutability, and runtime/Regime isolation.

## Resolved Findings

No blocking, major, or minor findings remain.

The implementation satisfies the approved architecture:

- validates both approved source bundles before analysis;
- performs zero provider, pivot, fitter, evaluator, Phase-I, network, holdout, tracker, runtime, YAML, or RegimeV2 actions;
- reconstructs exactly 576 complete candidate triplets across lookbacks 120/180/240;
- requires exact equality of candidate ID, role, anchors, timestamps, and anchor span across each triplet;
- retains path length and recency only as audit evidence;
- reproduces all 1,728 persisted control scores and coverage values within `1e-12`;
- evaluates only the control and the eight predeclared fixed-horizon formula instances;
- uses exact Decimal arithmetic for candidate scores;
- independently rederives the complete study from live approved sources during bundle validation;
- rejects stale, partially rebound, and fully rebound source/study/manifest attacks;
- keeps all protected source bytes unchanged.

## Evidence Confirmed

Preserved identities:

```text
quality study ID:
trendline-family-candidate-quality-normalization-study_b45c8006cbe5304f36305fb1131e75173f32addc181d3e48e8d5bfd5cb71b0e3

quality source-binding ID:
trendline-family-candidate-quality-normalization-source-binding_483b0f334281e27e7d9d99bf41ce86c5d7839d90148a9d025e1c72ba35e62d94
```

Matched population:

```text
complete triplets:          576
support triplets:           288
resistance triplets:        288
persisted score instances: 1,728
holdout positions:            0
```

The current control is exactly:

```text
anchor_span_bars / (lookback_bars - 1)
```

All 576 matched geometries receive unequal absolute control scores across lookbacks while preserving rank order. The expected ratios are confirmed:

```text
q120 / q180 = 179 / 119
q120 / q240 = 239 / 119
q180 / q240 = 239 / 179
```

The control therefore fails only the predeclared exact-lookback-invariance architecture gate.

All eight fixed-horizon instances are:

- deterministic from persisted causal structural evidence;
- bounded in `[0, 1]`;
- monotonic in anchor span;
- exactly lookback-invariant;
- independent of role, fold, empirical distribution, outcomes, recency, and path length;
- classified only as eligible for separately approved fresh unseen research.

No horizon, threshold, lookback, finalist, config, or runtime choice is made by the study.

## Family-Level Architecture Interpretation

The next fresh-data design should carry forward the **`fixed_horizon_saturating_v1` family**, not a selected horizon or threshold.

This recommendation is structural rather than outcome-driven:

- the family is exactly lookback-invariant;
- it is smoothly bounded and never creates a hard score-1 plateau for finite spans;
- it preserves all 21 observed raw-span score levels at every tested horizon;
- its largest tie group remains the raw-span tie group, about `13.19%`;
- linear H=12 hard-saturates about `34.20%` of candidates at 1.0;
- linear H=24 hard-saturates about `11.28%` at 1.0;
- linear H=48/H=96 avoid saturation only on this observed span range, while the formula family still has a hard cap for larger fresh-data spans.

This does not promote the saturating family. It only identifies the cleaner family boundary for a separately approved unseen-window experiment. Horizons `{12, 24, 48, 96}` remain unselected policy candidates.

## Remaining Non-Blocking Follow-Ups

1. Design one fresh unseen-data candidate trial for `fixed_horizon_saturating_v1` using a predeclared bounded horizon set.
2. Freeze the fresh data window, formula family, horizon grid, threshold policy, folds, sample gate, and objective before any execution.
3. Do not reuse the observed validation windows or open the existing planned holdout.
4. Keep raw anchor span explicit in artifacts even if a normalized score is later evaluated.
5. Keep current relevance/recency downstream from structural candidate quality.
6. Tracker research remains blocked until candidate validation produces a frozen finalist.
7. RegimeV2 remains excluded while that module is WIP.
8. The 14.05 MB JSON is acceptable as an external deterministic verification artifact; it has no runtime consumer.

## Blast Radius Confirmation

Created only:

```text
scripts/analyze_trendline_family_candidate_quality_normalization.py
tests/scripts/test_trendline_family_candidate_quality_normalization.py
artifacts/trendline_family_candidate_quality_normalization_studies/
plans/coder-to-review-trendline-family-candidate-quality-normalization-study-v1.md
```

Protected evidence remains unchanged:

```text
v1 trial root:          1 file
v2 trial root:         30 files
report bundle:          4 files
diagnosis bundle:       4 files
density-study bundle:   4 files
config SHA-256:
7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

`build_candidate_quality_normalization_study(...)` is called only by the script `main`; no production runtime caller exists.

## Validation Evidence Summary

Independently run:

```text
focused quality-normalization study:      38 passed
optimization + research support:          54 passed
full trendline-family:                    347 passed
family + adapter/projected isolation:     375 passed
RegimeV2/selection/signals isolation:     175 passed, 1 existing warning
Ruff:                                      passed
compileall:                                passed
git diff --check:                          passed
read-only bundle validation:               passed
```

Artifact hashes independently confirmed:

```text
source_binding.json:
413e08c7b604e0d9d065ebfdc7d1b9d631d8496ee3de06884a07bc3b01dea6f6

quality_normalization_study.json:
b5f1611524a268e770ec47cb275f47149371a63373695278cdb39736067b26e0

quality_normalization_study.md:
3dd4adf42f3f6349318343dfe082795f163576df8aa7a2343b13ff07aa461de1

study_manifest.json:
40eb8f53152ec9e330df93f9fa7c082fa31d8160ba9cd450b31727ce11bd64b8
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   46,874
edges:   148,349
status:  ready
```

The existing OpenTelemetry `LoggingHandler` deprecation warning is unrelated and unchanged.

## Recommended Approval Status

**APPROVE.**

The quality-normalization study is complete, deterministic, provenance-safe, and correctly limited to architecture evidence.

The next handoff should be an architect-led fresh unseen-data candidate trial design for the `fixed_horizon_saturating_v1` family. Do not implement canonical quality changes, select a horizon/threshold, or begin tracker evaluation directly from this study.
