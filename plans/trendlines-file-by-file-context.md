# Trendlines File-by-File Context

Date: 2026-07-11
Repo: `/Users/aloobhujia/flipperAgent`
Active package: `src/libs/trendlines`
Compatibility import shim: `src/app/trendlines`
Legacy duplicate package: `src/libs/models/trendlines_old`

This document is a durable context artifact for future specialized quant work on the trendlines model. It is intentionally file-by-file and pipeline-flow oriented so a model can reload the architecture without rediscovering the package from scratch.

## Specialist Workstream Notes

Because no live `squad` worker is attached, this context was built as independent internal passes:

- `quant-research` pass: read docs, model purpose, optimization objective, market-geometry semantics.
- `quant-architect` pass: mapped public seams, import boundaries, config flow, pipeline execution flow, RegimeV2 integration.
- `quant-review` pass: checked tests, known active-vs-legacy conflicts, downstream risks.
- `codebase-memory` pass: confirmed indexed project `Users-aloobhujia-flipperAgent`; traced `fit_and_signal` call graph.

No source-code edits were made. This file is a context artifact only.

---

## Canonical Ownership and Path Reality

The active source is:

```text
src/libs/trendlines
```

Most source files import themselves through:

```python
app.trendlines.*
```

That works because `src/app/trendlines/__init__.py` is a compatibility package that points its `__path__` to `src/libs/trendlines`.

There is also an old duplicate tree:

```text
src/libs/models/trendlines_old
```

This old tree currently pollutes search results and causes the import-boundary test `test_shared_boundary_symbols_have_single_canonical_definition` to fail because it defines old copies of boundary symbols such as `Ray`, `BoundaryResult`, and `build_boundary_result_from_trendline_result`.

---

## Top-Level Architecture

Trendlines is a market-geometry package that turns OHLCV candles into:

1. pivot points,
2. fitted support/resistance trendlines,
3. boundary/ray structure,
4. optional native trendline alpha signals,
5. optimization/workflow artifacts.

High-level flow:

```text
OHLCV DataFrame
  -> PivotSet
  -> TrendlineFitResult
  -> BoundaryResult
  -> native AlphaSignal list + composite
  -> RegimeV2 flat features / downstream consumers
```

Layer direction:

```text
contracts/config
  -> pivots/fitting
  -> registry
  -> pipeline
  -> boundary/signals/data/workflows
  -> api/public facade
```

Important design rule: `pipeline/` only owns extract -> fit. Boundary adaptation and signal extraction are called from the facade, not from the low-level pipeline orchestrator.

---

## Core Pipeline Flows

### Flow 1: Fit Only

Entrypoint:

```python
fit_trendlines(df, extractor="fractal", fitter="pathfinding", ...)
```

Flow:

```text
api.fit_trendlines
  -> pipeline.execute_trendline_pipeline
  -> pipeline.run_trendline_pipeline
  -> registry.build_extractor
  -> extractor.extract(df)
  -> registry.build_fitter
  -> fitter.fit(df, pivots)
  -> TrendlineOutput(fit_result only)
```

Output has:

- `fit_result` populated
- `boundary_result = None`
- `signal_output = None`

### Flow 2: Fit to Boundary

Entrypoint:

```python
fit_trendlines_to_boundary(df, asset, timeframe, ...)
```

Flow:

```text
api.fit_trendlines_to_boundary
  -> execute_trendline_pipeline
  -> optionally resolve_asset_config if TrendlinesConfig provided
  -> boundary.adapters.build_boundary_result_from_trendline_result
  -> TrendlineOutput(fit_result + boundary_result)
```

Output has:

- raw fit lines
- consumer-facing support/resistance rays
- hull floor/ceiling
- latest interaction label
- boundary context and quality metrics

### Flow 3: Full Fit + Boundary + Native Signals

Entrypoint:

```python
fit_and_signal(df, asset, timeframe, history=None, context=None, ...)
```

Flow:

```text
api.fit_and_signal
  -> execute_trendline_pipeline
  -> load_trendlines_config if no config passed
  -> resolve_asset_config(root, asset, timeframe, df, fit_result)
  -> build_boundary_result_from_trendline_result
  -> TrendlineSignalOrchestrator(resolved_config).run(boundary, history, context)
  -> TrendlineOutput(fit + boundary + signal_output)
```

The resolved config is built after fitting because `AssetProfile` can use `fit_result` structure to derive adaptive parameters.

### Flow 4: Oscillator-Space Trendlines

Entrypoint:

```python
fit_oscillator_to_boundary(df, asset, timeframe, oscillator_type, ...)
```

Flow:

```text
api.fit_oscillator_to_boundary
  -> resolve_oscillator_config
  -> build TrendlinePipelineConfig from oscillator defaults/overrides
  -> execute_trendline_pipeline
  -> build_boundary_result_from_trendline_result
  -> TrendlineOutput(fit + boundary, no signal extraction)
```

Reason for separate path: price-scale derived params such as ATR/price ratios do not transfer safely to bounded oscillator values like RSI.

### Flow 5: Optimization

Entrypoint:

```python
optimize_trendlines(df, asset, timeframe, config)
```

Flow:

```text
api.optimize_trendlines
  -> TrendlinesOptimizer.optimize
  -> Optuna study
  -> sample continuous params + categorical component params
  -> walk-forward folds
  -> run trial pipeline on train fold
  -> evaluate lines on forward test fold
  -> compute 5-tier objective
  -> return TrendlinesOptimizationResult
```

Objective tiers:

1. longevity,
2. touch accuracy,
3. penetration gate,
4. pivot density constraint,
5. fold stability.

### Flow 6: RegimeV2 Adapter

Consumer:

```text
src/libs/models/regime_v2/adapters/trendline_feature_producer.py
```

Flow:

```text
RegimeV2 price_history
  -> TrendlineFeatureProducer.analyze
  -> compute_trendline_context_features
  -> prepare OHLCV index
  -> fit_trendlines_to_boundary OR fit_and_signal
  -> flatten BoundaryResult into trendline_* features
```

Default RegimeV2 trendline config:

```python
extractor = "fractal"
fitter = "ensemble"
include_native_signals = False
record_snapshot = False
```

So RegimeV2 currently consumes geometry context by default, not native signal composite, unless `include_native_signals=True`.

---

## Public and Compatibility Files

### `src/libs/trendlines/__init__.py`

Canonical public export surface for the active package. Exports contracts, registry helpers, low-level pipeline helpers, and facade APIs. Use this for consumer imports where possible.

Stable exports include:

- `PivotSet`
- `Trendline`
- `TrendlineFitResult`
- `TrendlinePipelineConfig`
- `build_extractor`
- `build_fitter`
- `list_extractors`
- `list_fitters`
- `execute_trendline_pipeline`
- `run_trendline_pipeline`
- `run_trendline_pipeline_from_config`
- `TrendlineOutput`
- `fit_and_signal`
- `fit_oscillator_to_boundary`
- `fit_trendlines`
- `fit_trendlines_to_boundary`
- `optimize_trendlines`

### `src/libs/trendlines/api.py`

Primary facade. Consumers should prefer this over hand-wiring stages.

Key class:

- `TrendlineOutput`: wrapper around `TrendlineFitResult`, optional `BoundaryResult`, optional signal output, config, and metadata.

Key functions:

- `fit_trendlines`: extract + fit only.
- `fit_trendlines_to_boundary`: extract + fit + boundary adaptation.
- `fit_oscillator_to_boundary`: oscillator-space trendline boundary flow.
- `fit_and_signal`: full flow including native signal extraction.
- `optimize_trendlines`: Optuna-backed optimization facade.

Important semantics:

- `TrendlineOutput.is_valid` delegates to `fit_result.is_valid`.
- `TrendlineOutput.composite_direction/confidence` return `0.0` when no signal output exists.
- `fit_and_signal` loads config if not passed, resolves per-asset/per-timeframe config, then uses resolved boundary and signal params.

### `src/app/trendlines/__init__.py`

Compatibility shim. It sets `__path__` so `app.trendlines.*` resolves to `src/libs/trendlines`. This explains why active package files import `app.trendlines.*` even though the real source is under `src/libs/trendlines`.

Do not mistake this for a second implementation. It is a routing shim.

### `src/libs/trendlines/cli.py`

Thin CLI router for trendline workflows.

Commands:

- `drift-monitor`
- `pipeline-opt`

It imports command modules lazily and delegates execution. Keep this file thin; workflow-specific parsing/execution belongs in the workflow modules.

---

## Contracts Layer

### `src/libs/trendlines/contracts/__init__.py`

Re-exports canonical contract classes from `contracts/contracts.py`.

### `src/libs/trendlines/contracts/contracts.py`

Narrow core contracts used by pivot extraction and fitting.

Classes:

- `PivotSet`
- `Trendline`
- `TrendlineFitResult`

`PivotSet` contains high/low pivot indices and values. It exposes pivot counts and `is_valid(min_pivots=2)`.

`Trendline` represents one fitted support/resistance line in local bar-index space. It exposes:

- `value_at(index)`
- `project(steps_ahead)`
- `to_dict()`

`TrendlineFitResult` wraps support and resistance lines. It exposes structure semantics:

- `has_support`
- `has_resistance`
- `has_both_sides`
- `has_closed_channel`
- `is_one_sided_structure`
- `structure_state`
- `best_support`
- `best_resistance`

Important: `is_valid` can be true for one-sided structure. Downstream logic should check `has_both_sides` or `has_closed_channel` when a full channel is required.

---

## Config Layer

### `src/libs/trendlines/config/__init__.py`

Config package export surface. Re-exports base config, loader, resolution, derivation, profiles, search grids, signal config, and state transitions.

### `src/libs/trendlines/config/base_config.py`

Root config model.

Classes:

- `AssetTimeframeConfig`: optional per-asset/per-timeframe overrides for optimized params.
- `AssetConfig`: metadata + timeframe overrides.
- `OptimizableDefaults`: global defaults for the five main optimized params.
- `OscillatorDefaults`: defaults for oscillator-space trendlines.
- `OscillatorOverride`: per-oscillator overrides.
- `TrendlinesConfig`: root config.
- `TrendlinePipelineConfig`: backward-compatible runtime pipeline shim.

The five main optimizable defaults are:

- `interaction_tolerance_atr`
- `asymmetry_threshold`
- `convergence_rate_threshold`
- `wick_rejection_ratio`
- `squeeze_threshold`

`TrendlinesConfig` has backward-compatible properties:

- `.boundary`
- `.evaluation`
- `.signals`

New code should prefer resolved config, not these legacy accessors.

### `src/libs/trendlines/config/boundary_config.py`

Small dataclass for boundary adapter params.

Class:

- `BoundaryAdapterConfig`

Fields:

- `interaction_tolerance_atr`
- `atr_window`

### `src/libs/trendlines/config/defaults.py`

Python fallback when `trendlines.yaml` is absent. Returns the default dict used by the loader.

### `src/libs/trendlines/config/trendlines.yaml`

Main YAML source for active trendlines configuration. Contains root defaults, protocol, grids, assets, and oscillator config. Treat this as runtime config, not source-code logic.

### `src/libs/trendlines/config/asset_profile.py`

Computes data-derived market profile for one `(asset, timeframe)` execution.

Class:

- `AssetProfile`

Helpers:

- `_tf_to_minutes`
- `_mean_true_range_simple`

Used by `resolve_asset_config` to derive adaptive params from market data such as timeframe, bar duration, ATR, price scale, and structural fit context.

