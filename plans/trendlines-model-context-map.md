# Trendlines Model Context Map

Status: context-only review, no source-code changes.
Canonical active package: `src/libs/trendlines`.
Compatibility import package: `src/app/trendlines`.
Legacy duplicate package: `src/libs/models/trendlines_old`.

This file is a durable file-by-file and pipeline-flow context map for future quant work on the trendlines model. It should be read before adapting trendlines into RegimeV2, market-geometry features, signal confluence, or optimizer workflows.

---

## 1. High-Level Ownership

`src/libs/trendlines` owns reusable trendline/market-geometry logic:

1. Pivot extraction from OHLCV.
2. Support/resistance line fitting.
3. Conversion of fitted lines into boundary/ray contracts.
4. Native trendline signal extraction.
5. Dataset and walk-forward contracts.
6. Hyperparameter optimization and workflow promotion.
7. Drift monitoring.

Out of scope for this package:

- Portfolio/position sizing.
- Strategy execution.
- Cross-domain confluence with regime/oscillators beyond native trendline outputs.
- RegimeV2 policy decisions. RegimeV2 should consume compact trendline features, not trendline internals.

---

## 2. Important Path Clarification

The active package is:

```text
src/libs/trendlines
```

The repo also contains:

```text
src/libs/models/trendlines_old
```

That old package currently duplicates canonical symbols such as `Ray`, `BoundaryResult`, `QualityMetrics`, and boundary adapter functions. Trendlines tests mostly pass, but the import-boundary canonical-definition test fails because `trendlines_old` still defines symbols that should only live under `src/libs/trendlines/boundary`.

Compatibility shim:

```text
src/app/trendlines/__init__.py
```

This shim points `app.trendlines` imports at `src/libs/trendlines`, so many active modules import via `app.trendlines.*` even though the files physically live in `src/libs/trendlines`.

---

## 3. Layer Model

Observed dependency direction:

```text
Public API / CLI
  -> workflows
  -> data / signals / boundary
  -> pipeline
  -> registry
  -> pivots / fitting
  -> config
  -> contracts
```

Core rule: lower layers should not import upper layers.

Stable seams:

| Operation | Preferred seam |
|---|---|
| Public package imports | `src/libs/trendlines/__init__.py` or `app.trendlines` shim |
| Fit only | `fit_trendlines()` |
| Fit + boundary | `fit_trendlines_to_boundary()` |
| Full native signal output | `fit_and_signal()` |
| Oscillator-space line fitting | `fit_oscillator_to_boundary()` |
| Build extractor | `build_extractor(name, **kwargs)` |
| Build fitter | `build_fitter(name, **kwargs)` |
| Low-level extract -> fit | `run_trendline_pipeline()` |
| Config-driven pipeline | `execute_trendline_pipeline()` |
| Boundary adaptation | `build_boundary_result_from_trendline_result()` |
| Native signals | `TrendlineSignalOrchestrator` |
| Optimization | `optimize_trendlines()` / `TrendlinesOptimizer` |
| RegimeV2 consumption | `TrendlineFeatureProducer` in RegimeV2 adapter |

---

## 4. Runtime Pipeline Flows

### 4.1 Fit-Only Flow

Entry point:

```python
fit_trendlines(df, extractor="fractal", fitter="pathfinding", ...)
```

Flow:

```text
OHLCV DataFrame
  -> execute_trendline_pipeline()
  -> run_trendline_pipeline()
  -> build_extractor(name)
  -> extractor.extract(df) -> PivotSet
  -> build_fitter(name)
  -> fitter.fit(df, pivots) -> TrendlineFitResult
  -> TrendlineOutput(fit_result only)
```

Output fields:

- `fit_result`
- `boundary_result=None`
- `signal_output=None`
- `metadata.stages_completed=["extract", "fit"]`

### 4.2 Fit-To-Boundary Flow

Entry point:

```python
fit_trendlines_to_boundary(df, asset, timeframe, ...)
```

Flow:

```text
OHLCV DataFrame
  -> extract -> fit
  -> optional resolve_asset_config() if root TrendlinesConfig provided
  -> build_boundary_result_from_trendline_result()
  -> TrendlineOutput(fit_result + boundary_result)
```

