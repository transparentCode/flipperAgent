---
stage: coder-to-orchestrator
date_created: 2026-07-27
last_updated: 2026-07-27
owner: quant-coder
status: Review
source_agent: quant-orchestrator
target_agent: quant-orchestrator
tags: [handoff, quant, trendlines, adequacy, stochastic-nulls]
---

# L2-D4B Seeded Stochastic Null Comparison

## 1. Disposition

`READY_FOR_L2D4B_NULL_REVIEW`

Implementation and bounded evidence are complete without commit, merge, D5,
provider access, model changes, parameter tuning, or adequacy disposition.

## 2. Starting checkpoint

```text
branch: research/trendlines-adequacy-v1
starting commit: 632bc1baac4441217bf47a8c8c5b56fabdb647f7
subject: research: compare trendlines with deterministic baselines
worktree: uncommitted D4B scope only
```

## 3. Parallel-main audit

```text
origin/main: a6fe843a93602af294f7a4d452bb0c9c20d2e119
common base: 29a068a9032b826f88a859623b52faaeedeaee93
```

Main-only paths remain Trendline V2 viewer plans, scripts, source, and tests.
No mature-trendlines, D2-D4, shared replay, identity, configuration, or
current D4B path overlap was found. No synchronization was performed.

## 4. Design decision

D4B executes exactly `RANDOM_VALID_PIVOT_PAIR` and
`DENSITY_MATCHED_NULL`. Event timing remains fixed to the 43 committed D3
boundary-ray episode births. This is conditional geometry comparison, not a
test of event-timing quality. Fitted lines, time-shifted geometry, and
role-shuffled geometry remain out of scope.

## 5. Explicit stochastic specifications

```text
random-valid-pivot-pair-v1
  kind: random_valid_pivot_pair
  repetitions: 32
  seed: 2026072701
  preserves: timeframe, position, role, pivot_count, causal_prefix

causal-density-matched-null-v1
  kind: density_matched_null
  repetitions: 32
  seed: 2026072702
  preserves: timeframe, position, role, ray_count,
             observation_density, causal_prefix

quantiles: 0.05, 0.95
```

No stochastic specification was added to the frozen D2 study configuration.

## 6. Deterministic RNG

Each draw identity binds baseline ID, seed, repetition index, model event ID,
and draw semantics version. `int(draw_id[:16], 16)` seeds an isolated
`random.Random`; no global RNG, NumPy global state, Python hash, unordered set,
or wall-clock seed is used. Candidate and donor pools have deterministic sort
orders, so input iteration order does not affect evidence.

## 7. Random-pair construction

Pivots are inspected at each exact D3 selection prefix, validated against its
replay point, restricted to confirmed append-only same-role pivots, and required
to precede selection. All ordered pairs are enumerated and sorted by
`x1, x2, y1, y2`. Geometry uses exact two-point slope/intercept and is retained
only when support is below or equal to selection close or resistance is above or
equal. Empty pools produce `no_valid_same_role_pivot_pair` abstentions.

## 8. Density-matched construction

Donors are same-timeframe, same-role D3 events with strictly earlier selection
position and availability. Current, simultaneous, future, opposite-role, and
other-timeframe donors are excluded. Donor slope and role-signed donor distance
are normalized by donor ATR, then transported through current selection close
and ATR. Donor provenance and all normalized intermediates are persisted.
Empty pools produce `no_prior_same_role_donor` abstentions. No pivot-pair
fallback exists.

## 9. Outcome and denominator policy

Available selections reuse the D3 frozen-geometry OHLC outcome helper. Outcomes
start strictly after selection, preserve D3 availability and horizon semantics,
and use selection-time ATR. Every baseline/repetition/event attempt exists once;
abstentions create no outcomes. Model and null summaries use the same available
event subset and remain separate by timeframe, role, and horizon. Deltas are
model minus null; undefined values remain `None`.

## 10. Bounded inventory

```text
model events:             43
selection attempts:       2,752 = 43 × 2 × 32
available selections:     2,688
abstentions:                 64
null outcomes:            10,752
repetition comparisons:     512
distribution summaries:     112
```

```text
random-valid-pivot-pair-v1: attempts 1,376; available 1,376; abstentions 0
causal-density-matched-null-v1:
  attempts 1,376; available 1,312; abstentions 64; coverage 95.3488%
```

Density abstentions are causal first-event donor absences, retained without
fallback. Random-pair coverage is 100% in this cohort.

## 11. Per-role/per-horizon distribution inventory

All seven metrics are persisted for every baseline, role, and horizon:
`touch_rate`, `rejection_rate`, `confirmed_break_rate`, `false_break_rate`,
`mean_penetration_atr`, `mean_favourable_excursion_atr`, and
`mean_adverse_excursion_atr`. Each row has 32 repetitions, defined/undefined
counts, mean/median/minimum/maximum, q05/q95, and negative/zero/positive counts.

Touch-rate distribution rows, included as an audit index (full distributions
remain in `run_manifest.json` and the canonical bundle):

