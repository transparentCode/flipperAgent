# Mature Trendlines L0-B Causality and Repaint-Risk Audit

## 1. Disposition

Read-only audit complete. No implementation, test, configuration, documentation,
artifact, provider, network, or Trendline V2 change was made.

Primary disposition: `READY_FOR_L0B_CAUSALITY_REVIEW`

Evidence supports `L1-A — Pivot finality remediation` as next phase. Highest-risk
findings are Fractal equal-plateau pivot revision, RDP whole-frame retrospective
simplification, and missing public snapshot finality/revision semantics.

## 2. Starting branch and commit

```text
branch: research/legacy-trendlines-quality-stability-v1
starting HEAD: d9744969deea040e4ef073c3c39d1d282cec4386
starting subject: test: close legacy trendlines consolidation
starting worktree: clean
```

Consolidation checkpoint was committed before this audit. Canonical package tree:

```text
git rev-parse HEAD:src/libs/models/trendlines
a186219ce5ca1eb479ef2e8e64fc86b9d2f10e0f

tracked files: 147
```

## 3. Worktree and environment proof

```text
Python: 3.13.13
Ruff: 0.15.20
PYTHONPATH: $PWD/src:$PWD
provider/network calls: none
Binance fetches: none
```

Codebase-memory indexing was attempted for this isolated checkout and crashed on
one file; live source inspection was used afterward. No index artifact or source
file was modified.

## 4. Canonical package identity

```text
src/libs/models/trendlines/
namespace: libs.models.trendlines
tracked files: 147
Trendline V2 audited only for preservation, not behavior
```

Public signatures inspected:

```text
fit_trendlines(df, *, config, extractor, fitter, extractor_kwargs, fitter_kwargs)
fit_trendlines_to_boundary(df, *, asset, timeframe, ...)
fit_and_signal(df, *, asset, timeframe, ..., history, context)
```

None exposes `as_of`, `confirmed_only`, provisional/final status, snapshot ID,
checkpoint, revision ID, or a causal-history repository. `TrendlineOutput`,
`TrendlineFitResult`, `BoundaryResult`, and `TrendlineSnapshot` likewise carry no
explicit finality or revision contract.

## 5. Public entrypoint inventory

`fit_trendlines` runs extract → fit and returns current-frame output.
`fit_trendlines_to_boundary` adds boundary adaptation using `df.index[-1]`.
`fit_and_signal` adds runtime profile/config resolution, boundary adaptation, and
signals from caller-supplied history/context. All are causal only when callers
pass a point-in-time prefix and correctly ordered context/history.

`run_trendline_pipeline` resolves an extractor/fitter, extracts from supplied
`df`, fits against supplied pivots, and adds current pipeline metadata. It does
not attach checkpoint, finality, or revision identity.

## 6. Data-horizon map