### `src/libs/trendlines/config/oscillator_profile.py`

Oscillator-space equivalent of `AssetProfile`. Avoids price-scale assumptions such as ATR/price ratio.

Class:

- `OscillatorProfile`

Used by `resolve_oscillator_config`.

### `src/libs/trendlines/config/derive.py`

Pure derivation functions. No I/O and no mutable state.

Functions derive:

- hold bars,
- volume lookback,
- minimum history,
- ATR window,
- consecutive penetration bars,
- forward lookahead bars,
- parallel tolerance,
- flat tolerance,
- full-confidence touch counts,
- slope match tolerance,
- slope acceleration threshold.

Main functions:

- `compute_all_derived(profile)`
- `compute_oscillator_derived(...)`

This is where adaptive runtime parameters are computed from profile instead of hardcoding them in YAML.

### `src/libs/trendlines/config/evaluation_config.py`

Evaluation/protocol config.

Classes:

- `FitnessConfig`
- `WalkForwardDefaults`
- `LookbackGridConfig`
- `DriftMonitorConfig`
- `EvaluationConfig`

Used by workflow and optimization layers.

### `src/libs/trendlines/config/search_grid_config.py`

Typed search-grid config.

Classes:

- `FractalSearchGrid`
- `RDPSearchGrid`
- `PathfindingSearchGrid`
- `LeastSquaresSearchGrid`
- `RansacSearchGrid`
- `GridSearchConfig`

Extractor/fitter decorators use these grids to expose searchable component choices.

### `src/libs/trendlines/config/signal_config.py`

Backward-compatible signal config stubs and typed groupings.

Important note in source: after hyperparameter segregation, many signal fields are no longer here. They are now either:

- hardcoded constants in signal extractor modules,
- derived via `derive.py` and `resolve.py`,
- moved to `OptimizableDefaults`.

Classes include:

- `QualityConfig`
- `StateTransitionEntry`
- `StateTransitionsConfig`
- `StructuralSignalConfig`
- `TemporalSignalConfig`
- `PatternSignalConfig`
- `FakeoutSignalConfig`
- `SignalConfig`

### `src/libs/trendlines/config/state_transitions.py`

Builds deterministic state-transition table from market logic.

Functions:

- `_classify_transition`
- `_compute_direction`
- `build_state_transition_table`

This replaces a large scalar transition table with a derived mapping.

### `src/libs/trendlines/config/loader.py`

Loads YAML config and falls back to `defaults.py`.

Key functions:

- `_merge_dicts`
- `_parse_asset_tf_config`
- `_parse_assets`
- `_parse_oscillator_defaults`
- `_parse_oscillator_overrides`
- `load_trendlines_config`

Risk area: schema drift between YAML and dataclasses should be caught by config tests.

### `src/libs/trendlines/config/resolve.py`

Canonical config-resolution seam.

Classes:

- `ResolvedSignalConfig`
- `ResolvedConfig`
- `ResolvedOscillatorConfig`

Functions:

- `resolve_asset_config`
- `resolve_oscillator_config`

Price-space resolution order:

```text
TrendlinesConfig.defaults
  -> assets[asset].timeframes[timeframe]
  -> AssetProfile.from_dataframe
  -> compute_all_derived
  -> build_state_transition_table
  -> ResolvedConfig
```

Oscillator-space resolution order:

```text
oscillator_defaults
  -> oscillator_overrides[oscillator_type]
  -> OscillatorProfile
  -> compute_oscillator_derived
  -> ResolvedOscillatorConfig
```

---

## Registry Layer

### `src/libs/trendlines/registry/__init__.py`

Re-exports registry helpers.

### `src/libs/trendlines/registry/registry.py`

Canonical registry seam for extractors and fitters.

Functions:

- `list_extractors`
- `build_extractor`
- `get_extractor_search_grid`
- `list_fitters`
- `build_fitter`
- `get_fitter_search_grid`

Deprecated extractor aliases:

- `fractals -> fractal`
- `rdp-zigzag -> rdp_zigzag`

Deprecated fitter aliases:

- `ols -> least_squares`
- `least-squares -> least_squares`

Registry imports `app.trendlines.pivots` and `app.trendlines.fitting` to trigger decorator-based registration.

---

## Pivot Extraction Layer

### `src/libs/trendlines/pivots/__init__.py`

Imports pivot base and concrete extractors so decorators register them.

Registered extractors:

- `fractal`
- `rdp_zigzag`

### `src/libs/trendlines/pivots/base.py`

Base protocol and registry decorator.

Class:

- `PivotExtractor`

Function:

- `register_extractor`

Extractor interface:

```python
extract(df: pd.DataFrame) -> PivotSet
```

### `src/libs/trendlines/pivots/fractal.py`

Fractal-style pivot extractor.

Class:

- `FractalPivotExtractor`

Parameters:

- `window_left`
- `window_right`

Core behavior:

- requires `high` and `low`,
- uses sliding windows,
- swing high is exact maximum over left/core/right,
- swing low is exact minimum,
- deduplicates equal consecutive pivots by choosing group midpoint.

Best use:

- deterministic pivot extraction,
- stable local extrema detection,
- simple default extractor.

Risk:

- strict equality against max/min can produce dense pivots in flat/noisy regions; dedup only handles equal consecutive values.

### `src/libs/trendlines/pivots/rdp_zigzag.py`

RDP-based zigzag extractor.

Class:

- `RDPZigZagPivotExtractor`

Parameters:

- `epsilon_atr`
- `min_segment_bars`
- `atr_window`

Core behavior:

- requires `high`, `low`, `close`,
- computes mean ATR,
- uses Ramer-Douglas-Peucker on close path,
- classifies retained points as highs/lows based on local close shape,
- final values use actual high/low arrays.

Best use:

- cleaner swing structure,
- volatility-normalized simplification,
- less sensitivity to one-bar local extrema.

