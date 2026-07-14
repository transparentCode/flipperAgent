# Review → Approval: Trendline-Family Candidate Density Study v1

## Reviewed Scope

Independent review of:

```text
scripts/analyze_trendline_family_candidate_density.py
tests/scripts/test_trendline_family_candidate_density.py
artifacts/trendline_family_candidate_density_studies/
  btcusdt_4h_20250801_20251201_candidate_geometry_v2/
plans/coder-to-review-trendline-family-candidate-density-study-v1.md
```

The review covered source identity, diagnosis-only read boundaries, threshold-zero exposure reconstruction, existing-threshold reconciliation, fold/holdout isolation, exact threshold arithmetic, support-frontier semantics, structural persistence summaries, external artifact provenance, protected-source immutability, and runtime/Regime isolation.

## Resolved Findings

No blocking, major, or minor implementation findings remain.

The study satisfies the approved architecture:

- consumes only the validated rejection-diagnosis bundle;
- performs zero provider, evaluator, Phase-I, network, holdout, tracker, interaction, MTF, RegimeV2, runtime, or YAML actions;
- reconstructs canonical exposure solely from persisted 0.40 threshold-zero shadow evidence;
- requires exactly 288 bars and 576 candidates per lookback;
- requires 288 support and 288 resistance candidates per lookback;
- reconciles the existing 0.30, baseline 0.35, and 0.40 diagnosis records exactly;
- uses exact Decimal threshold comparisons over 0–4000 bps;
- keeps the minimum-sample frontier descriptive and non-promotional;
- binds the study to the approved diagnosis bytes through a rederived source-binding ID;
- rejects stale and fully rebound nested inventory attacks;
- keeps all protected source bytes unchanged.

## Research Evidence Confirmed

The canonical exposure and support frontiers are:

```text
lookback  exposed candidates  balanced roles  highest grid threshold with >=100 candidates
120       576                 288 / 288       0.12   (crosses below at 0.13)
180       576                 288 / 288       0.08   (crosses below at 0.09)
240       576                 288 / 288       0.06   (crosses below at 0.07)
```

At each highest supported threshold every validation fold remains non-empty. The accepted counts are 34, 41, and 40 across the three folds for all three lookbacks after the corresponding threshold rescaling.

Independent cross-lookback inspection found:

- all 576 candidate IDs match by fold, position, and role across lookbacks 120/180/240;
- all anchor IDs and anchor spans match across those lookbacks;
- path lengths differ because longer lookbacks expose additional historical path pivots;
- quality scales approximately by the inverse lookback duration:
  - 120 vs 180: about 1.5042x;
  - 120 vs 240: about 2.0084x;
  - 180 vs 240: about 1.3352x.

This is consistent with the canonical `anchor_span_coverage_v1` implementation:

```text
quality = anchor_span_seconds / supplied_OHLCV_window_seconds
```

Therefore the observed density difference is primarily a quality-normalization effect tied to lookback length, not evidence that the shorter lookback discovered a different geometry population.

This conclusion is exploratory because the validation windows were already observed. It does not authorize a threshold, lookback, config patch, finalist, promotion, or runtime use.

## Remaining Non-Blocking Follow-Ups

1. Design a separate quality-definition architecture study before another parameter-grid trial.
2. Compare `anchor_span_coverage_v1` with lookback-invariant structural quality components while preserving exact geometry and causal fitting.
3. Any confirmation must use a separately approved unseen data window.
4. Tracker research remains blocked until a candidate-stage configuration passes validation and becomes a frozen finalist.
5. RegimeV2 remains excluded while that module is WIP.

## Blast Radius Confirmation

Created only:

```text
scripts/analyze_trendline_family_candidate_density.py
tests/scripts/test_trendline_family_candidate_density.py
artifacts/trendline_family_candidate_density_studies/
plans/coder-to-review-trendline-family-candidate-density-study-v1.md
```

Protected evidence remains unchanged:

```text
v1 trial root:       1 file
v2 trial root:      30 files
report bundle:       4 files
diagnosis bundle:    4 files
config SHA-256:      7a7fbc156a0ed3e01ac5b3d7502a76e834d6b34668daa8a569f32b4e63a887d8
```

No production runtime caller exists for `build_candidate_density_study(...)`.

## Validation Evidence Summary

Independently run:

```text
focused density study:                     33 passed
optimization + research support:           54 passed
full trendline-family:                     347 passed
family + adapter/projected isolation:      375 passed
broader RegimeV2/selection/signals slice:  175 passed, 1 existing warning
Ruff:                                       passed
compileall:                                 passed
git diff --check:                           passed
read-only bundle validation:                passed
```

The existing OpenTelemetry `LoggingHandler` deprecation warning is unrelated and unchanged.

Preserved artifact identities:

```text
study ID:
trendline-family-candidate-density-study_a1160637adbf58bc9a3b8a40cd4b79aa817f2749235ca883c799e03b1b429941

study source-binding ID:
trendline-family-candidate-density-study-source-binding_f433b8b24b2fd251fa3fea28d764e72a58c60382d5c834b607466ca893aad5c6
```

Codebase-memory:

```text
project: Users-aloobhujia-flipperAgent
nodes:   46,435
edges:   146,912
status:  ready
```

## Recommended Approval Status

**APPROVE.**

The candidate-density study is complete, deterministic, provenance-safe, and correctly limited to exploratory validation evidence.

The next handoff should be an architect-led, validation-only quality-normalization study. Do not begin a fresh threshold trial or tracker evaluation directly from this study.