| Component | Horizon and state | Classification | Scope | Severity | Disposition |
|---|---|---|---|---|---|
| `fit_trendlines` | Complete supplied frame; current snapshot only | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| `fit_trendlines_to_boundary` | Fit plus full supplied-frame ATR/interaction; timestamp is last row | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| `fit_and_signal` | Prefix-safe only if `df`, history, and context are aligned | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| `run_trendline_pipeline` | Uses only supplied `df`; no finality metadata | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| `FractalPivotExtractor` | Left/right sliding windows; right-window confirmation; equal-pivot midpoint | `CAUSAL_WITH_CONFIRMATION_DELAY`, `PREFIX_REVISING`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_IMPLEMENTATION` |
| `RDPZigZagPivotExtractor` | Complete close path, forced first/final endpoints, complete-frame mean ATR | `PREFIX_REVISING`, `RETROSPECTIVE_ONLY`, `AMBIGUOUS_CONTRACT` | runtime/research | HIGH | `RESTRICT_TO_RESEARCH` |
| `LeastSquaresFitter` | Supplied pivots and full supplied-frame ATR; deterministic | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| `PathfindingFitter` | Supplied pivots and body prices in supplied frame; deterministic tie order | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| `RansacFitter` | Supplied pivots, full-frame mean ATR, random pair sampling | `CAUSAL`, `NONDETERMINISTIC_OPTION`, `AMBIGUOUS_CONTRACT` | runtime/research | MEDIUM | `REMEDIATE_CONTRACT` |
| `EnsembleFitter` | Three sub-fitters; catches sub-fitter exceptions; partial lines remain valid | `CAUSAL`, `FAIL_OPEN_PARTIAL`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| Boundary adapter | Current close, full supplied-frame ATR, projected rays, last-index timestamp | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| `BoundaryResult` / snapshot history | Timestamp exists; no identity/finality; insertion order accepted | `AMBIGUOUS_CONTRACT` | runtime | HIGH | `REMEDIATE_CONTRACT` |
| Structural signals | Current boundary only; no future bars | `CAUSAL` | runtime | LOW | `RETAIN` |
| Temporal signals | Caller history list; no ordering/future validation | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| Pattern signals | Current ray slopes only | `CAUSAL` | runtime | LOW | `RETAIN` |
| Fakeout signals | Caller history plus caller context `ohlcv`/ATR; no timestamp alignment | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| Quality helpers | Current result and supplied metrics only | `CAUSAL` | runtime | LOW | `RETAIN` |
| Signal orchestrator | Catches extractor exceptions and computes composite from survivors | `FAIL_OPEN_PARTIAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| Asset profile/config resolution | Full supplied-frame mean ATR/price and fit-result statistics | `CAUSAL`, `AMBIGUOUS_CONTRACT` | runtime | MEDIUM | `REMEDIATE_CONTRACT` |
| Temporal split construction | Train/test order is causal; purge only when configured | `CAUSAL`, `AMBIGUOUS_CONTRACT` | offline | MEDIUM | `REMEDIATE_CONTRACT` |
| Forward benchmarks | Test bars intentionally score future reaction/penetration | `OFFLINE_FORWARD_LABEL_ONLY` | offline | INFORMATIONAL | `RETAIN` |
| Pipeline evaluation/walk-forward | Fits train frame, scores test frame; wrapper default purge is zero | `OFFLINE_FORWARD_LABEL_ONLY`, `AMBIGUOUS_CONTRACT` | offline | MEDIUM | `REMEDIATE_CONTRACT` |
| Bayesian optimizer | Offline folds; failed folds become zero score; sampler seed fixed at 42 | `OFFLINE_FORWARD_LABEL_ONLY` | offline | LOW | `RETAIN_WITH_DOCUMENTED_DELAY` |

Component count: 23.

Classification counts overlap by design:

```text
CAUSAL:                         15
CAUSAL_WITH_CONFIRMATION_DELAY: 1
PREFIX_REVISING:                2
RETROSPECTIVE_ONLY:             1
NONDETERMINISTIC_OPTION:        1
FAIL_OPEN_PARTIAL:              2
OFFLINE_FORWARD_LABEL_ONLY:     3
AMBIGUOUS_CONTRACT:            18
```

## 7. Pivot causality findings

### Fractal

Source: `src/libs/models/trendlines/pivots/fractal.py:48-61,81-95`.

The extractor emits candidates only through `len(df) - window_right`, so ordinary
isolated pivots have a right-window confirmation delay. It then groups contiguous
equal-value candidates and chooses `group[len(group) // 2]`. Later equal bars can
add candidates to that group and move the selected midpoint.

Finding: ordinary isolated pivots are causal with confirmation delay; equal-price
plateaus are prefix-revising. Existing output has no provisional/final marker.

### RDP ZigZag

Source: `src/libs/models/trendlines/pivots/rdp_zigzag.py:41-57,60-89,105-145`.

The extractor forces first and final rows as RDP endpoints, computes rolling ATR
then mean ATR over the complete supplied frame, simplifies the complete close path,
and classifies interior points using adjacent retained points. Appending bars can
change endpoint geometry, retained points, classifications, and epsilon.

Finding: retrospective/prefix-revising. Not suitable for immutable live pivots
without a separate checkpoint/finality contract.

