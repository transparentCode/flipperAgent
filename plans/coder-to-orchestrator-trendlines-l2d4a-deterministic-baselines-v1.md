# Coder-to-Orchestrator Handoff

## L2-D4A — Paired Deterministic Naive Baseline Comparison

### 1. Disposition

`READY_FOR_L2D4A_BASELINE_REVIEW`. This phase remains descriptive. No
baseline-comparison adequacy outcome, winner, composite score, promotion, or
D4B random/null study was selected.

### 2. Starting checkpoint

```text
branch: research/trendlines-adequacy-v1
starting commit: dbe6c8dcff80396c42f92a27bf53f31facc3f8a6
starting subject: research: measure causal trendline interaction utility
```

### 3. Parallel-main path audit

`origin/main` was fetched and compared at the merge base. Main-exclusive
changes were confined to Trendline V2 generic-viewer plans, runner, and tests.
There was no overlap with mature trendlines, shared replay/identity code, or
D4A paths. No merge, rebase, or primary-checkout change was performed.

### 4. Event-timing decision

D4A holds mature-model event timing fixed. The population is the 43 committed
non-left-censored `BOUNDARY_RAY` births from D3: 24 support and 19 resistance.
Each event receives exactly one attempt for each frozen deterministic baseline
at the same timeframe, position, event time, availability time, role, ATR,
horizons, and break-confirmation policy. Results therefore compare geometry
conditional on mature-model event timing; they do not compare when geometry was
selected.

### 5. Baseline definitions

Only study-config baseline kinds were accepted, in committed order:

```text
RECENT_EXTREMA
HORIZONTAL_SUPPORT_RESISTANCE
```

`RECENT_EXTREMA` uses the latest two confirmed same-role pivots and the exact
line through their `(bar_position, price)` coordinates. `HORIZONTAL_SUPPORT_RESISTANCE`
uses the latest confirmed same-role pivot with slope `0` and intercept equal to
its price. Support selects low pivots; resistance selects high pivots. No fit,
regression, tolerance, optimisation, or alternate pivot substitution is used.

### 6. Pivot finality and causal binding

Pivots are obtained through `inspect_replay_pivots()` at each exact selection
prefix. Every pivot is required to be `confirmed_append_only`, causally before
the selection position, and bound to the event replay point, content, source,
checkpoint, boundary snapshot, and boundary revision identities. Baseline
geometry is frozen at selection and evaluated through the extracted D3 pure
future-OHLC helper.

### 7. Abstentions and coverage

```text
model events:                         43
selection attempts:                   86
available selections:                 86
abstentions:                           0
baseline outcomes:                   344
comparison summaries:                 16
```

Per baseline:

```text
RECENT_EXTREMA:
  support:     24 attempts, 24 available, 0 abstentions, coverage 1.0
  resistance:  19 attempts, 19 available, 0 abstentions, coverage 1.0

HORIZONTAL_SUPPORT_RESISTANCE:
  support:     24 attempts, 24 available, 0 abstentions, coverage 1.0
  resistance:  19 attempts, 19 available, 0 abstentions, coverage 1.0
```

### 8. Matched denominators and results

Model and baseline summaries use the same available-event subset for each
baseline. `me/mel/mrc` means model event count / matched eligible count /
right-censored count. Deltas are model minus baseline. Raw counts, rates,
means, and medians remain in `baseline_comparison_bundle.json`.