Key boundary products:

- `BoundaryResult.active_support_rays`
- `BoundaryResult.active_resistance_rays`
- `BoundaryResult.convex_hull_floor`
- `BoundaryResult.convex_hull_ceiling`
- `BoundaryResult.interaction`
- `BoundaryResult.quality_metrics`
- `BoundaryResult.metadata.context`

### 4.3 Full Fit-And-Signal Flow

Entry point:

```python
fit_and_signal(df, asset, timeframe, history=None, context=None, ...)
```

Flow:

```text
OHLCV DataFrame
  -> execute_trendline_pipeline()
  -> resolve_asset_config(root_config, asset, timeframe, df, fit_result)
  -> build_boundary_result_from_trendline_result(... resolved boundary params ...)
  -> if boundary is valid:
       TrendlineSignalOrchestrator(resolved_config).run(boundary, history, context)
     else:
       neutral signal output
  -> TrendlineOutput(fit_result + boundary_result + signal_output)
```

Signal output:

- `signals`
- `composite_direction`
- `composite_confidence`
- `signal_count`
- `by_source`

### 4.4 Oscillator-Space Flow

Entry point:

```python
fit_oscillator_to_boundary(df, asset, timeframe, oscillator_type, ...)
```

Flow:

```text
synthetic oscillator OHLCV
  -> resolve_oscillator_config()
  -> execute_trendline_pipeline()
  -> build_boundary_result_from_trendline_result()
  -> TrendlineOutput(fit_result + boundary_result)
```

Important: oscillator flow bypasses `resolve_asset_config()` because price-scale derived params are not safe for bounded oscillators.

### 4.5 Optimization Flow

Entry point:

```python
optimize_trendlines(df, asset, timeframe, config)
```

Flow:

```text
TrendlinesOptimizer.optimize()
  -> Optuna study
  -> sample trial params
  -> walk-forward splits
  -> per fold:
       pipeline_factory(params)(train_df)
       -> fit_result + n_pivots
       -> evaluate on test_df
       -> compute longevity
       -> compute touch accuracy
       -> compute penetration gate
       -> compute pivot density constraint
  -> aggregate fold scores
  -> add fold-stability bonus
  -> return TrendlinesOptimizationResult
```

Default optimizer fitter: `ensemble`.

Objective shape:

```text
(w_longevity * longevity + w_touch_accuracy * touch_accuracy)
  * penetration_gate_multiplier
  * pivot_density_constraint_multiplier
  + fold_stability_bonus
```

### 4.6 RegimeV2 Feature Flow

RegimeV2 adapter:

```text
src/libs/models/regime_v2/adapters/trendline_feature_producer.py
```

Flow:

```text
price_history sequence
  -> DataFrame
  -> _prepare_ohlcv_index()
  -> fit_trendlines_to_boundary() by default
     or fit_and_signal() if include_native_signals=True
  -> BoundaryResult
  -> compact flat feature dict
```

Default RegimeV2 trendline config:

```python
extractor = "fractal"
fitter = "ensemble"
min_bars = 30
atr_window = 14
include_native_signals = False
history_limit = 5
record_snapshot = False
```

RegimeV2 consumes features, not raw trendline classes. This is the correct isolation boundary.

---

## 5. Core Contracts

### `PivotSet`

Defined in `contracts/contracts.py`.

Fields:

- `high_indices`
- `high_values`
- `low_indices`
- `low_values`

Helpers:

- `n_highs`
- `n_lows`
- `total_pivots`
- `is_valid(min_pivots=2)`

### `Trendline`

Defined in `contracts/contracts.py`.

Fields:

- `start_index`, `end_index`
- `start_value`, `end_value`
- `slope`, `intercept`
- `touch_count`
- `is_support`
- `method`
- `score`
- `metadata`

Helpers:

- `value_at(index)`
- `project(steps_ahead)`
- `to_dict()`

### `TrendlineFitResult`

Defined in `contracts/contracts.py`.

Fields:

- `support_lines`
- `resistance_lines`
- `is_valid`
- `metadata`

Structure helpers:

- `has_support`
- `has_resistance`
- `has_both_sides`
- `has_closed_channel`
- `is_one_sided_structure`
- `structure_state`
- `best_support`
- `best_resistance`