Risk:

- uses close path for shape classification, so intrabar high/low extremes only enter after classification.

---

## Fitting Layer

### `src/libs/trendlines/fitting/__init__.py`

Imports base and all concrete fitters to trigger registration.

Registered fitters:

- `pathfinding`
- `least_squares`
- `ransac`
- `ensemble`

### `src/libs/trendlines/fitting/base.py`

Base protocol and registry decorator.

Class:

- `TrendlineFitter`

Function:

- `register_fitter`

Fitter interface:

```python
fit(df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult
```

### `src/libs/trendlines/fitting/pathfinding.py`

Dynamic-programming pivot-path fitter.

Class:

- `PathfindingFitter`

Parameters:

- `pivot_window`
- `pivot_extractor`
- `line_fit_mode`: `endpoint` or `ols_on_path`

Core behavior:

- uses high pivots for resistance and low pivots for support,
- finds best valid pivot path,
- a segment is valid only if it does not cut candle bodies,
- support line must stay at/below candle body bottoms,
- resistance line must stay at/above candle body tops,
- final line can use endpoint mode or OLS over selected path.

Scoring:

- coverage-based.

Best use:

- structurally conservative support/resistance,
- candle-body-respecting trendlines.

Risk:

- endpoint mode may ignore older path geometry in final slope; `ols_on_path` can be richer but may cut bodies unless separately validated after refit.

### `src/libs/trendlines/fitting/least_squares.py`

Deterministic OLS fitter.

Class:

- `LeastSquaresFitter`

Parameters:

- `pivot_window`
- `pivot_extractor`
- `residual_threshold_atr`
- `atr_window`

Core behavior:

- fits a line to all pivots on one side,
- uses ATR-scaled residual threshold for inlier counting,
- outputs one support and/or one resistance line.

Scoring:

- `r_squared`.

Best use:

- smooth global support/resistance approximation,
- oscillator-space fitting.

Risk:

- can fit through prices unless downstream quality/cut checks catch poor geometry.

### `src/libs/trendlines/fitting/ransac.py`

Pair-sampled robust fitter.

Class:

- `RansacFitter`

Parameters:

- `pivot_window`
- `residual_threshold_atr`
- `max_trials`
- `max_cut_fraction`
- `min_coverage`
- `atr_window`
- `seed`

Core behavior:

- samples pivot pairs,
- checks ATR inliers,
- rejects candidates with insufficient coverage,
- rejects candidates that cut too many candle bodies,
- refits on inliers using `np.polyfit`.

Scoring:

```text
inlier_ratio * coverage * (1 - cut_fraction)
```

Best use:

- robust support/resistance in noisy data,
- outlier-resistant geometry.

Risk:

- stochastic but default seed makes it deterministic; search/runtime cost grows with max trials.

### `src/libs/trendlines/fitting/ensemble.py`

Meta-fitter that pools all three sub-fitters.

Class:

- `EnsembleFitter`

Parameters:

- `pivot_window`
- `pivot_extractor`
- `slope_dedup_atol`
- `intercept_dedup_atr_frac`
- `pathfinding_line_fit_mode`

Core behavior:

- runs `PathfindingFitter`, `LeastSquaresFitter`, and `RansacFitter` on the same pivot set,
- collects support/resistance lines,
- deduplicates near-identical lines by slope/intercept similarity,
- returns up to 3 support + 3 resistance lines.

Best use:

- richer market-geometry context,
- optimization,
- RegimeV2 adapter default.

Risk:

- `is_valid=True` if at least one side exists; downstream full-channel logic must check structure state.

---

## Low-Level Pipeline Layer

### `src/libs/trendlines/pipeline/__init__.py`

Re-exports pipeline orchestrator helpers.

### `src/libs/trendlines/pipeline/orchestrator.py`

Owns extract -> fit only.

Functions:

- `_resolve_extractor`
- `_resolve_fitter`
- `run_trendline_pipeline`
- `run_trendline_pipeline_from_config`
- `execute_trendline_pipeline`

Main behavior:

```text
resolve extractor
  -> extract pivots
  -> resolve fitter
  -> fit trendlines
  -> attach pipeline metadata
```

Pipeline metadata includes:

- extractor name,
- fitter name,
- number of high pivots,
- number of low pivots.

No boundary or signal logic belongs here.

---

## Boundary Layer

### `src/libs/trendlines/boundary/__init__.py`

Boundary public surface. Exports adapters, contracts, history, policy, and touch helpers.

### `src/libs/trendlines/boundary/contracts.py`

Consumer-facing geometry contracts.

Classes:

- `Ray`
- `QualityMetrics`
- `BoundaryResult`

Function:

- `boundary_interaction_direction`

Interaction direction map:

```text
GEOMETRIC_BOUNCE_SUPPORT    -> +1
GEOMETRIC_BOUNCE_RESISTANCE -> -1
STRUCTURAL_BREAKOUT         -> +1
STRUCTURAL_BREAKDOWN        -> -1
other/NONE                  -> 0
```

`Ray` represents a trendline projected into timestamp space but still uses bar-index slope/intercept for value projection.

`QualityMetrics` summarizes ray count, average score, normalized quality, touches, r-squared, and hull width in ATR.

`BoundaryResult` exposes:

- active support/resistance rays,
- convex hull floor/ceiling,
- latest interaction,
- structure semantics,
- market position state,
- channel pressure flags,
- support/resistance quality properties.

### `src/libs/trendlines/boundary/adapters.py`

Converts narrow fit contracts into consumer-facing boundary contracts.

Key functions:

- `trendline_to_boundary_ray`
- `build_boundary_result_from_trendline_result`

Important helpers:

- `_detect_boundary_interaction`
- `_build_boundary_context`
- `_line_quality_summary`
- `_mean_true_range`

Boundary context includes:

- current price,
- latest ATR,
- mean ATR,
- interaction tolerance in ATR and price,
- support/resistance levels,
- ATR distances to support/resistance,
- hull width ATR,
- hull position,
- market position state,
- inside/above/below channel flags,
- near-support / near-resistance flags,
- mid-channel noise,
- channel compression,
- upper/lower channel pressure,
- normalized quality summaries.

Line quality blend:

```text
0.30 * coverage_score
+ 0.25 * touch_score
+ 0.20 * residual_quality_score
+ 0.15 * no_cut_score
+ 0.10 * recency_score
```

Risk: interaction is latest-bar based; multi-bar confirmation lives in history/signals/downstream logic.

### `src/libs/trendlines/boundary/history.py`

In-memory rolling snapshot history.

Classes:

- `TrendlineSnapshot`
- `TrendlineSnapshotHistory`

Purpose:

- supports temporal signal extraction,
- stores per asset/timeframe bounded history,
- can return snapshots before a timestamp,
- avoids persistent storage concerns.

Used by RegimeV2 adapter when history is supplied and snapshot recording is enabled.

### `src/libs/trendlines/boundary/policy.py`

Shared policy/config contracts for boundary/confluence concepts.

Classes:

- `TouchDeclusterConfig`
- `TouchDiagnostics`
- `ConfluenceGateConfig`
- `ConfluenceQualitySnapshot`
- `RayTrackerConfig`
- `TrackedRayState`

These are contracts/policies, not pipeline execution code.

### `src/libs/trendlines/boundary/touches.py`

Touch declustering helper.

Functions:

- `decluster_touch_indices`
- `_resolve_min_gap`

Purpose:

- collapses dense nearby touch indices into structurally distinct touches.

---

## Signal Layer

### `src/libs/trendlines/signals/__init__.py`

Exports native trendline signal contracts, extractors, and orchestrator.

### `src/libs/trendlines/signals/base.py`

Signal base contracts.

Classes:

- `AlphaSignal`
- `BaseAlphaExtractor`

`AlphaSignal` clamps:

- direction to `[-1, 1]`,
- confidence to `[0, 1]`.

Strength is `abs(direction) * confidence`.

### `src/libs/trendlines/signals/constants.py`

Constants for signal extraction. Keeps interaction labels and fixed semantics centralized for native signal modules.

### `src/libs/trendlines/signals/quality.py`

Shared confidence/quality helpers.

Functions:

- `clamp_unit`
- `touch_count_confidence_factor`
- `blended_quality_score`
- `confluence_confidence`
- `price_quality_for_direction`
- `oscillator_quality_for_direction`

Used by structural/pattern signals and downstream-style quality confidence calculations.

### `src/libs/trendlines/signals/structural.py`

Structural signal extractor.

Class:

- `StructuralAlphaExtractor`

Emits signals around:

- interaction direction,
- hull squeeze,
- support/resistance asymmetry.

Parameters flow from resolved config:

- `asymmetry_threshold`
- `squeeze_threshold`
- `full_confidence_touches`

### `src/libs/trendlines/signals/temporal.py`

Temporal/history-aware signal extractor.

Class:

- `TemporalAlphaExtractor`

Emits signals around:

- hull convergence,
- transition from previous to current state,
- ray persistence bias,
- slope acceleration.

Requires history for most useful behavior.

Parameters include:

- `min_history`
- `slope_match_tol`
- `convergence_rate_threshold`
- `slope_accel_threshold`
- `state_transitions`

### `src/libs/trendlines/signals/patterns.py`

Pattern signal extractor.

Class:

- `PatternAlphaExtractor`

Detects structural patterns from support/resistance slope and hull geometry, such as channel/triangle-like states.

Parameters:

- `parallel_tol`
- `flat_tol`
- `full_confidence_touches`

### `src/libs/trendlines/signals/fakeout.py`

Fakeout/retest signal extractor.

Class:

- `FakeoutAlphaExtractor`

Emits signals around:

- false breakout,
- false breakdown,
- wick rejection at support/resistance,
- low-volume breakout/breakdown,
- confirmed breakout/breakdown.

Uses context such as OHLCV, ATR, and volume trustworthiness.

Parameters:

- `hold_bars`
- `volume_lookback`
- `wick_rejection_ratio`

### `src/libs/trendlines/signals/utils.py`

Utility helpers for signals.

Functions:

- `volume_is_trustworthy`
- `z_score`
- `series_acceleration`
- `has_matching_ray`
- `count_persistent_rays`

Used especially by temporal and RegimeV2 adapter logic.

### `src/libs/trendlines/signals/orchestrator.py`

Runs native signal extractors and aggregates outputs.

Class:

- `TrendlineSignalOrchestrator`

Default extractors:

- `StructuralAlphaExtractor`
- `TemporalAlphaExtractor`
- `PatternAlphaExtractor`
- `FakeoutAlphaExtractor`

Key functions/methods:

- `_build_extractors_from_resolved`
- `run`
- `_compute_composite`
- `to_dict`

Composite formula:

```text
composite_direction = sum(direction * confidence * weight) / total_weight
composite_confidence = sum(confidence * weight) / total_weight
```

Risk: failed extractors are swallowed into warnings and produce empty source output. Good for live safety, but can hide degradation unless logs/metrics are monitored.

---

## Data and Replay Layer

### `src/libs/trendlines/data/__init__.py`

Exports dataset contracts, fetchers, artifact I/O, and temporal split helpers.

### `src/libs/trendlines/data/contracts.py`

Replay/data contracts.

Classes:

- `TrendlineArtifactRef`
- `TrendlineDataRequest`
- `TrendlineDatasetManifest`

Functions:

- `_stable_hash`
- `normalize_timeframes`
- `_normalize_names`

Purpose:

- deterministic dataset identity,
- artifact addressing,
- reproducible runs.