| baseline | role | horizon | model `me/mel/mrc` | baseline `me/mel/mrc` | coverage | Δ touch | Δ rejection | Δ confirmed break | Δ false break | Δ penetration | Δ favourable | Δ adverse |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| RECENT_EXTREMA | support | 1 | 24/24/0 | 24/24/0 | 1.0000 | 0.1250 | 0.0714 | 0.0000 | 0.0000 | -0.2667 | -0.6131 | -0.2667 |
| RECENT_EXTREMA | support | 3 | 24/24/0 | 24/24/0 | 1.0000 | 0.1250 | 0.1385 | -0.1746 | 0.1905 | -0.2240 | -0.1802 | 0.0506 |
| RECENT_EXTREMA | support | 6 | 24/24/0 | 24/24/0 | 1.0000 | 0.1250 | 0.1833 | -0.2614 | 0.2955 | -0.2621 | -0.4458 | -0.0593 |
| RECENT_EXTREMA | support | 12 | 24/23/1 | 24/23/1 | 1.0000 | 0.1739 | 0.1267 | -0.2000 | 0.2000 | -0.2118 | -0.5001 | -0.1848 |
| RECENT_EXTREMA | resistance | 1 | 19/19/0 | 19/19/0 | 1.0000 | 0.0526 | -0.1000 | 0.0000 | 0.0000 | 0.0366 | -0.1572 | 0.0366 |
| RECENT_EXTREMA | resistance | 3 | 19/19/0 | 19/19/0 | 1.0000 | 0.1053 | -0.0417 | 0.1000 | -0.0500 | 0.0031 | -0.0716 | -0.1930 |
| RECENT_EXTREMA | resistance | 6 | 19/18/1 | 19/18/1 | 1.0000 | 0.1111 | -0.2250 | 0.1143 | -0.0857 | 0.4884 | -0.5287 | 0.4924 |
| RECENT_EXTREMA | resistance | 12 | 19/18/1 | 19/18/1 | 1.0000 | 0.0556 | -0.2667 | 0.0333 | 0.0778 | 0.4943 | -0.2706 | 0.5813 |
| HORIZONTAL_SUPPORT_RESISTANCE | support | 1 | 24/24/0 | 24/24/0 | 1.0000 | 0.2083 | 0.5714 | 0.0000 | 0.0000 | -0.6756 | 0.1281 | -0.6756 |
| HORIZONTAL_SUPPORT_RESISTANCE | support | 3 | 24/24/0 | 24/24/0 | 1.0000 | 0.2083 | 0.1635 | -0.0889 | -0.0667 | -0.5725 | 0.3709 | -0.2811 |
| HORIZONTAL_SUPPORT_RESISTANCE | support | 6 | 24/24/0 | 24/24/0 | 1.0000 | 0.1667 | 0.2364 | -0.1364 | 0.1705 | -0.4745 | 0.2688 | -0.0465 |
| HORIZONTAL_SUPPORT_RESISTANCE | support | 12 | 24/23/1 | 24/23/1 | 1.0000 | 0.2609 | 0.2246 | -0.2333 | 0.2333 | -0.4806 | 0.0062 | -0.5583 |
| HORIZONTAL_SUPPORT_RESISTANCE | resistance | 1 | 19/19/0 | 19/19/0 | 1.0000 | 0.2105 | 0.0000 | 0.0000 | 0.0000 | -0.1655 | -0.1138 | -0.1655 |
| HORIZONTAL_SUPPORT_RESISTANCE | resistance | 3 | 19/19/0 | 19/19/0 | 1.0000 | 0.2105 | 0.3750 | 0.3500 | -0.0500 | -0.3454 | -0.2509 | -0.1066 |
| HORIZONTAL_SUPPORT_RESISTANCE | resistance | 6 | 19/18/1 | 19/18/1 | 1.0000 | 0.1667 | -0.0286 | 0.0000 | -0.2000 | -0.1200 | -0.6021 | 0.1266 |
| HORIZONTAL_SUPPORT_RESISTANCE | resistance | 12 | 19/18/1 | 19/18/1 | 1.0000 | 0.0000 | -0.1000 | 0.0750 | -0.0750 | 0.1353 | -0.4025 | 0.8062 |

These values are reported without adequacy interpretation. Support and
resistance, baseline kind, and horizon remain separate coordinates.

### 9. D3 helper extraction

The narrow `measure_frozen_geometry_outcomes()` and
`build_interaction_summaries()` helpers remove duplicate D3 formulas. The
public summary helper now enforces the exact `(event_id, horizon)` Cartesian
product, rejecting duplicate, missing, extra, unknown, and unconfigured
coordinates. The committed D3 interaction bundle was reconstructed offline
with unchanged identity:

```text
56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
```

### 10. R1 audit-contract completion