Important nuance: several fitters set `is_valid=True` if either side exists. Downstream logic must use structure helpers when it specifically needs two-sided or closed-channel structure.

### `Ray`, `BoundaryResult`, `QualityMetrics`

Defined in `boundary/contracts.py`.

`Ray` is consumer-facing projected trendline geometry. `BoundaryResult` is the package’s structural market-context output.

---

## 6. File-by-File Context Map

### Root/Public

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `src/libs/trendlines/__init__.py` | Public export surface | `fit_and_signal`, `fit_trendlines`, `build_extractor`, `build_fitter`, contracts | Prefer this surface over internals. Imports via `app.trendlines.*`. |
| `src/libs/trendlines/api.py` | Main facade API | `TrendlineOutput`, `fit_trendlines`, `fit_trendlines_to_boundary`, `fit_oscillator_to_boundary`, `fit_and_signal`, `optimize_trendlines` | Highest-level stable API. Composes pipeline, config, boundary, signals, optimization. |
| `src/libs/trendlines/cli.py` | Thin CLI router | `build_parser`, `main` | Routes command families such as drift monitor and pipeline optimization. |
| `src/app/trendlines/__init__.py` | Compatibility package | same public exports | Repoints `app.trendlines` path to `src/libs/trendlines`. |

### Contracts

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `contracts/__init__.py` | Contract exports | `PivotSet`, `Trendline`, `TrendlineFitResult` | Small re-export layer. |
| `contracts/contracts.py` | Core DTOs | `PivotSet`, `Trendline`, `TrendlineFitResult` | No trendlines imports; lower-layer contract. |

### Config

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `config/__init__.py` | Config export surface | config dataclasses, loaders, resolve helpers | Public config seam. |
| `config/base_config.py` | Root typed configs | `TrendlinesConfig`, `TrendlinePipelineConfig`, `OptimizableDefaults`, asset/oscillator configs | `TrendlinesConfig` is the root. `TrendlinePipelineConfig` is compatibility/workflow shim. |
| `config/boundary_config.py` | Boundary runtime params | `BoundaryAdapterConfig` | Holds `interaction_tolerance_atr`, `atr_window`. |
| `config/evaluation_config.py` | Protocol config | `EvaluationConfig`, `FitnessConfig`, `WalkForwardDefaults`, `LookbackGridConfig`, `DriftMonitorConfig` | Frozen research/evaluation defaults. |
| `config/search_grid_config.py` | Component grids | `GridSearchConfig`, extractor/fitter grid dataclasses | Component decorators reference these values. |
| `config/signal_config.py` | Legacy/back-compat signal config structs | `SignalConfig`, per-signal configs | New runtime path uses `ResolvedSignalConfig`. |
| `config/defaults.py` | Python fallback config | `get_default_config_dict()` | Used when YAML missing/unavailable. |
| `config/loader.py` | YAML + fallback parser | `load_trendlines_config()` and parse helpers | Merges YAML into typed config dataclasses. |
| `config/asset_profile.py` | Runtime market profile | `AssetProfile` | Computes timeframe minutes, ATR, price scale, bars, line stats. |
| `config/oscillator_profile.py` | Oscillator profile | `OscillatorProfile` | Keeps oscillator-space derivation separate from price-space derivation. |
| `config/derive.py` | Derived param formulas | `compute_all_derived`, `compute_oscillator_derived` | Produces derived knobs from profile rather than YAML literals. |
| `config/resolve.py` | Runtime config resolver | `ResolvedConfig`, `ResolvedSignalConfig`, `resolve_asset_config`, `resolve_oscillator_config` | Single seam for defaults -> overrides -> profile -> derived runtime config. |
| `config/state_transitions.py` | Temporal transition table | `build_state_transition_table()` | Builds state-to-state directional/confidence semantics. |
| `config/trendlines.yaml` | Runtime YAML source | n/a | Loaded by `load_trendlines_config()`. |

### Registry

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `registry/__init__.py` | Registry exports | builder/listing functions | Public seam for constructing plugins. |
| `registry/registry.py` | Build/list components | `build_extractor`, `build_fitter`, `list_extractors`, `list_fitters`, grid helpers | Handles deprecated aliases; triggers decorator registration by importing pivots/fitting packages. |