### `src/libs/trendlines/data/fetchers.py`

Injected dataset loading helpers.

Class:

- `TrendlineDatasetLoader` protocol

Functions:

- `_normalize_columns`
- `_normalize_frame_map`
- `build_dataset_manifest`
- `load_dataset`

Design: source-agnostic. Real connector behavior is injected, not embedded here.

### `src/libs/trendlines/data/artifacts.py`

Artifact persistence helpers.

Functions:

- `artifact_path`
- `_write_json_artifact`
- `_read_json_artifact`
- `_resolve_manifest_artifact`
- `write_dataset_manifest`
- `read_dataset_manifest`
- `write_temporal_split_manifest`
- `read_temporal_split_manifest`

Purpose:

- deterministic JSON persistence for manifests and temporal split specs.

### `src/libs/trendlines/data/temporal.py`

Temporal split and walk-forward contracts.

Classes:

- `WalkForwardSplit`
- `WalkForwardValidator`
- `TemporalSplitSpec`
- `TemporalSplitManifest`

Functions:

- `_stable_hash`
- `resolve_trendline_auto_split_spec`
- `build_temporal_split_manifest`

Purpose:

- deterministic walk-forward split generation,
- auto-split policy from timeframe/asset class,
- replayable temporal manifests.

---

## Optimization Layer

### `src/libs/trendlines/optimization/__init__.py`

Exports optimization models, optimizer, oscillator optimization, and walk-forward helpers.

### `src/libs/trendlines/optimization/models.py`

Optimization dataclasses.

Classes:

- `TrendlinesBenchmarkResults`
- `TrendlinesOptimizationWeights`
- `TrendlinesOptimizationConfig`
- `TrendlinesTrialResult`
- `TrendlinesOptimizationResult`

Default optimizer search includes:

- 5 continuous trendline/signal params,
- extractor left/right windows,
- fitter pivot window,
- optional lookback fraction,
- fitter selection default `ensemble`.

`TrendlinesOptimizationResult` can save/load JSON.

### `src/libs/trendlines/optimization/optimizer.py`

Optuna-backed optimizer.

Class:

- `TrendlinesOptimizer`

Function:

- `_default_pipeline_factory`

Core stages:

```text
create Optuna study
  -> sample params
  -> iterate walk-forward folds
  -> run pipeline on train fold
  -> evaluate lines on forward test fold
  -> aggregate fold benchmarks
  -> return best result
```

Samplers:

- TPE,
- CMA-ES,
- random.

Pruners:

- median,
- hyperband,
- noop fallback.

Important risk: if `fit_result.is_valid` accepts one-sided structure, the optimizer may reward one-sided lines unless benchmark tiers penalize them sufficiently.

### `src/libs/trendlines/optimization/walk_forward.py`

Walk-forward validation wrapper.

Classes:

- `WalkForwardSplit`
- `WalkForwardValidator`

Delegates to trendlines temporal split infrastructure.

### `src/libs/trendlines/optimization/oscillator.py`

Oscillator-specific optimization wrapper.

Class:

- `OscillatorOptimizationConfig`

Functions:

- `_oscillator_pipeline_factory`
- `optimize_oscillator_trendlines`
- `apply_oscillator_result`

Purpose:

- reuse price-space geometric objective for oscillator-space trendline structures,
- apply optimized oscillator params back to config.

### `src/libs/trendlines/optimization/benchmarks/__init__.py`

Benchmark module export surface.

### `src/libs/trendlines/optimization/benchmarks/_tolerance.py`

Shared tolerance computation.

Functions:

- `compute_tolerance`
- `_estimate_atr`

Combines slope-relative and ATR-based tolerance. This avoids under-tolerating flat lines or high-volatility data.

### `src/libs/trendlines/optimization/benchmarks/longevity.py`

Tier 1 benchmark.

Function:

- `compute`

Measures how long lines survive in forward test window before consecutive penetration breach.

### `src/libs/trendlines/optimization/benchmarks/touch_accuracy.py`

Tier 2 benchmark.

Function:

- `compute`

Measures touch-reaction accuracy in forward window.

### `src/libs/trendlines/optimization/benchmarks/penetration_gate.py`

Tier 3 gate.

Functions:

- `compute`
- `gate_penalty`

High penetration rates are penalized multiplicatively. Supports soft gate behavior.

### `src/libs/trendlines/optimization/benchmarks/pivot_density.py`

Tier 4 constraint.

Functions:

- `compute`
- `tent_score`
- `constraint_penalty`

Uses pivot density per 100 bars so the constraint transfers across timeframes/window sizes.

### `src/libs/trendlines/optimization/benchmarks/fold_stability.py`

Tier 5 benchmark.

Function:

- `compute`

Measures cross-fold variance. Lower coefficient of variation means higher stability score.

---

## Workflow Layer

### `src/libs/trendlines/workflows/__init__.py`

Trendlines workflow/application contract root. Re-exports common workflow contracts.

### `src/libs/trendlines/workflows/common/__init__.py`

Exports workflow contracts and promotion helper.

### `src/libs/trendlines/workflows/common/contracts.py`

Workflow study contracts.

Classes:

- `WorkflowStudyStatus`
- `WorkflowPromotionDecision`
- `WorkflowPromotionSpec`
- `WorkflowExperimentSpec`
- `PipelineOptimizationSpec`

Functions:

- `_stable_hash`
- `default_study_status`
- `normalize_study_status`

Purpose:

- deterministic study identity,
- promotion metadata,
- reproducible experiment spec.

### `src/libs/trendlines/workflows/common/promotion.py`

Promotion decision logic.

Function:

- `decide_pipeline_promotion`

Purpose:

- determines whether optimization output is eligible for config promotion.

### `src/libs/trendlines/workflows/benchmarking/__init__.py`

Reserved bounded context for benchmarking flows. Currently minimal.