## 8. Fractal plateau evidence

Fixture case: flat 100-price frame, high plateau begins at index 20, extractor
`window_left=3`, `window_right=3`. Plateau pivot selected while prefix extends:

| Plateau length | Selected high-pivot indices as equal bars arrive |
|---:|---|
| 2 | `20 → 21` |
| 3 | `20 → 21` |
| 4 | `20 → 21 → 22` |
| 8 | `20 → 21 → 22 → 23 → 24` |

For length 8, a higher follow-on high appeared later as a new pivot after its own
right-window delay. A lower follow-on left the plateau midpoint revised. The first
index was already emitted after the nominal three-bar delay, then disappeared from
the next snapshot. Finality cannot be inferred from existing `PivotSet` fields.

## 9. Deterministic fixture and prefix replay

Ephemeral fixture only; no file persisted:

```text
400 hourly UTC bars
numpy default_rng(42)
trend + two cyclic components + volatility regimes
equal high plateau: indices 120:128
equal low plateau: indices 210:220
late high-volatility suffix: indices >= 320
```

Canonical hash method: SHA-256 of compact sorted-key JSON containing nanosecond
index values and float OHLCV columns in `open,high,low,close,volume` order.

```text
fixture hash:
851e334c005cfde7f7cc3723b62866124a92900e61eabf0c82add24361f22e16
```

Prefix replay used every `df.iloc[:n]` for `n=20..400` (381 prefixes).

```text
Fractal: 9 adjacent prefix steps removed/moved prior pivot tuples.
  example: prefix 124 -> 125 removed (120, 106.9451763456, high)
  example: prefix 214 -> 215 removed (210, 104.6995473995, low)

RDP: 86 adjacent prefix steps removed/moved prior pivot tuples.
  example: prefix 34 -> 35 removed (30, 103.4052423444, high)

Every extractor/fitter combination: 381 distinct current snapshots and
380 adjacent snapshot changes. These changes are current-prefix revisions,
not by themselves proof of repainting; contracts do not label revision state.

fit_trendlines:              381 distinct fit snapshots, no errors
fit_trendlines_to_boundary:  381 distinct fit snapshots, no errors
fit_and_signal:              381 distinct fit snapshots, no errors
```

## 10. RDP suffix-perturbation evidence

Historical prefix: first 260 fixture bars. Each suffix appended 40 bars. Prior
pivot tuples were compared after restricting combined output to indices `<260`.

| Suffix | Prior tuples removed | Prior tuples added | Result |
|---|---:|---:|---|
| flat | 0 | 0 | unchanged in this case |
| strong up | 0 | 1 | prior output changed |
| strong down | 1 | 2 | prior output changed |
| high volatility | 21 | 0 | major prior-output rewrite |
| low volatility | 0 | 1 | prior output changed |

RDP epsilon was recomputed from complete-frame mean ATR for every combined frame.
Finding: RDP must be marked retrospective/revisable, not live immutable.

## 11. Fitter determinism evidence

Frame: fixture prefix of 300 bars; 20 repeated fits; default RANSAC
`max_trials=250` in this experiment.

```text
RANSAC seed=42:  1 distinct hash; line counts [2]; slopes/intercepts/scores stable
RANSAC seed=7:   1 distinct hash; line counts [2]; stable
RANSAC seed=123: 1 distinct hash; line counts [2]; stable
RANSAC seed=None: 6 distinct hashes; line counts [2];
                  4 slope variants; 4 intercept variants; 6 score variants

LeastSquares: 1 distinct hash across 20 runs
Pathfinding:  1 distinct hash across 20 runs
Ensemble:     1 distinct hash across 20 runs
```

Fixed seed is deterministic. `seed=None` is an exposed nondeterministic option,
not evidence that default RANSAC is nondeterministic.

## 12. Ensemble and signal failure evidence

Controlled in-memory monkeypatching made each ensemble sub-fitter fail separately,
in pairs, and all together.