### Pivots

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `pivots/__init__.py` | Pivot exports + registration trigger | `FractalPivotExtractor`, `RDPZigZagPivotExtractor` | Importing this triggers decorator registration. |
| `pivots/base.py` | Pivot plugin protocol | `PivotExtractor`, `register_extractor` | Maintains `EXTRACTOR_REGISTRY`. |
| `pivots/fractal.py` | Fractal swing extractor | `FractalPivotExtractor` | Exact left/right high-low window pivots. Deduplicates equal adjacent pivots. |
| `pivots/rdp_zigzag.py` | RDP/ZigZag extractor | `RDPZigZagPivotExtractor` | Simplifies close path, classifies turning points, uses ATR-scaled epsilon. |

### Fitting

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `fitting/__init__.py` | Fitter exports + registration trigger | all fitter classes | Importing this triggers fitter registration. |
| `fitting/base.py` | Fitter protocol | `TrendlineFitter`, `register_fitter` | Maintains `FITTER_REGISTRY`. |
| `fitting/pathfinding.py` | Dynamic-programming fitter | `PathfindingFitter` | Finds pivot path that avoids candle-body cuts. Modes: `endpoint`, `ols_on_path`. |
| `fitting/least_squares.py` | OLS fitter | `LeastSquaresFitter` | Fits pivots by polyfit; scores by r-squared; ATR residual inliers. |
| `fitting/ransac.py` | Robust fitter | `RansacFitter` | Pair-sampled RANSAC with ATR inliers, body-cut rejection, coverage and cut constraints. |
| `fitting/ensemble.py` | Meta-fitter | `EnsembleFitter` | Runs pathfinding + OLS + RANSAC on same pivots, deduplicates near-identical lines. Preferred for optimizer/RegimeV2. |

### Pipeline

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `pipeline/__init__.py` | Pipeline exports | pipeline functions | Thin public surface. |
| `pipeline/orchestrator.py` | Extract -> fit orchestrator | `run_trendline_pipeline`, `run_trendline_pipeline_from_config`, `execute_trendline_pipeline` | Does not do boundary or signals. Keeps pipeline narrow. |

### Boundary

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `boundary/__init__.py` | Boundary exports | `BoundaryResult`, `Ray`, adapters, history, policy | Stable consumer-facing geometry surface. |
| `boundary/contracts.py` | Ray/boundary DTOs | `Ray`, `QualityMetrics`, `BoundaryResult`, `boundary_interaction_direction` | Rich market-position helpers live here. |
| `boundary/adapters.py` | Trendline -> boundary conversion | `trendline_to_boundary_ray`, `build_boundary_result_from_trendline_result` | Computes hulls, interactions, quality, boundary context. |
| `boundary/history.py` | Rolling boundary history | `TrendlineSnapshot`, `TrendlineSnapshotHistory` | Used by temporal/fakeout signals and RegimeV2 feature history. |
| `boundary/policy.py` | Policy/config DTOs | touch decluster, confluence, ray tracker dataclasses | Supports confluence/quality policies without pulling upper layers. |
| `boundary/touches.py` | Touch declustering helper | `decluster_touch_indices` | Converts raw touch events into gap-filtered effective touches. |

### Signals

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `signals/__init__.py` | Signal exports | signal classes/orchestrator | Thin re-export layer. |
| `signals/base.py` | Signal contracts | `AlphaSignal`, `BaseAlphaExtractor` | Direction/confidence are clamped in `AlphaSignal.__post_init__`. |
| `signals/constants.py` | Interaction constants | direction mapping helpers/constants | Signal layer interaction semantics. |
| `signals/quality.py` | Quality scoring helpers | `clamp_unit`, `blended_quality_score`, confluence/price/oscillator quality helpers | Shared confidence shaping logic. |
| `signals/structural.py` | Structural signals | `StructuralAlphaExtractor` | Interaction, hull squeeze, S/R asymmetry. |
| `signals/temporal.py` | History/time signals | `TemporalAlphaExtractor` | Hull convergence, transitions, persistence bias, slope acceleration. |
| `signals/patterns.py` | Pattern signals | `PatternAlphaExtractor` | Parallel/flat/channel-like patterns. |
| `signals/fakeout.py` | Fakeout signals | `FakeoutAlphaExtractor` | False breakouts/breakdowns, wick rejection, low-volume breakout, confirmed breakouts. |
| `signals/orchestrator.py` | Signal aggregator | `TrendlineSignalOrchestrator` | Builds extractors from `ResolvedSignalConfig`; computes weighted composite. |
| `signals/utils.py` | Signal utility math | `volume_is_trustworthy`, `z_score`, `series_acceleration`, ray matching/persistence helpers | Also consumed by RegimeV2 trendline adapter. |