### `src/libs/trendlines/workflows/monitoring/__init__.py`

Exports drift monitoring workflow.

### `src/libs/trendlines/workflows/monitoring/drift_monitor.py`

Trendlines boundary drift monitor.

Functions:

- `_fetch_futures_klines`
- `_extract_ray_snapshot`
- `build_monitor_snapshot`
- `load_baseline`
- `save_baseline`
- `compare`
- `_run_boundary_pipeline`
- `run_monitor`
- `main`

Purpose:

- run canonical trendline boundary pipeline,
- compare current quality snapshot with saved baseline,
- detect ray degradation/drift.

Risk: uses Binance Futures connector directly inside workflow monitoring; acceptable at workflow edge, not data contracts layer.

### `src/libs/trendlines/workflows/pipeline/__init__.py`

Exports pipeline optimization workflow modules.

### `src/libs/trendlines/workflows/pipeline/evaluation.py`

Pipeline evaluation and parameter search logic.

Functions:

- `_resolve_fit_frame`
- `run_pipeline_with_params`
- `_fit_window_bars`
- `evaluate_trendlines_on_forward`
- `walk_forward_evaluate`
- `evaluate_pivot_count`
- `_extractor_grid`
- `_trendline_fitter_grid`
- `search_pipeline_parameters`

Purpose:

- run trendline pipeline with candidate params,
- evaluate forward quality,
- search candidate extractor/fitter/config combinations.

### `src/libs/trendlines/workflows/pipeline/temporal_spec.py`

Temporal plan and optimization spec builder.

Functions:

- `generate_windows`
- `_manifest_windows`
- `resolve_pipeline_temporal_plan`
- `_coerce_trendline_component_spec`
- `resolve_trendlines_workflow_config`
- `_trendline_lookback_grid`
- `build_pipeline_optimization_spec`

Purpose:

- derive walk-forward windows,
- coerce component params into config,
- build deterministic optimization specs.

### `src/libs/trendlines/workflows/pipeline/support.py`

Workflow support helpers.

Functions:

- `_index_to_date_str`
- `build_pipeline_data_request`
- `build_pipeline_artifact_ref`
- `build_pipeline_split_manifest_ref`
- `_merge_param_dicts`
- `_deep_merge`

Purpose:

- construct deterministic artifact references,
- build workflow data request contracts,
- merge params safely.

### `src/libs/trendlines/workflows/pipeline/config_apply.py`

Config-apply helpers.

Functions:

- `_deep_merge`
- `build_yaml_snippet`
- `apply_pipeline_optimization_to_config`

Purpose:

- convert promoted optimization result to YAML snippet,
- merge promoted params into config.

### `src/libs/trendlines/workflows/pipeline/reporting.py`

Console/report formatting helpers.

Functions:

- `print_results`
- `print_pipeline_yaml_snippet`

### `src/libs/trendlines/workflows/pipeline/data_fetch.py`

Data fetching helpers for workflow edge.

Functions:

- `_build_default_connector`
- `download_historical_data`
- `fetch_pipeline_workflow_data`

Design note: connector behavior belongs here, not in `data/` contracts.

### `src/libs/trendlines/workflows/pipeline/workflow.py`

Public pipeline optimization workflow wrapper and CLI target.

Functions:

- `parse_args`
- `optimize_timeframe`
- `_run_pipeline_cli`
- `main`

Purpose:

- command-level wrapper around data, temporal plan, evaluation, promotion, and reporting.

---

## Scripts

### `src/libs/trendlines/scripts/__init__.py`

Package marker for scripts.

### `src/libs/trendlines/scripts/run_optimization.py`

Large argparse script for running optimization.

Class:

- `StatusFileWriter`

Functions include:

- `fetch_data`
- `load_data_from_csv`
- `_backup_yaml`
- `_make_status_callback`
- `_plateau_analysis`
- `_print_comparison`
- `_print_full_metrics`
- `_print_summary`
- `run_single`
- `run_staged`
- `run_oscillator`
- `_compute_oscillator_series`
- `_prepare_oscillator_df`
- `build_config`
- `_load_universe`
- `main`

Purpose:

- fetch/cached Binance futures OHLCV,
- run single/staged/universe optimization,
- write status for monitor,
- optionally backup/apply YAML.

Risk: large script with multiple responsibilities. Safe changes should be very targeted.

### `src/libs/trendlines/scripts/monitor_optimization.py`

CLI monitor for optimization status JSON.

Class:

- `OptimizationMonitor`

Function:

- `main`

Purpose:

- display progress, best score, trial count, ETA, and process health.

---

## Documentation Files

### `src/libs/trendlines/docs/README.md`

Package overview, quick reference, registered components, stages, scope, and doc map.

### `src/libs/trendlines/docs/architecture.md`

Layer model, dependency graph, import-boundary rules, full pipeline sequence, boundary flow, signal aggregation flow, config hierarchy, canonical seams, optimization design, design rules.

Most important doc for architecture reviews.

### `src/libs/trendlines/docs/agent-map.md`

Operational coding guide. Explains where to change extractors, fitters, config, boundary logic, native signals, pipeline execution, data pipeline, workflows, public API, and CLI.

Most important doc for implementation handoffs.

### `src/libs/trendlines/docs/pipeline.md`

End-to-end pipeline execution and API examples. Good for consumer integration context.

### `src/libs/trendlines/docs/config.md`

Config hierarchy and resolution documentation.

### `src/libs/trendlines/docs/pivots.md`

Pivot algorithms and usage.

### `src/libs/trendlines/docs/fitting.md`

Fitter algorithms and comparison.

### `src/libs/trendlines/docs/boundary.md`

Boundary adapter, Ray contract, interaction detection, quality metrics, context fields.

### `src/libs/trendlines/docs/signals.md`

Native signal extractors, confidence formulas, orchestrator, and quality scoring.