```text
one sub-fitter failure:  is_valid=True; 2 support + 2 resistance lines remain
two failures:            is_valid=True; 1 support + 1 resistance line remains
all failures:             is_valid=False; no lines
```

`EnsembleFitter` records sub-fitter error strings in metadata, but partial output
still has normal `is_valid=True` semantics. This is `FAIL_OPEN_PARTIAL` for runtime
consumers.

Controlled signal extractor failure produced:

```text
signal_count=1
failed source -> []
healthy source -> one signal
composite_direction=0.5
composite_confidence=0.5
```

`TrendlineSignalOrchestrator` logs a warning, drops failed-source signals, and
returns a normal composite without an explicit degraded/error status.

## 13. Boundary and history findings

Source: `boundary/adapters.py:323-341,405-423`; `boundary/contracts.py:146-160`.

Boundary adaptation consumes current last-row price, rays projected at current
bar, and full supplied-frame ATR. It emits only `df.index[-1]` as timestamp.
`BoundaryResult` has no snapshot ID, finality, revision, or source checkpoint.

Source: `boundary/history.py:20-55,59-147`.

Ephemeral history probe added timestamps 02:00, 01:00, 01:00. Observed:

```text
history order: [02:00, 01:00, 01:00]
latest:        01:00
history_before(02:00): [01:00, 01:00]
```

`add()` accepts out-of-order and duplicate snapshots; `latest()` means last
insertion, not greatest timestamp. `history_before()` filters timestamps but does
not sort or deduplicate. Raw signal history lists have no validation.

## 14. Signal-history findings

`signals/temporal.py:42-72,74-160` uses `history[-n:]`, `history[-1]`, and recent
sequence order directly. It assumes caller-supplied history is ordered and
past-only. `signals/fakeout.py:31-62,64-99,101-207` scans caller history and uses
`context["ohlcv"].iloc[-1]`; no timestamp alignment links context to result.
Structural, pattern, and quality paths use current supplied result only and showed
no future-bar read in source review.

## 15. Configuration-derivation findings

Source: `config/asset_profile.py:82-133`; `config/resolve.py:92-174`.

`AssetProfile.from_dataframe()` computes mean ATR, mean price, bar count, and
optional fit statistics across complete supplied `df`. `resolve_asset_config()`
derives signal/boundary parameters from that profile.

Same fixture, same configuration, prefix versus full frame:

```text
                 prefix 100       full 400
mean_atr         1.02880936       1.62820621
mean_price       101.9700         107.0196
mean_slope_abs   0.05798567       0.02723101
parallel_tol     0.00504467       0.00760705
slope_match_tol  0.02899283       0.01361550
```

Conclusion: causal when resolved separately on each prefix; unsafe if one
full-dataset resolved config is reused for historical prefixes. API does not make
prefix discipline explicit.

`forward_lookahead_bars` is derived from timeframe duration, not future prices.
Its use in scoring is an offline label horizon, not runtime inference leakage.

## 16. Optimisation/evaluation boundary

Source: `workflows/pipeline/evaluation.py:35-139,141-181`.

`run_pipeline_with_params()` fits only `train_df`. `evaluate_trendlines_on_forward()`
uses test highs/lows/closes and future bars after each test touch to calculate
longevity, penetration, and touch reaction. This is intentional
`OFFLINE_FORWARD_LABEL_ONLY` behavior.

Source: `data/temporal.py:65-121,126-304`.

Temporal manifests preserve train/test ordering and enforce `purge_bars` when a
positive value is supplied. However, `workflows/pipeline/temporal_spec.py:17-31`
sets `purge_bars=0` in `generate_windows()`, and
`resolve_pipeline_temporal_plan()` defaults `purge_bars=0`. `optimize_timeframe()`
calls that resolver without an explicit purge override. This differs from the
evaluation default object, which contains a 24-bar purge setting.

Finding: no observed train/test outcome flow into fitting; forward labels stay in
test scoring. Purge policy is not uniformly enforced by the pipeline wrapper and
needs an explicit contract decision.

Source: `optimization/optimizer.py:284-288,419-425`.