### Data

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `data/__init__.py` | Data exports | request/manifest/split/artifact helpers | Public data layer surface. |
| `data/contracts.py` | Dataset/replay contracts | `TrendlineDataRequest`, `TrendlineDatasetManifest`, `TrendlineArtifactRef` | Deterministic hashes for reproducibility. |
| `data/fetchers.py` | Loader abstraction | `TrendlineDatasetLoader`, `load_dataset`, `build_dataset_manifest` | Source-agnostic; loader is injected. |
| `data/artifacts.py` | JSON artifact I/O | manifest read/write helpers | Persists dataset and split manifests. |
| `data/temporal.py` | Walk-forward split model | `WalkForwardValidator`, `TemporalSplitSpec`, `TemporalSplitManifest`, auto split resolver | Core deterministic temporal validation logic. |

### Optimization

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `optimization/__init__.py` | Optimization exports | optimizer/config/result classes | Public optimization API. |
| `optimization/models.py` | Optimization DTOs | `TrendlinesOptimizationConfig`, `TrendlinesOptimizationResult`, `TrendlinesBenchmarkResults`, `TrendlinesTrialResult` | Stores search ranges, benchmarks, results. |
| `optimization/optimizer.py` | Optuna optimizer | `TrendlinesOptimizer`, `_default_pipeline_factory` | TPE/CMA/random sampler support, walk-forward objective, tier scoring. |
| `optimization/walk_forward.py` | Optimization WF wrapper | `WalkForwardValidator`, `WalkForwardSplit` | Delegates to data temporal split concepts. |
| `optimization/oscillator.py` | Oscillator optimizer | `OscillatorOptimizationConfig`, `optimize_oscillator_trendlines`, `apply_oscillator_result` | Oscillator-specific search ranges/factory/apply path. |
| `optimization/benchmarks/_tolerance.py` | ATR/slope tolerance helper | `compute_tolerance` | Shared by benchmark metrics. |
| `optimization/benchmarks/longevity.py` | Tier 1 | `compute` | Measures line survival into forward/test data. |
| `optimization/benchmarks/touch_accuracy.py` | Tier 2 | `compute` | Measures touch-reaction hit rate. |
| `optimization/benchmarks/penetration_gate.py` | Tier 3 gate | `compute`, `gate_penalty` | Penalizes excessive line penetration. |
| `optimization/benchmarks/pivot_density.py` | Tier 4 constraint | `compute`, `tent_score`, `constraint_penalty` | Penalizes too sparse/dense pivots. |
| `optimization/benchmarks/fold_stability.py` | Tier 5 | `compute` | Cross-fold coefficient-of-variation stability bonus. |

