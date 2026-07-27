---
stage: coder-to-orchestrator
date_created: 2026-07-27
last_updated: 2026-07-27
owner: quant-coder
status: Ready for review
source_agent: quant-orchestrator
target_agent: quant-orchestrator
tags: [handoff, quant, trendlines, adequacy, interaction-utility]
---

# Mature Trendlines L2-D3
## Causal Interaction Utility

### 1. Disposition

`READY_FOR_L2D3_INTERACTION_REVIEW` pending independent review. No commit was
made. Measurements remain descriptive; no adequacy outcome was selected.

### 2. Branch and starting commit

```text
branch: research/trendlines-adequacy-v1
starting commit: 10d81ee690b833e52f0d73bee75be9bec5cbb4ea
starting subject: research: measure causal trendline structural stability
```

### 3. Parallel-main path audit

`origin/main` was fetched and compared from the merge base. Main-only changes
were limited to Trendline V2 generic-viewer plans, script, runner, and tests.
No mature-trendlines, shared replay/identity/configuration, or D3 paths
overlapped. No merge, rebase, or synchronization was performed.

### 4. Evaluation unit

Only `BOUNDARY_RAY` geometry was evaluated. Boundary rays are the canonical
consumer-facing projected geometry and D2 showed one-to-one line/ray structural
behaviour. Fitted lines were not separately evaluated, avoiding duplicate
evidence. Event unit is one non-left-censored boundary-ray episode birth.

### 5. Event selection and frozen geometry

Events come only from the committed D2 bundle's non-left-censored ray episodes.
The birth state binds episode, replay point, content, source, checkpoint,
boundary snapshot/revision, cohort, study, D2 bundle, and interaction-spec IDs.
Selection starts at the birth position; outcome rows begin at the next frame
position. Birth role, slope, intercept, and selection-time `latest_atr` remain
frozen for every future horizon. Later structural states cannot update the
projection.

### 6. Interaction protocol

The bounded spec is:

```text
evaluation_horizons_bars: 1, 3, 6, 12
break_confirmation_bars: resolved prepared 1h signals.hold_bars = 3
touch: inclusive low <= projected_level <= high
projection: frozen_slope * absolute_position + frozen_intercept
normalisation: selection-time latest_atr
break attempt: first adverse close only
```

Support defended touches require `close >= level`; resistance requires
`close <= level`. Wick rejection uses strict penetration through the level and
return to the defended side. Break confirmation requires consecutive adverse
closes; return before confirmation is false; a horizon ending first is
unresolved. Penetration and maximum favourable/adverse excursions are
selection-ATR normalised. No model interaction label, signal label, return,
P&L, retest, or role-reversal lifecycle is used.

### 7. Censoring and denominators

Future rows must be strictly later than selection position and availability.
Horizon targets beyond the available frame are right-censored and excluded
from eligible denominators. Touch, rejection, confirmed-break, and false-break
rates use their specified denominators; zero denominators are `None`. Support
and resistance summaries remain separate.

### 8. Contracts and identities

Five primary frozen contracts were added:

```text
TrendlineInteractionUtilitySpec
TrendlineInteractionEvent
TrendlineInteractionOutcome
TrendlineInteractionSummary
TrendlineInteractionUtilityBundle
```

Spec, event, outcome, summary, and bundle IDs use canonical SHA-256 content
hashes. Bundle validation checks nested IDs, D2 identity, event/outcome
coverage, summary recomputation, rate/count consistency, and tamper resistance.
Timing, paths, wall-clock values, and provider state are excluded from identity.

### 8a. R1 replay and outcome binding remediation

Independent review found that the first validator accepted rehashed bundles
with unrelated D2 cohort/study IDs, arbitrary dataset/replay IDs, impossible
coordinates, incomplete event/horizon coverage, and altered OHLC-derived
outcomes. R1 keeps the same five contracts and measurement formulas, but makes
canonical validation require both a typed D2 structural bundle and the typed
`PreparedTrendlineResearchReplay`.

Validation now:

```text
D3 cohort/study/D2 IDs == D2 bundle IDs
D3 dataset/replay IDs   == replay IDs
event set               == every non-left-censored boundary-ray D2 episode birth
event fields            == D2 birth state and validated replay point
outcome coordinates    == exact event_id x configured horizon product
horizon end            == selection position + horizon
touch/adverse positions strictly follow selection and stay inside horizon
stored outcomes        == measure_interaction_outcomes(replay frame)
stored summaries       == recomputed expected summaries
```

Every expected event birth point reuses `validate_replay_point_integrity()`.
Outcome validation delegates OHLC touch, break, penetration, and excursion
semantics to the existing pure measurement function; no formula is duplicated.
The bounded bundle ID remained exactly `56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4`.
No serialized evidence measurement changed.