Offline fold exceptions become zero scores; final benchmark exceptions become an
empty benchmark result. This is not runtime partial inference, but it can obscure
offline failure causes and should remain visible in research reporting.

## 17. Complete audit matrix

| Component | Entrypoint | Data horizon | Confirmation delay | Prefix stable | Deterministic | Failure mode | Runtime/offline | Classification | Severity | Evidence | Disposition |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Public fit API | `fit_trendlines` | supplied frame | none exposed | current snapshot only | yes with fixed config | raises input errors | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | HIGH | no as-of/finality/revision fields | `REMEDIATE_CONTRACT` |
| Boundary facade | `fit_trendlines_to_boundary` | full frame ATR + current row | none | current snapshot only | yes | input validation | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | HIGH | adapter uses full ATR and last timestamp | `REMEDIATE_CONTRACT` |
| Signal facade | `fit_and_signal` | df + raw history/context | caller-defined | not guaranteed | yes fixed inputs | signal partial failure | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | HIGH | no alignment/finality contract | `REMEDIATE_CONTRACT` |
| Pipeline orchestrator | `run_trendline_pipeline` | supplied frame | extractor-dependent | no revision ID | yes fixed inputs | component errors propagate | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | current metadata only | `REMEDIATE_CONTRACT` |
| Fractal | `FractalPivotExtractor.extract` | left/right window | right-window bars | No on equal plateaus | yes | none | runtime | `CAUSAL_WITH_CONFIRMATION_DELAY`, `PREFIX_REVISING` | HIGH | plateau probe | `REMEDIATE_IMPLEMENTATION` |
| RDP ZigZag | `RDPZigZagPivotExtractor.extract` | complete close/ATR frame | none | No | yes fixed input | none | runtime/research | `PREFIX_REVISING`, `RETROSPECTIVE_ONLY` | HIGH | suffix perturbation | `RESTRICT_TO_RESEARCH` |
| Least squares | `LeastSquaresFitter.fit` | pivots + full prefix ATR | inherited | current snapshot only | yes | raises validation | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | 20/20 repeat | `REMEDIATE_CONTRACT` |
| Pathfinding | `PathfindingFitter.fit` | pivot/body prices in prefix | inherited | current snapshot only | yes | raises validation | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | 20/20 repeat | `REMEDIATE_CONTRACT` |
| RANSAC | `RansacFitter.fit` | pivots + full prefix ATR | inherited | current snapshot only | fixed seed only | seed option | runtime/research | `CAUSAL`, `NONDETERMINISTIC_OPTION` | MEDIUM | seed=None 6 hashes | `REMEDIATE_CONTRACT` |
| Ensemble | `EnsembleFitter.fit` | three prefix fitters + full ATR | inherited | partial current snapshot | fixed inputs | catches all sub-fitter exceptions | runtime | `CAUSAL`, `FAIL_OPEN_PARTIAL` | HIGH | partial failure probe | `REMEDIATE_CONTRACT` |
| Boundary adapter | `build_boundary_result_from_trendline_result` | complete supplied frame | none | no revision identity | yes | validation raises | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | HIGH | full ATR / timestamp | `REMEDIATE_CONTRACT` |
| Snapshot history | `TrendlineSnapshotHistory.add/latest` | caller snapshots | none | insertion-based | yes | accepts bad order | runtime | `AMBIGUOUS_CONTRACT` | HIGH | out-of-order probe | `REMEDIATE_CONTRACT` |
| Structural signals | `StructuralSignalExtractor.extract` | current boundary | none | yes if boundary causal | yes | orchestrator catches | runtime | `CAUSAL` | LOW | current result only | `RETAIN` |
| Temporal signals | `TemporalSignalExtractor.extract` | raw history sequence | min-history only | caller-dependent | yes | orchestrator catches | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | `history[-n:]` | `REMEDIATE_CONTRACT` |
| Pattern signals | `PatternSignalExtractor.extract` | current rays/slopes | none | yes if result causal | yes | orchestrator catches | runtime | `CAUSAL` | LOW | current result only | `RETAIN` |
| Fakeout signals | `FakeoutSignalExtractor.extract` | raw history + raw context | hold bars only | caller-dependent | yes | orchestrator catches | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | no context timestamp check | `REMEDIATE_CONTRACT` |
| Quality helpers | quality extractors | current result/metrics | none | yes if input causal | yes | caller validation | runtime | `CAUSAL` | LOW | no future read | `RETAIN` |
| Signal orchestrator | `TrendlineSignalOrchestrator.run` | all supplied extractor inputs | extractor-defined | partial output | yes fixed inputs | catches extractor exceptions | runtime | `FAIL_OPEN_PARTIAL` | MEDIUM | failed source returned empty | `REMEDIATE_CONTRACT` |
| Config profile | `AssetProfile.from_dataframe` | complete frame + fit result | none | prefix-only use required | yes | fails loud on bad input | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | prefix/full profile drift | `REMEDIATE_CONTRACT` |
| Config resolver | `resolve_asset_config` | profile from supplied frame | none | prefix-only use required | yes | validation raises | runtime | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | derived params drift | `REMEDIATE_CONTRACT` |
| Temporal splits | `build_temporal_split_manifest` | index ranges | purge if positive | yes | yes | invalid spec raises | offline | `CAUSAL`, `AMBIGUOUS_CONTRACT` | MEDIUM | wrapper default zero purge | `REMEDIATE_CONTRACT` |
| Forward benchmarks | `evaluate_trendlines_on_forward` | future test bars | configured lookahead | N/A runtime | yes | empty data returns zero metrics | offline | `OFFLINE_FORWARD_LABEL_ONLY` | INFORMATIONAL | test-only slices | `RETAIN` |
| Pipeline evaluation | `walk_forward_evaluate` | train fit + test labels | split policy | yes with manifest | yes | invalid fit gets zero window | offline | `OFFLINE_FORWARD_LABEL_ONLY`, `AMBIGUOUS_CONTRACT` | MEDIUM | zero-purge wrapper default | `REMEDIATE_CONTRACT` |
| Optimizer | `TrendlinesOptimizer` | train/test folds | validator/config | yes per fold | sampler seed 42 | fold exceptions score zero | offline | `OFFLINE_FORWARD_LABEL_ONLY` | LOW | exception catches | `RETAIN_WITH_DOCUMENTED_DELAY` |