### Workflows

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `workflows/__init__.py` | Workflow exports | common workflow DTOs | Thin surface. |
| `workflows/common/contracts.py` | Workflow study contracts | `WorkflowStudyStatus`, `WorkflowPromotionDecision`, `WorkflowPromotionSpec`, `WorkflowExperimentSpec`, `PipelineOptimizationSpec` | Durable experiment/promotion metadata. |
| `workflows/common/promotion.py` | Promotion gate | `decide_pipeline_promotion` | Decides whether optimization result is promotable. |
| `workflows/pipeline/temporal_spec.py` | Pipeline temporal plan | `resolve_pipeline_temporal_plan`, `build_pipeline_optimization_spec`, `resolve_trendlines_workflow_config` | Connects temporal manifests and pipeline config. |
| `workflows/pipeline/evaluation.py` | Pipeline search/eval | `run_pipeline_with_params`, `evaluate_trendlines_on_forward`, `walk_forward_evaluate`, `search_pipeline_parameters` | Non-Optuna/grid-style workflow evaluation path. |
| `workflows/pipeline/support.py` | Workflow request/artifact helpers | `build_pipeline_data_request`, artifact/split ref builders, merge helpers | Builds deterministic request/artifact references. |
| `workflows/pipeline/config_apply.py` | YAML apply path | `build_yaml_snippet`, `apply_pipeline_optimization_to_config` | Applies promoted optimized params into config snippets/files. |
| `workflows/pipeline/data_fetch.py` | Historical data fetch workflow | `download_historical_data`, `fetch_pipeline_workflow_data` | Connector-injected fetch path; tries default connector lazily. |
| `workflows/pipeline/reporting.py` | CLI reporting | `print_results`, `print_pipeline_yaml_snippet` | User-facing optimization print helpers. |
| `workflows/pipeline/workflow.py` | CLI workflow entry | `optimize_timeframe`, `_run_pipeline_cli`, `main` | Pipeline optimization CLI implementation. |
| `workflows/monitoring/drift_monitor.py` | Drift monitoring | `run_monitor`, `build_monitor_snapshot`, `compare`, baseline helpers | Fetches current data, runs boundary pipeline, compares against baseline. |
| `workflows/benchmarking/__init__.py` | Placeholder/empty namespace | none | No substantive runtime logic currently. |

### Scripts

| File | Role | Key symbols | Notes |
|---|---|---|---|
| `scripts/run_optimization.py` | Standalone optimization script | `run_single`, `run_staged`, `run_oscillator`, `StatusFileWriter`, Binance/cache helpers | Large operational CLI; can fetch Binance data and apply YAML updates. |
| `scripts/monitor_optimization.py` | Status monitor | `OptimizationMonitor` | Reads status JSON, displays progress/ETA/PID health. |
| `scripts/__init__.py` | Empty marker | none | Package marker. |

### Docs

| File | Role |
|---|---|
| `docs/README.md` | Module overview and quick reference. |
| `docs/architecture.md` | Layer model, dependency rules, pipeline diagrams, optimization architecture. |
| `docs/agent-map.md` | Practical coding/debugging map for future agents. |
| `docs/pipeline.md` | Facade and low-level pipeline usage. |
| `docs/pivots.md` | Pivot extractor algorithms. |
| `docs/fitting.md` | Fitter algorithms and comparisons. |
| `docs/boundary.md` | Boundary adapter/contracts/interaction semantics. |
| `docs/signals.md` | Native signal extractors and aggregation semantics. |
| `docs/config.md` | Config hierarchy and resolution. |
| `docs/data.md` | Data contracts, split manifests, artifact persistence. |
| `docs/workflows.md` | Optimization/promotion/drift workflows. |

---

## 7. RegimeV2 Integration File Map

Primary adapter:

```text
src/libs/models/regime_v2/adapters/trendline_feature_producer.py
```

Key symbols:

- `TrendlineFeatureConfig`
- `TrendlineFeatureProducer`
- `compute_trendline_context_features`

Important behavior:

- Fail-soft: missing/insufficient data returns neutral features instead of throwing.
- Uses `fit_trendlines_to_boundary()` by default.
- Uses `fit_and_signal()` only if `include_native_signals=True`.
- Optionally records `TrendlineSnapshotHistory`.
- Produces flat feature names prefixed by `trendline_`.

Feature families:

- validity/error
- interaction class and direction
- structure state
- channel position flags
- support/resistance levels
- ATR-normalized distances
- hull width and compression
- quality scores
- touch counts
- slope normalized by ATR
- ray counts
- history/persistence context
- optional native signal composite

---

## 8. Test Surface

Trendlines tests under `src/libs/trendlines/tests`:

```text
test_boundary_adapters.py
test_boundary_history.py
test_boundary_public_api.py
test_boundary_quality_metrics.py
test_config_resolve.py
test_config.py
test_data_contracts.py
test_data_fetchers.py
test_derive.py
test_drift_monitor_workflow.py
test_end_to_end_pipeline.py
test_ensemble_fitter.py
test_extractors.py
test_facade_equivalence.py
test_import_boundaries.py
test_integration_pipeline.py
test_least_squares_fitter.py
test_optimization_benchmarks.py
test_optimization_integration.py
test_optimization_models.py
test_optimizer.py
test_pathfinding_fitter.py
test_pipeline_executor.py
test_public_api.py
test_ransac_fitter.py
test_registry.py
test_signal_orchestrator_config.py
test_signals.py
test_state_transitions_derived.py
test_structure_semantics.py
test_temporal.py
test_trendlines_cli.py
test_trendlines_pipeline_workflow.py
test_workflow_contracts.py
```