| baseline | role | horizon | defined | mean delta | q05 | q95 |
|---|---|---:|---:|---:|---:|---:|
| random pair | support | 1 | 32 | 0.174479 | 0.083333 | 0.250000 |
| random pair | support | 3 | 32 | 0.260417 | 0.166667 | 0.333333 |
| random pair | support | 6 | 32 | 0.281250 | 0.208333 | 0.375000 |
| random pair | support | 12 | 32 | 0.311141 | 0.217391 | 0.410870 |
| random pair | resistance | 1 | 32 | 0.230263 | 0.157895 | 0.315789 |
| random pair | resistance | 3 | 32 | 0.294408 | 0.210526 | 0.368421 |
| random pair | resistance | 6 | 32 | 0.364583 | 0.283333 | 0.444444 |
| random pair | resistance | 12 | 32 | 0.309028 | 0.222222 | 0.388889 |
| density matched | support | 1 | 32 | 0.005435 | -0.086957 | 0.086957 |
| density matched | support | 3 | 32 | -0.043478 | -0.106522 | 0.063043 |
| density matched | support | 6 | 32 | -0.089674 | -0.193478 | 0.000000 |
| density matched | support | 12 | 32 | -0.076705 | -0.181818 | 0.020455 |
| density matched | resistance | 1 | 32 | 0.012153 | -0.111111 | 0.136111 |
| density matched | resistance | 3 | 32 | 0.038194 | -0.136111 | 0.136111 |
| density matched | resistance | 6 | 32 | 0.079044 | -0.144118 | 0.235294 |
| density matched | resistance | 12 | 32 | -0.003676 | -0.202941 | 0.176471 |

These rows are descriptive evidence only; no interpretation or winner is
selected.

## 12. Identity chain and checksums

```text
source_id: d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331
availability_id: 9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1
dataset_id: 6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c
preparation_id: ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141
replay_id: dc0783482b42bfec1beca1a45866ac0a40813cb144d390d28551ed0d419f0b78
cohort_id: 9c3f9f6b099be611fcbd309a80483dc5b072d77ebd831de798370de52a9b7f69
study_config_id: 07e634810f6be3a2223f7f8dde2aa778e68aa47d7003e12a92128fc4a65d3e1d
D2 bundle: f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
D3 bundle: 56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
D4A bundle: 664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663
D4B bundle: 98f04441c0ef9c643640c78004a875ab6fa6a8de6c797eb1f2e68420910323db
interaction_spec_id: df6f3cfa6dd9656de4e34d0eb1302a7726db6c5cd9106a700203aad810b9d98f
```

Artifact directory:
`artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d4b_seeded_stochastic_nulls_v1/`

```text
stochastic_null_comparison_bundle.json  13,869,543 bytes  12be8d79ddc6bd72a92be198bffede963b40bebfb19d21c4b8268c1d1fe85fc0
run_manifest.json                          346,906 bytes  764e67720800cb6a0833e1d2548953471adb9214dca5d202a85b750b25e07653
review.md                                      980 bytes  c19b66b62ee201e6ad78372b175d8107769b5284c1ea59e2e9378444a3f8352c
```

Checksums cover these three canonical output files. `checksums.json` itself is
the verification index and is not self-listed.

## 13. Validation

```text
D4B focused:                 46 passed
D4B script:                   6 passed
D4A focused:                 36 passed
D4A script:                   4 passed
D3 focused:                 48 passed
Canonical mature trendlines: 680 passed
Viewer Python:              30 passed
Viewer Node/TypeScript:     23 passed
Consumer/ingestion/bridge:  79 passed (accepted unchanged matrix)
Offline workflows:          20 passed (accepted unchanged matrix)
Mocked Binance bridge:       8 passed
Provider calls/retries:      0 / 0
Ruff/compileall/diff-check:  passed
Repository-local caches:     removed after validation
```

The D4B script and tests use injected/reloaded artifacts only. No network or
provider construction exists in D4B code.

## 14. Files changed

```text
A  src/libs/models/trendlines/workflows/research/adequacy/stochastic_null_comparison.py
A  src/libs/models/trendlines/tests/research_adequacy/test_stochastic_null_comparison.py
A  scripts/analyze_trendlines_l2d4b_seeded_nulls.py
A  tests/scripts/test_analyze_trendlines_l2d4b_seeded_nulls.py
M  src/libs/models/trendlines/workflows/research/adequacy/__init__.py
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
A  artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d4b_seeded_stochastic_nulls_v1/*
A  plans/coder-to-orchestrator-trendlines-l2d4b-seeded-nulls-v1.md
```

## 15. Abstractions deliberately not added

No Monte Carlo framework, sampler registry, generic experiment runner, plugin,
database, repository, manager, factory, evaluator class, state machine, or new
configuration loader was added. D4B uses pure functions and five primary frozen
result contracts, reusing D3 outcome and summary formulas.

## 16. Residual risks

Evidence is one BTCUSDT 1h cohort with 43 mature-model events. Event timing is
held fixed, so D4B does not compare when geometry is selected. The stochastic
draw count is descriptive, not formal inference: no p-values, significance
thresholds, or multiple-testing correction were applied. Cross-window,
cross-asset, parameter-sensitivity, interaction-lifecycle, and adequacy
disposition work remain deferred. No D5 work began.

## 17. Hardcoding classification

The bounded source/D2/D3/D4A artifact paths, expected committed IDs, base
commit, seeds, repetitions, baseline names, and quantile probabilities are
explicit study controls. Candidate construction, draw derivation, geometry
transport, outcome calculation, summaries, quantiles, and identity validation
remain package APIs; the script only reconstructs context and persists evidence.

## 18. Recommended next phase

Independent review of D4B seeded-null evidence. Do not select an adequacy outcome
or begin D5 before review.