## 18. Severity-ranked findings

### HIGH-1 — Fractal plateau pivot finality failure

```text
source: src/libs/models/trendlines/pivots/fractal.py
method: FractalPivotExtractor.extract/_deduplicate_equal_pivots
reproduction: window_right=3, equal high plateau at index 20; append equal bars
observed: selected pivot 20 -> 21 -> 22 -> 23 -> 24
affected entrypoints: all facades using fractal extractor by default
tests gap: existing tests validate snapshots, not append-only prefix finality
```

### HIGH-2 — RDP retrospective output exposed as selectable pipeline extractor

```text
source: src/libs/models/trendlines/pivots/rdp_zigzag.py
method: extract/_rdp_iterative/_compute_atr
reproduction: append five 40-bar suffix variants to a 260-bar prefix
observed: high-volatility suffix removed 21 prior pivots; down suffix removed 1
and added 2; epsilon recomputed from combined-frame mean ATR
affected entrypoints: fit_trendlines, fit_trendlines_to_boundary, fit_and_signal
tests gap: final-frame correctness tests do not assert suffix stability
```

### HIGH-3 — No enforceable live snapshot finality/revision contract

```text
source: api.py; boundary/contracts.py; boundary/history.py
method: public facades, BoundaryResult, TrendlineSnapshotHistory.add/latest
reproduction: add snapshots at 02:00, 01:00, 01:00
observed: latest returns last insertion; duplicates/out-of-order values accepted
affected entrypoints: fit_and_signal and all history-driven temporal/fakeout paths
tests gap: no contract test for future rejection, ordering, revision identity, or
immutable as-of retrieval
```