Additional consumer test:

```text
tests/test_regime_v2_trendline_feature_producer.py
```

Last targeted validation run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/libs/trendlines/tests tests/test_regime_v2_trendline_feature_producer.py -q
```

Observed result:

```text
271 passed, 1 failed
```

The failure is `test_shared_boundary_symbols_have_single_canonical_definition`, caused by duplicate boundary symbols under `src/libs/models/trendlines_old`.

---

## 9. Current Strengths

1. Clear layering and import-boundary intent.
2. Good public facade design.
3. Extractor/fitter plugin registry supports experimentation.
4. Ensemble fitter gives more robust geometry than a single method.
5. Boundary layer creates meaningful market-structure state, not just raw lines.
6. Signal layer is native/self-contained and does not require alpha/confluence package imports.
7. Config resolution cleanly separates optimizable defaults, per-asset overrides, and derived runtime params.
8. Optimizer evaluates geometry quality through multiple dimensions instead of pure fit error.
9. RegimeV2 adapter correctly consumes compact features rather than internal trendline objects.

---

## 10. Current Risks / Context Warnings

1. `src/libs/models/trendlines_old` is still present and conflicts with canonical boundary ownership tests.
2. Codebase-memory traces may surface `trendlines_old` symbols, which can mislead impact analysis until the old copy is removed or excluded.
3. Facade defaults and consumer defaults differ:
   - `fit_and_signal()` default fitter: `pathfinding`
   - RegimeV2 default fitter: `ensemble`
   - optimizer default fitter: `ensemble`
4. `TrendlineFitResult.is_valid` often means at least one side exists, not necessarily closed channel. Use `has_both_sides` or `has_closed_channel` when needed.
5. Boundary interaction is primarily latest-bar/hull/tolerance based. Multi-bar confirmation must come from history/signals/consumer logic.
6. Native signals are disabled in RegimeV2 by default through `include_native_signals=False`; RegimeV2 currently gets mostly geometry-context features.
7. Some docs use old conceptual path names like `app/trendlines`; active physical path is `src/libs/trendlines` with compatibility shim.
8. Optimization and workflow layers have overlapping concepts (`optimization/*` and `workflows/pipeline/*`); future changes should avoid duplicating semantics further.

---

## 11. Suggested Next Actions

1. Decide policy for `src/libs/models/trendlines_old`:
   - delete,
   - move out of scanned Python source,
   - or exclude from canonical-boundary tests.
2. Re-run targeted trendlines tests to get a clean baseline.
3. Standardize or explicitly document fitter defaults:
   - facade default `pathfinding` vs RegimeV2/optimizer default `ensemble`.
4. Build a dedicated RegimeV2 trendline integration review:
   - Which features are actually used?
   - Which are ignored?
   - Which features are redundant/correlated?
   - Should native signals be enabled for shadow runs only?
5. Add a small architecture handoff for any future changes before editing existing trendline symbols.

---

## 12. Quick Mental Model for Future Agents

When asked to change trendlines:

1. Identify layer:
   - pivots, fitting, boundary, signals, config, data, optimizer, workflow, or consumer adapter.
2. Use public seam if possible.
3. Before changing symbols, run codebase-memory impact lookup for callers/callees.
4. Check whether the change affects RegimeV2 adapter features.
5. Check whether one-sided vs closed-channel semantics matter.
6. Update tests in the same layer.
7. Run targeted tests, not the full repo first.

Minimal targeted test pattern:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/libs/trendlines/tests -q
PYTHONPATH=src .venv/bin/python -m pytest tests/test_regime_v2_trendline_feature_producer.py -q
```

If touching RegimeV2 consumer behavior:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_regime_v2_trendline_feature_producer.py tests/test_regime_v2.py -q
```