### `src/libs/trendlines/docs/data.md`

Dataset contracts, temporal splits, artifact persistence, auto-split policy.

### `src/libs/trendlines/docs/workflows.md`

Optimization workflow, fitness function, promotion, and drift monitor.

---

## Tests and What They Protect

### Boundary tests

- `test_boundary_adapters.py`: interaction classification, pipeline-to-boundary conversion.
- `test_boundary_history.py`: snapshot history isolation and pruning.
- `test_boundary_public_api.py`: boundary export stability and config param use.
- `test_boundary_quality_metrics.py`: hull width/quality metrics.
- `test_structure_semantics.py`: one-sided vs closed-channel semantics and context flags.

### Config tests

- `test_config.py`: pipeline config round trips.
- `test_config_resolve.py`: asset config resolution.
- `test_derive.py`: profile and derived parameter logic.
- `test_state_transitions_derived.py`: state transition table generation.

### Pivot/fitter/pipeline tests

- `test_extractors.py`: extractor registry and behavior.
- `test_pathfinding_fitter.py`: pathfinding behavior and line-fit modes.
- `test_least_squares_fitter.py`: OLS fitter.
- `test_ransac_fitter.py`: RANSAC fitter.
- `test_ensemble_fitter.py`: ensemble registration, dedup, metadata.
- `test_registry.py`: builder/list/alias behavior.
- `test_pipeline_executor.py`: low-level pipeline execution.
- `test_end_to_end_pipeline.py`: extract -> fit -> boundary -> signals.
- `test_integration_pipeline.py`: facade integration.
- `test_facade_equivalence.py`: boundary facade equivalence.
- `test_public_api.py`: public exports.

### Optimization/workflow tests

- `test_optimization_benchmarks.py`: five-tier metrics.
- `test_optimization_models.py`: optimization dataclasses and serialization.
- `test_optimizer.py`: optimizer with mock pipeline factory.
- `test_optimization_integration.py`: optimizer facade and YAML writeback.
- `test_temporal.py`: temporal split contracts.
- `test_trendlines_pipeline_workflow.py`: workflow spec and optimization metadata.
- `test_workflow_contracts.py`: promotion and workflow contracts.
- `test_trendlines_cli.py`: CLI routing and config apply behavior.
- `test_drift_monitor_workflow.py`: drift monitor behavior.

### Import-boundary test

- `test_import_boundaries.py`: AST-enforced layer boundaries and canonical ownership.

Current known issue: one import-boundary check fails because `src/libs/models/trendlines_old` duplicates boundary symbols.

---

## Known Risks and Contextual Warnings

1. `trendlines_old` conflict

`src/libs/models/trendlines_old` is a duplicate old implementation. It causes canonical symbol ownership failures and pollutes codebase-memory traces.

2. Active path vs docs wording

Docs often refer to `app/trendlines`. The active source path is `src/libs/trendlines`, and `src/app/trendlines` is only a compatibility shim.

3. Validity semantics

`TrendlineFitResult.is_valid` and `BoundaryResult.is_valid` can be true for one-sided structure. Any strategy or RegimeV2 policy requiring a true channel must check `has_both_sides` or `has_closed_channel`.

4. Facade default mismatch

`fit_and_signal` defaults to fitter `pathfinding`, while RegimeV2 and optimizer prefer `ensemble`. This is not necessarily wrong, but it should be documented or standardized for production behavior.

5. Latest-bar interaction

Boundary interaction detection is based on latest price vs current hull/rays with ATR tolerance. Multi-bar confirmation should be handled by temporal signals or downstream policy.

6. Signal extractor fail-soft behavior

`TrendlineSignalOrchestrator.run` catches extractor exceptions and returns no signals for that source. This is good for live safety but can hide broken extractors without log monitoring.

7. Large optimization script

`src/libs/trendlines/scripts/run_optimization.py` is large and multi-purpose. Changes should be avoided unless necessary; prefer workflow modules for reusable logic.

8. RegimeV2 native signal switch

RegimeV2 default `include_native_signals=False` means it consumes geometry features but not native trendline alpha composite by default.

---

## High-Value Next Actions

1. Resolve `src/libs/models/trendlines_old` duplication.

Options:

- delete it,
- move it outside scanned source tree,
- convert to archive docs,
- exclude from import-boundary scan if intentionally kept.

2. Standardize public path language.

Use one convention in docs:

- implementation path: `src/libs/trendlines`,
- import path: `app.trendlines` / `libs.trendlines` depending caller context.

3. Decide default fitter policy.

Evaluate whether facade defaults should move from `pathfinding` to `ensemble`, or whether pathfinding remains the lightweight default and ensemble is reserved for RegimeV2/optimizer.

4. Add a specific RegimeV2 trendline context review.

Focus on whether current flat features are enough for market geometry:

- line age/recency,
- support/resistance strength asymmetry,
- channel slope class,
- compression expansion regime,
- breakout retest state,
- MTF alignment hooks,
- stale ray decay.

5. Run clean test target after old-copy decision.

Target:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/libs/trendlines/tests tests/test_regime_v2_trendline_feature_producer.py -q
```

---

## Quick Context Reload Summary

When reloading this context in a future session:

- Active package is `src/libs/trendlines`.
- Use `api.py` facades first.
- `pipeline/` only does extract -> fit.
- `boundary/` converts fit result into market structure/rays.
- `signals/` runs native structural/temporal/pattern/fakeout signals.
- `config/resolve.py` is the key runtime config seam.
- `optimization/optimizer.py` is Optuna-based geometric quality optimization.
- `workflows/` wraps reproducible data/temporal/promotion/CLI flows.
- RegimeV2 consumes trendlines via `src/libs/models/regime_v2/adapters/trendline_feature_producer.py`.
- `src/libs/models/trendlines_old` is legacy duplicate pollution and should be handled before broad refactors.