### MEDIUM findings

```text
M1  Ensemble partial failures remain is_valid=True and reach consumers.
M2  Signal extractor failures become empty by-source results with normal composite.
M3  Full-frame profile/ATR derivation changes historical parameters if reused.
M4  RANSAC seed=None produces six result hashes in 20 identical runs.
M5  Raw temporal/fakeout history/context lacks timestamp alignment validation.
M6  Pipeline temporal wrapper defaults purge_bars=0 despite 24-bar evaluation default.
M7  Offline optimizer catches fold errors and converts them into zero/empty results.
```

No CRITICAL finding. No evidence of forward test outcomes entering production
inference or train-frame fitting was found.

## 19. Confirmed-safe contracts

```text
Fractal isolated non-tie candidates use only left/current/right bars and wait for
window_right bars before candidate availability.

Least-squares, pathfinding, and fixed-seed RANSAC are deterministic for identical
frame, pivots, and configuration.

RANSAC default seed=42 is repeatable; nondeterminism is isolated to seed=None.

Forward longevity, penetration, and touch-reaction labels consume future bars only
inside offline test evaluation.

Walk-forward fitting receives train_df; test_df is passed to scoring, not fitting.

Structural, pattern, and quality signal code paths read current supplied results,
not future bars directly.
```

## 20. Ambiguous contracts

```text
Current-prefix output versus immutable historical output is not distinguished.
No public as_of/checkpoint/finality/revision field exists.
RDP can be selected through normal runtime facades despite retrospective behavior.
Boundary history insertion order is not guaranteed to match event time.
Signal history/context may contain future or mismatched timestamps without rejection.
Full-frame derived config is safe only under caller-enforced prefix execution.
Pipeline purge behavior differs between configured/default paths.
Partial runtime failures do not always produce degraded status.
```

## 21. Recommended remediation order

1. `L1-A` pivot finality remediation: define immutable checkpoint semantics; fix or
   restrict Fractal plateau handling; keep RDP research-only unless redesigned.
2. Add public snapshot contract: `as_of`, final/provisional status, revision ID,
   ordered/future-rejecting history, and aligned signal context.
3. Define degraded-result semantics for ensemble and signal partial failure.
4. Make prefix-only profile/ATR/config usage explicit and test full-frame reuse as
   forbidden for historical replay.
5. Resolve pipeline purge policy and persist the effective temporal split manifest.
6. Keep RANSAC fixed-seed default; document or reject `seed=None` for production.

## 22. Tests executed

```text
src/libs/models/trendlines/tests: 266 collected, 266 passed
```

Additional validation was ephemeral Python only:

```text
381-prefix replay across extractors, fitters, and three public facades
Fractal plateau cases: shorter/equal/longer/growing and higher/lower follow-ons
RDP flat/up/down/high-volatility/low-volatility suffix perturbations
RANSAC seeds 42/7/123/None, 20 repeats each
Least-squares/pathfinding/ensemble, 20 repeats each
Ensemble one/two/all controlled sub-fitter failures
Signal orchestrator controlled extractor failure
Boundary history out-of-order/duplicate probe
AssetProfile/config prefix-versus-full comparison
```

## 23. Files changed

```text
A plans/coder-to-orchestrator-trendlines-l0b-causality-audit-v1.md
```

No implementation, tests, configuration, artifacts, benchmarks, research files,
or Trendline V2 files changed.

## 24. Git status

Expected final status after handoff creation:

```text
?? plans/coder-to-orchestrator-trendlines-l0b-causality-audit-v1.md
```

No commit was made for L0-B.

## 25. Residual risks

Findings are based on deterministic synthetic OHLCV and source-level contracts.
No provider data or production replay was used. Real feeds may expose additional
timestamp, missing-bar, timezone, duplicate-index, or volume-quality interactions.
Those are follow-up risks, not reasons to weaken this evidence.

## 26. Recommended next phase

```text
L1-A — Pivot finality remediation
```

Do not start remediation in this audit.

READY_FOR_L0B_CAUSALITY_REVIEW