The D4A comparison bundle now exposes explicit `interaction_spec_id` beside
its nested interaction specification. Validation requires this identity to
match both the nested spec and the committed D3 interaction spec. The run
manifest now inventories all 16 deterministic comparison-summary rows in
canonical order and requires exact equality with the bundle rows.

The prior bundle ID was:

```text
8580c523db1b7a57faf443e7e57a2e1493f06faea3bb462a046e651f52903360
```

The regenerated bundle ID is:

```text
664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663
```

Removing only the new explicit field reproduces the prior bundle ID. All
source, replay, D2/D3, baseline, count, rate, mean, median, and delta values
remain unchanged. No adequacy outcome was selected and no random/null baseline
was executed.

### 11. Bundle and source identities

```text
source artifact:
  artifacts/trendlines_research_validation/20260726_btcusdt_1h_single_call_v1/normalized_ohlcv_v2.json
  sha256 d6798e34731b4d8978e878c5f7703bdac187eed8c0917efe8f4344768f91c9d1
source_id       d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331
dataset_id      6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c
availability_id 9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1
preparation_id  ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141
replay_id       dc0783482b42bfec1beca1a45866ac0a40813cb144d390d28551ed0d419f0b78
cohort_id       9c3f9f6b099be611fcbd309a80483dc5b072d77ebd831de798370de52a9b7f69
study_config_id 07e634810f6be3a2223f7f8dde2aa778e68aa47d7003e12a92128fc4a65d3e1d
stability_spec_id 12d9aa6b154238092835fd9879422a8d57d0a52e61ba8863dd27e8b7822a6271
D2 bundle       f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
D3 bundle       56d42daeda8bfcfd6625a345c4aef40a9eb9bf63ced415f4a947b9ff546d93a4
interaction_spec_id df6f3cfa6dd9656de4e34d0eb1302a7726db6c5cd9106a700203aad810b9d98f
D4A bundle       664a23b5110cea4a3f9370df9d465da3c07c70ceaaae96f29ad8841f31bb7663
```

Artifact file checksums:

```text
baseline_comparison_bundle.json e49a2f7c0129cbedce9c3b520fd0e9a2047c089ae9f83cccd055422e905e0b50
run_manifest.json                eb170e3eb261a29536caedf8aaa7dc3d4249406d0fae64c4b86bbee2a6e3f09b
review.md                        096fe330b3abaff4053d1ec9463b31bbaa4546a7b670c3f02120348291defe48
```

### 12. Tests and validation

Current recorded validation disposition:

```text
D4A focused:              36 passed
D4A script:                 4 passed
D3 focused:               48 passed
Canonical mature suite:  634 passed
Viewer Python:            30 passed
Viewer Node/TypeScript:   23 passed
Consumer/bridge:          79 passed
Offline workflows:        20 passed
Provider calls/retries:    0 / 0
Ruff/compileall/diff-check: passed
```

The bounded script loads only the committed L2-C frame artifact and committed
D2/D3 evidence. It contains no provider construction or structural, pivot,
outcome, summary, delta, or identity algorithm.

### 13. Abstractions deliberately not added

No tracker, matching engine, evaluator class, registry, manager, repository,
database, factory, plugin interface, generic metric executor, randomisation
framework, or new configuration loader was added. D4A uses pure functions and
existing D3 outcome/summary contracts.

### 14. Residual risks

The sample is one BTCUSDT 1h cohort with 43 mature-model events, and D4A holds
event timing fixed. Coverage is complete for both deterministic baselines in
this bounded run, but timing quality and cross-window/cross-asset robustness
remain unmeasured. D4B random/density-matched nulls and later adequacy decisions
remain unauthorised.

### 15. Hardcoding classification

The source, D2/D3 artifact paths, expected committed identities, implementation
base commit, and bounded study scope are explicit study controls in the thin
offline script. Baseline kinds, horizons, confirmation policy, and model
parameters are not invented there; they are read from the frozen study/replay
configuration and validated against committed evidence.

### 16. Recommended next phase

Review D4A evidence before deciding whether to authorise L2-D4B seeded random
and density-matched nulls. Do not infer adequacy from this descriptive bundle.