### 9. Bounded offline source and identity binding

Only the committed L2-C frame artifact and committed D2 bundle were loaded:

```text
source artifact:
artifacts/trendlines_research_validation/20260726_btcusdt_1h_single_call_v1/normalized_ohlcv_v2.json

D2 artifact:
artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d2_structural_stability_v1/structural_stability_bundle.json
```

```text
source_id:                         d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331
availability_id:                  9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1
dataset_id:                       6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c
research_configuration_id:        ab6ec43eede637492f1e11bea6f4ae0cf72ef12045ee87265d648edb0cfc5853
preparation_id:                   ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141
replay_id:                        dc0783482b42bfec1beca1a45866ac0a40813cb144d390d28551ed0d419f0b78
cohort_id:                        9c3f9f6b099be611fcbd309a80483dc5b072d77ebd831de798370de52a9b7f69
study_config_id:                  07e634810f6be3a2223f7f8dde2aa778e68aa47d7003e12a92128fc4a65d3e1d
stability_spec_id:                12d9aa6b154238092835fd9879422a8d57d0a52e61ba8863dd27e8b7822a6271
structural_stability_bundle_id:   f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
interaction_spec_id:              df6f3cfa6dd9656de4e34d0eb1302a7726db6c5cd9106a700203aad810b9d98f
interaction_utility_bundle_id:    56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
```

Source rows: 312. Replay: 293 executed, 248 recorded. Provider calls and
retries: `0 / 0`. D2 bundle identity was reconstructed and matched exactly
before D3 measurement.

### 10. Measurements

```text
boundary-ray events: 43
support events:      24
resistance events:   19
outcomes:            172
summaries:           8 (2 roles x 4 horizons)
```

Per-role/per-horizon summary counts and rates are stored in
`run_manifest.json` and `interaction_utility_bundle.json`. Non-empty summary
rows from the bounded run:

```text
role        horizon  eligible  right-censored  touches  touch_rate  candidate  confirmed  false  unresolved
support     1        24        0               7        0.2916667    3          0          0      3
support     3        24        0              13        0.5416667    9          1          3      5
support     6        24        0              15        0.6250000   11          4          6      1
support    12        23        1              17        0.7391304   15          7          8      0
resistance  1        19        0               6        0.3157895    3          0          0      3
resistance  3        19        0               8        0.4210526    5          3          1      1
resistance  6        18        1              10        0.5555556   10          4          2      4
resistance 12        18        1              10        0.5555556   10          7          3      0
```

No result is interpreted as adequate or inadequate.

### 11. Artefacts and checksums

Output directory:

```text
artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d3_interaction_utility_v1/
```

```text
interaction_utility_bundle.json  172963  af69336b52439b819f53f578dadde8558d8b43085778ef07a7a9880a103dfe55
review.md                          846  71fc448e2784d40d92a4a0a1cd730013678f06d99d121adfaafba14e9858956a
run_manifest.json                 9593  48ef5b7f3dca628a7f2b1596786a163689dbf99b55ae4027bf6ec9d9be4cae9f
```

`checksums.json` validates all listed files. `outcome` is `null`.

### 12. Tests and validation

Focused package tests: 48 passed. Script tests: 4 passed. Canonical mature
trendlines collection: 598 passed. Viewer Python: 30 passed. Viewer Node: 23
passed. Consumer/ingestion/bridge matrix: 79 passed. Offline workflows: 20
passed. Provider calls/retries: 0 / 0. Ruff, compileall, and diff-check:
passed. The manifest test disposition records this completed matrix.

Required unchanged groups remain viewer Python 30, viewer Node 23,
consumer/bridge 79, and offline workflows 20. Provider calls remain zero.
Ruff, compileall, and diff-check are required. Repository-local caches are
removed after validation.

### 13. Deliberately not added

No tracker, matching engine, event state machine, registry, manager,
repository, factory, plugin interface, generic metric executor, new loader,
null baseline, P&L, retest/role reversal, parameter tuning, notebook/viewer
change, model/YAML change, provider path, or adequacy outcome was added.

### 14. Residual risks

This is one bounded BTCUSDT 1h cohort with 43 boundary-ray birth events.
Support and resistance sample sizes are asymmetric and small for inference.
The study measures descriptive future OHLC behaviour only and does not address
null comparison, cross-window robustness, cross-asset replication, predictive
utility, or execution economics. Those remain later phases.

### 15. Recommended next phase

`L2-D3 independent review`, followed only after approval by the separately
scoped causal interaction interpretation/research workflow. L2-D4 baseline
comparison and L2-D5 robustness remain deferred.
