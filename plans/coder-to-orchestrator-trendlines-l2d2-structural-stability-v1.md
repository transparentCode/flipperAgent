# Coder-to-Orchestrator Handoff: L2-D2 Structural Stability

## 1. Disposition

L2-D2 is implemented as a descriptive, causal structural-stability measurement layer. No adequacy outcome is selected. The bounded real-market measurement ran offline from the committed L2-C frame artifact with zero provider calls. Commit remains intentionally pending independent review.

## 2. Branch and starting commit

~~~text
branch: research/trendlines-adequacy-v1
starting commit: b839f5d593d47df186814563fe6fcd38984c85a6
starting subject: feat: add causal trendline adequacy foundation
mature-trendlines integration checkpoint: 29a068a9032b826f88a859623b52faaeedeaee93
parallel main changes: Trendline V2 only; no D2 synchronization performed
~~~

## 3. Changed paths

~~~text
M  src/libs/models/trendlines/workflows/research/adequacy/__init__.py
A  src/libs/models/trendlines/workflows/research/adequacy/stability.py
A  src/libs/models/trendlines/tests/research_adequacy/test_stability.py
A  scripts/analyze_trendlines_l2d2_structural_stability.py
A  tests/scripts/test_analyze_trendlines_l2d2_structural_stability.py
M  src/libs/models/trendlines/docs/research.md
M  src/libs/models/trendlines/docs/workflows.md
?? artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d2_structural_stability_v1/
~~~

No model, YAML, notebook, viewer, provider, replay-execution, or L2-C source implementation path changed.

## 4. Structural keys

Fitted-line anchors use exact roleless key:

~~~text
(timeframe, method, start_position, end_position)
~~~

Boundary-ray anchors use:

~~~text
(timeframe, start_time, end_time)
~~~

Ordinal, evidence ID, replay-point ID, revision ID, fuzzy slope matching, rounded geometry, and configurable tolerances are excluded. Role is attached state. Duplicate roleless anchors at one coordinate fail closed.

## 5. Structural states and identities

Each eligible line/ray observation becomes one immutable structural state with cohort, stability-spec, coordinate, event/availability times, exact shape, quality fields, replay/content/source/checkpoint identities, boundary snapshot and revision identities, and a content-addressed state_id.

The stability spec requires explicit ordered positive horizons:

~~~text
survival_horizons_bars: (1, 3, 6, 12)
stability_spec_id: 12d9aa6b154238092835fd9879422a8d57d0a52e61ba8863dd27e8b7822a6271
~~~

## 6. Transition formulas

Transitions compare adjacent eligible recorded observations in replay order and retain the bar-position gap. For roleless anchor sets previous and current:

~~~text
persistent = previous intersection current
births = current minus previous
disappearances = previous minus current
shape revisions = persistent anchors whose exact shape tuple changed
role switches = persistent anchors whose role changed

anchor persistence rate = persistent / previous active
birth rate = births / current active
disappearance rate = disappearances / previous active
revision churn = shape revisions / persistent
~~~

Undefined zero-denominator rates are None. Aggregate rates use summed numerators and denominators, not averages of transition rates.

## 7. Shape, quality, and drift

Line shape is (start_value, end_value, slope, intercept) with quality (touch_count, score). Ray shape is (start_price, end_price, slope, intercept) with quality (touch_count, quality, r_squared). Exact shape changes alone increment revision counts. Quality-only changes do not. Descriptive drift rows report requested slope/intercept, endpoint, touch, score/quality, and R-squared deltas; no stability label or threshold is applied.

## 8. Episodes and censoring

Episodes continue only across consecutive eligible recorded positions. A disappearance followed by reappearance starts a new episode. Each episode records first/last positions, observed positions, span, roles, role switches, shape revisions, and left/right censoring.

Survival uses observed births only. For each explicit horizon, target_position = first_position + horizon. Targets must be exact eligible recorded positions. Targets beyond scoped end are right-censored; targets inside scope but absent from recorded position set are unavailable. No interpolation is performed. Survival denominators exclude both categories.

## 9. Canonical causal integrity

build_structural_stability_bundle() validates every replay point with canonical validate_replay_point_integrity() before consuming diagnostic rows. It reuses collect_adequacy_observations(), replay_line_rows(), and replay_ray_rows(); it does not rerun model execution. Bundle identity binds cohort/study/spec IDs, eligible observation identities, state IDs, transitions, drift, episodes, survival, summaries, and semantics. Timing/path/wall-clock values are excluded.

## 10. Bounded offline source binding

Only this committed artifact was loaded:

~~~text
artifacts/trendlines_research_validation/20260726_btcusdt_1h_single_call_v1/normalized_ohlcv_v2.json
sha256: d6798e34731b4d8978e878c5f7703bdac187eed8c0917efe8f4344768f91c9d1
~~~

The reloaded frame has 312 rows. L2-C source, availability, dataset, preparation, and replay identities were required to match exactly:

~~~text
source_id:       d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331
availability_id: 9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1
dataset_id:      6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c
preparation_id:  ff653424e4e848a52666859f14c819c517f79a13d3bc980431bbadc5d15b8141
replay_id:       dc0783482b42bfec1beca1a45866ac0a40813cb144d390d28551ed0d419f0b78
~~~

Replay scope was warm-up 19, record start 64, end 311, stride 1: 293 executed positions and 248 recorded positions. Provider calls and retries: 0 and 0.

## 11. Bounded measurement counts

~~~text
eligible observations: 248
invalid observations:  0
excluded observations: 0

fitted-line states:       496
boundary-ray states:      496
fitted-line transitions:  247
boundary-ray transitions: 247
fitted-line drift rows:   451
boundary-ray drift rows:  451
fitted-line episodes:     45
boundary-ray episodes:    45
survival rows:            8
~~~

Per-unit summaries:

~~~text
unit          active mean/min/max  births  disappearances  persistent  revisions  role switches  episodes
FITTED_LINE   2.0 / 2 / 2          43      43               451         0          0              45
BOUNDARY_RAY  2.0 / 2 / 2          43      43               451         0          0              45
~~~

Survival rows, identical by unit in this bounded run:

~~~text
horizon  observed births  eligible targets  survived  failed  right-censored  unavailable  rate
1        43                43                 43        0       0               0            1.0
3        43                43                 43        0       0               0            1.0
6        43                42                 28        14      1               0            0.6666666666666666
12       43                41                 11        30      2               0            0.2682926829268293
~~~

These are measurements only. They are not interpreted as adequate, stable, unstable, useful, or unusable.

## 12. R1 remediation

R1 corrected per-unit active-anchor summaries to filter both observation unit and timeframe. Transition contracts now enforce position gaps, count conservation, and exact count-derived rates, including None for zero denominators. Survival contracts enforce count conservation and exact survival rates. Episodes require explicit ordered observed positions; no intermediate positions are synthesized. Bundle validation recomputes transitions, drift, episodes, and per-unit summaries from stored rows, and verifies survival unit/timeframe membership. Manifest closeout uses implementation_base_commit and validated test disposition. The 1,739-line stability module remains intentionally unsplit; size consolidation is post-semantics technical debt, not an R1 redesign target.

## 13. Artefacts and identity

Output directory:

~~~text
artifacts/trendlines_research_adequacy/20260727_btcusdt_1h_l2d2_structural_stability_v1/
~~~

Files:

~~~text
run_manifest.json
structural_stability_bundle.json
review.md
checksums.json
~~~

Corrected bundle ID:

~~~text
f74fcfe1a16c0a3b489aeb61090c861d49c91fc578a31c9217673d8b581d254f
~~~

run_manifest.json uses:

~~~text
implementation_base_commit: b839f5d593d47df186814563fe6fcd38984c85a6
test_disposition.status: PASSED
provider_calls: 0
provider_retries: 0
outcome: null
~~~

Final artefact checksums:

~~~text
review.md:                       625 bytes  3d24c33240f234ab7cc5a4154baf4a7c98926c03cb10a789036ea89f2e2f76dc
run_manifest.json:              5068 bytes  30b7ab9c3ed0ea4525952392aea77620831e7d60d38a8d1a683cd7e25890f30c
structural_stability_bundle.json 2355809 bytes  45334acedac1d9162e1c4591bc6ea9da54e08d57d045a61f220a2f7c62818701
~~~

## 14. Tests and validation

Final validation:

~~~text
structural stability focused tests: 30 passed
offline analysis-script tests:        4 passed
canonical mature trendlines:        550 passed
viewer Python:                       30 passed
viewer Node/TypeScript:              23 passed
consumer/ingestion/bridge:           79 passed
offline workflows:                   20 passed
provider calls:                       0
Ruff:                              passed
compileall:                        passed
diff-check:                        passed
~~~

The 550 canonical tests include the 27 L2-D1 adequacy tests and 30 D2
structural tests in addition to the pre-existing mature-trendlines suite.

## 15. Deliberately absent abstractions

No tracker, matching engine, registry, manager, repository, database, factory, plugin interface, generic metric executor, or configuration loader was added. Pure functions and frozen result dataclasses compose existing validated APIs.

## 16. Hardcoding classification

The 1h BTCUSDT bounds, artifact path, expected L2-C identities, replay window, study scope, and explicit (1, 3, 6, 12) horizons are bounded-study protocol constants. They are not model parameters and are checked as expected evidence. Structural keying, transition, episode, drift, and survival algorithms are implemented in package APIs, not in the offline script. The script is a thin artifact consumer and writer.

## 17. Residual risks

This run covers one asset, one timeframe, and one bounded historical cohort. It does not establish interaction utility, null-relative performance, cross-window robustness, cross-asset behavior, predictive outcomes, or any promotion decision. Exact shape comparison intentionally has no floating-point tolerance; that is the frozen D2 identity rule. Lines and rays may share geometry in this source, but remain separate observation units and bundles.

## 18. Recommended next phase

Independent structural review first. Only after review may the project proceed to L2-D3 causal interaction utility measurements.
