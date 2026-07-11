# Trendlines Old — File-by-File Context Map

Generated for the flipperAgent workspace as a read-only context artifact for `src/libs/models/trendlines_old`.

This file is intentionally separate from:

- `plans/trendlines-model-context-map.md`
- `plans/trendlines-file-by-file-context.md`

The goal is to preserve old-package context without confusing it with the active canonical package.

---

## 0. Executive Summary

`src/libs/models/trendlines_old` is a legacy/archive copy of the trendlines package. It is mostly a snapshot of the current active package, but it is not a clean independent package because most imports inside it still point to `app.trendlines.*`, which resolves to the active canonical package through the compatibility shim at `src/app/trendlines`.

That means:

- Running or importing `trendlines_old` modules may unexpectedly execute active `src/libs/trendlines` internals.
- Codebase-memory sees duplicate classes/functions and can confuse old vs active call paths.
- Active trendlines import-boundary tests currently fail because `trendlines_old` defines duplicate canonical boundary symbols.
- `trendlines_old` also contains large optimization result CSV/JSON artifacts under `optimization/results/`.

High-level comparison against active `src/libs/trendlines`:

```text
old runtime/docs/tests files inspected: 147 total filesystem files
old Python files parsed: 113
syntax errors: 0
shared files identical to active: 134
shared files different from active: 10
files only in old, ignoring .DS_Store: 0
files only in active, ignoring pycache: boundary/history.py + a few newer tests
```

The meaningful code drift is concentrated in:

```text
boundary/__init__.py
boundary/adapters.py
boundary/contracts.py
contracts/contracts.py
fitting/ensemble.py
fitting/pathfinding.py
tests/test_ensemble_fitter.py
tests/test_pathfinding_fitter.py
tests/test_signals.py
workflows/pipeline/workflow.py
```

Active trendlines has newer boundary context, structure semantics, quality normalization, and history support that are missing or smaller in `trendlines_old`.

---

## 1. Package Identity

### Path

```text
src/libs/models/trendlines_old
```

### Status

Archive / legacy copy. It should not be treated as canonical runtime code unless explicitly revived.

### Canonical active replacement

```text
src/libs/trendlines
```

### Compatibility shim that affects this package

```text
src/app/trendlines/__init__.py
```

The shim routes `app.trendlines.*` imports to `src/libs/trendlines`. Since old files mostly import `app.trendlines.*`, the old copy is not self-contained.

---

## 2. Why This Package Is Risky

### 2.1 Duplicate canonical symbols

`trendlines_old` defines classes/functions that import-boundary tests expect to live only under active `src/libs/trendlines`, for example:

```text
Ray
QualityMetrics
BoundaryResult
trendline_to_boundary_ray
build_boundary_result_from_trendline_result
TouchDeclusterConfig
ConfluenceGateConfig
RayTrackerConfig
decluster_touch_indices
```

This causes active package validation failure in:

```text
src/libs/trendlines/tests/test_import_boundaries.py::test_shared_boundary_symbols_have_single_canonical_definition
```

### 2.2 Hybrid import behavior

Example from old package:

```python
from app.trendlines.boundary.contracts import BoundaryResult, QualityMetrics, Ray
from app.trendlines.config import BoundaryAdapterConfig, TrendlinePipelineConfig
from app.trendlines.contracts import Trendline, TrendlineFitResult
```

This means `src/libs/models/trendlines_old/boundary/adapters.py` defines old adapter functions, but imports active boundary contracts and active trendline contracts, not local old-package contracts.

### 2.3 Old package contains generated/result payloads

`src/libs/models/trendlines_old/optimization/results/` contains CSV and JSON outputs. These are useful historical artifacts, but they should not be mixed with runtime code context.

### 2.4 It can pollute codebase-memory

Graph traces already show references to `src.libs.models.trendlines_old.*` mixed with active `src.libs.trendlines.*`, so future impact analysis can be ambiguous unless old is removed, excluded, or converted into explicit archival data.

---

## 3. Active-vs-Old Delta Summary

### 3.1 Files identical to active

Most files are byte-identical to `src/libs/trendlines`, including:

- API facade shape
- config layer
- data/replay contracts
- optimizer and benchmark modules
- registry
- pivot extractors
- least-squares and RANSAC fitters
- signal extractors
- workflows except one textual difference
- docs
- many tests

### 3.2 Files different from active

| File | Old lines | Active lines | Meaning |
|---|---:|---:|---|
| `boundary/__init__.py` | 49 | 57 | old lacks newer boundary history exports |
| `boundary/adapters.py` | 201 | 429 | old lacks boundary context, structure summary, normalized quality helpers |
| `boundary/contracts.py` | 176 | 330 | old lacks structure-state helpers, quality properties, boundary-context convenience accessors |
| `contracts/contracts.py` | 109 | 160 | old lacks structure semantics on `TrendlineFitResult` |
| `fitting/ensemble.py` | 172 | 183 | old lacks newer pathfinding line-fit-mode plumbing/validation details |
| `fitting/pathfinding.py` | 220 | 235 | old lacks newer `line_fit_mode` behavior/tests or reduced implementation detail |
| `tests/test_ensemble_fitter.py` | 85 | 100 | old tests missing newer pathfinding refit-mode coverage |
| `tests/test_pathfinding_fitter.py` | 58 | 90 | old tests missing newer OLS-on-path and validation coverage |
| `tests/test_signals.py` | 313 | 312 | old still imports `app.alpha._runtime`, active removed this compatibility dependency |
| `workflows/pipeline/workflow.py` | 235 | 235 | same line count but content hash differs; likely import/routing drift |

### 3.3 Files present active-side but not old-side

Ignoring `__pycache__`, active has newer files absent in old:

```text
boundary/history.py
tests/test_boundary_history.py
tests/test_boundary_quality_metrics.py
tests/test_structure_semantics.py
```

This confirms active trendlines evolved beyond the old copy mainly around boundary history, quality metrics, and structure-state semantics.

---

## 4. Runtime Pipeline Context

Even though this is `trendlines_old`, the conceptual pipeline is same as active trendlines.

### 4.1 Fit-only flow

```text
fit_trendlines(df)
  -> execute_trendline_pipeline(df)
  -> run_trendline_pipeline(df)
  -> registry.build_extractor(name)
  -> extractor.extract(df) -> PivotSet
  -> registry.build_fitter(name)
  -> fitter.fit(df, pivots) -> TrendlineFitResult
  -> TrendlineOutput(fit_result only)
```

### 4.2 Boundary flow

```text
fit_trendlines_to_boundary(df, asset, timeframe)
  -> execute_trendline_pipeline(df)
  -> build_boundary_result_from_trendline_result(...)
  -> TrendlineOutput(fit_result + boundary_result)
```

Old boundary result is materially thinner than active boundary result.

Old boundary metadata has:

```text
metadata.source
metadata.trendlines
metadata.trendlines.adapter
metadata.trendlines.config, if supplied
```

Active boundary metadata additionally has:

```text
metadata.structure
metadata.context
metadata.normalized_quality
trendlines.structure
trendlines.normalized_quality
```

### 4.3 Full signal flow

```text
fit_and_signal(df, asset, timeframe)
  -> execute_trendline_pipeline(df)
  -> resolve_asset_config(root_config, asset, timeframe, df, fit_result)
  -> build_boundary_result_from_trendline_result(...)
  -> TrendlineSignalOrchestrator(resolved_config).run(boundary, history, context)
  -> TrendlineOutput(fit_result + boundary_result + signal_output)
```

Important: since old files import active `app.trendlines.*`, this may actually run active implementations unless old modules are loaded directly and fully patched to local imports.

### 4.4 Optimization flow

```text
optimize_trendlines(df, asset, timeframe, config)
  -> TrendlinesOptimizer(config)
  -> Optuna study
  -> walk-forward splits
  -> pipeline_factory(params, asset, timeframe)
  -> run_pipeline_with_params(train_df, asset, timeframe, params)
  -> evaluate on forward/test window
  -> aggregate benchmark tiers
  -> TrendlinesOptimizationResult
```

### 4.5 Workflow/CLI flow

```text
trendlines CLI
  -> pipeline-opt command
  -> workflows/pipeline/workflow.py
  -> fetch/prepare data
  -> optimize timeframe
  -> promotion decision
  -> optional config apply
```

---

## 5. File-by-File Context — Package Root

### `src/libs/models/trendlines_old/.DS_Store`

Mac filesystem metadata. Not source. Should not be preserved as code context.

### `src/libs/models/trendlines_old/__init__.py`

Public API re-export surface. Defines no runtime logic itself.

Exports canonical trendlines symbols:

```text
PivotSet
Trendline
TrendlineFitResult
TrendlinePipelineConfig
build_extractor
build_fitter
list_extractors
list_fitters
execute_trendline_pipeline
run_trendline_pipeline
run_trendline_pipeline_from_config
TrendlineOutput
fit_and_signal
fit_oscillator_to_boundary
fit_trendlines
fit_trendlines_to_boundary
optimize_trendlines
```

Important: imports are from `app.trendlines.*`, so this old `__init__` is mostly a forwarding surface to active trendlines.

### `src/libs/models/trendlines_old/api.py`

Facade API. Same shape as active trendlines.

Classes:

```text
TrendlineOutput
```

Functions:

```text
fit_trendlines
fit_trendlines_to_boundary
fit_oscillator_to_boundary
fit_and_signal
optimize_trendlines
```

Role:

- Provides composed public operations.
- Hides extract/fit/boundary/signal chain from consumers.
- Resolves asset/timeframe config for full signal pipeline.

Risk:

- Imports `app.trendlines.*`, so using old facade may still dispatch to active components.

### `src/libs/models/trendlines_old/cli.py`

Thin command router.

Functions:

```text
build_parser
_load_command_module
main
```

Routes workflow commands such as pipeline optimization and drift monitor into workflow modules.

---

## 6. File-by-File Context — Contracts

### `contracts/__init__.py`

Re-exports contract classes from `app.trendlines.contracts.contracts`.

### `contracts/contracts.py`

Core narrow DTOs for pivot extraction and trendline fitting.

Classes:

```text
PivotSet
Trendline
TrendlineFitResult
```

Old behavior:

- `PivotSet` holds high/low indices and values.
- `Trendline` holds line geometry in local bar-index coordinates.
- `TrendlineFitResult` only exposes `best_support`, `best_resistance`, and `to_dict()`.

Missing compared to active:

```text
has_support
has_resistance
has_both_sides
has_closed_channel
is_one_sided_structure
structure_state
structure_summary
metadata["structure"] defaulting in __post_init__
extra to_dict structure flags
```

Implication:

- Old package has weaker structural semantics.
- It cannot directly distinguish `support_only`, `resistance_only`, `closed_channel`, etc. without consumer-side checks.

---

## 7. File-by-File Context — Pivots

### `pivots/__init__.py`

Imports base, fractal, and RDP zigzag modules to trigger decorator-based registration.

### `pivots/base.py`

Defines:

```text
PivotExtractor Protocol
register_extractor decorator
EXTRACTOR_REGISTRY
```

Role:

- Plugin seam for pivot extractors.
- Keeps extraction separate from fitting.

### `pivots/fractal.py`

Defines:

```text
FractalPivotExtractor
```

Behavior:

- Uses left/right window comparison around each bar.
- Swing highs come from `high` column.
- Swing lows come from `low` column.
- Deduplicates equal adjacent pivots by keeping midpoint.
- Search grid is loaded from `GridSearchConfig().fractal`.

### `pivots/rdp_zigzag.py`

Defines:

```text
RDPZigZagPivotExtractor
```

Behavior:

- Simplifies close path with RDP.
- Epsilon is ATR-scaled.
- Converts simplified path turns into high/low pivots.
- Uses `high`/`low` values at pivot indices.

Risk:

- RDP path is based on close, so wick-only pivots may be missed unless captured by final high/low mapping.

---

## 8. File-by-File Context — Fitting

### `fitting/__init__.py`

Imports base and all fitter implementations to trigger registration.

### `fitting/base.py`

Defines:

```text
TrendlineFitter Protocol
register_fitter decorator
FITTER_REGISTRY
```

Role:

- Plugin seam for fitters.
- Fitters must accept `fit(df, pivots=None)` and return `TrendlineFitResult`.

### `fitting/pathfinding.py`

Defines:

```text
PathfindingFitter
```

Old behavior:

- Uses pivot-path dynamic programming.
- Validates candidate segments against candle bodies.
- Builds line from selected path.

Diff vs active:

- Old has 220 lines; active has 235.
- Active includes more explicit `line_fit_mode` behavior/validation, including newer OLS-on-path tests.

Role:

- Conservative geometric fitter that avoids line-body cuts.
- Good for structural support/resistance lines.

### `fitting/least_squares.py`

Defines:

```text
LeastSquaresFitter
```

Behavior:

- Fits OLS line on pivot side.
- Uses ATR-scaled residual threshold for inliers.
- Score is based on `r_squared`.

Status:

- Byte-identical to active.

### `fitting/ransac.py`

Defines:

```text
RansacFitter
```

Behavior:

- Pair-sampled robust line fitting.
- Uses ATR residual threshold.
- Rejects candidates with too many candle-body cuts.
- Defaults to deterministic seed 42.

Status:

- Byte-identical to active.

### `fitting/ensemble.py`

Defines:

```text
EnsembleFitter
_slope_intercept_similar
_deduplicate
```

Behavior:

- Runs pathfinding + least_squares + ransac on same pivot set.
- Pools support/resistance lines.
- Deduplicates near-identical lines by slope/intercept similarity.

Diff vs active:

- Old has 172 lines; active has 183.
- Active has additional pathfinding refit-mode plumbing/metadata/validation.

Role:

- Main robust fitting mode for optimizer and RegimeV2 adapter in active usage.

---

## 9. File-by-File Context — Registry

### `registry/__init__.py`

Re-exports registry surface.

### `registry/registry.py`

Functions:

```text
list_extractors
build_extractor
get_extractor_search_grid
list_fitters
build_fitter
get_fitter_search_grid
```

Role:

- Canonical build/list seam for extractors and fitters.
- Handles deprecated aliases:
  - `fractals -> fractal`
  - `rdp-zigzag -> rdp_zigzag`
  - `ols -> least_squares`
  - `least-squares -> least_squares`

Status:

- Byte-identical to active.

Important import behavior:

- Imports `app.trendlines.pivots` and `app.trendlines.fitting`, so registry population resolves through active app shim if old is imported naively.

---

## 10. File-by-File Context — Pipeline

### `pipeline/__init__.py`

Re-exports pipeline orchestrator functions.

### `pipeline/orchestrator.py`

Functions:

```text
_resolve_extractor
_resolve_fitter
run_trendline_pipeline
run_trendline_pipeline_from_config
execute_trendline_pipeline
```

Role:

- Runs only extract -> fit.
- Does not do boundary adaptation or signals.
- Adds pipeline metadata:
  - extractor name
  - fitter name
  - pivot counts

Status:

- Byte-identical to active.

---

## 11. File-by-File Context — Boundary

This is the biggest difference between old and active.

### `boundary/__init__.py`

Old exports adapter/contracts/policy/touches but does not export `history.py`, because old package does not include boundary history.

Diff vs active:

- active includes `TrendlineSnapshot` and `TrendlineSnapshotHistory` exports.

### `boundary/contracts.py`

Classes:

```text
Ray
QualityMetrics
BoundaryResult
```

Function:

```text
boundary_interaction_direction
```

Old behavior:

- `Ray` exposes basic projection and touch metadata.
- `QualityMetrics` only reports:
  - ray counts
  - mean score
  - mean touch count
  - mean r_squared
  - hull_width_atr
- `BoundaryResult` only exposes:
  - best support/resistance
  - raw to_dict fields

Missing vs active:

```text
Ray.normalized_quality_score
Ray.quality_components
QualityMetrics.mean_normalized_quality
QualityMetrics.mean_support_quality
QualityMetrics.mean_resistance_quality
BoundaryResult.has_support
BoundaryResult.has_resistance
BoundaryResult.has_both_sides
BoundaryResult.has_closed_channel
BoundaryResult.is_one_sided_structure
BoundaryResult.structure_state
BoundaryResult.structure_summary
BoundaryResult.boundary_context
BoundaryResult.market_position_state
BoundaryResult.hull_position
BoundaryResult.is_inside_channel
BoundaryResult.is_above_channel
BoundaryResult.is_below_channel
BoundaryResult.is_near_support
BoundaryResult.is_near_resistance
BoundaryResult.is_mid_channel_noise
BoundaryResult.has_channel_compression
BoundaryResult.has_upper_channel_pressure
BoundaryResult.has_lower_channel_pressure
BoundaryResult.mean_normalized_quality
BoundaryResult.best_support_quality
BoundaryResult.best_resistance_quality
```

Important old bug/limitation:

- Old `hull_width_atr` is `(hull_ceiling - hull_floor) / ATR`, not absolute width. Active changed to absolute hull width to avoid negative/inverted channel oddities.

### `boundary/adapters.py`

Functions:

```text
_validate_trendline_boundary_frame
_mean_true_range
_detect_boundary_interaction
trendline_to_boundary_ray
build_boundary_result_from_trendline_result
```

Old behavior:

- Converts trendlines to rays.
- Computes hull floor and ceiling from support/resistance rays at latest bar.
- Computes ATR.
- Detects latest-bar interaction:
  - structural breakdown
  - structural breakout
  - support bounce
  - resistance bounce
  - none
- Builds basic `BoundaryResult`.

Missing vs active:

```text
_distance_atr
_hull_position
_build_boundary_context
_clip01
_line_coverage_score
_residual_quality_score
_line_quality_summary
normalized quality metadata
structure metadata
context metadata
support/resistance distance ATR
inside/above/below channel state
near support/resistance flags
mid-channel noise
channel compression
upper/lower channel pressure
best support/resistance quality
```

Implication:

- Old boundary adapter is usable for simple ray/interaction conversion.
- It is not sufficient for richer RegimeV2 context features that rely on active boundary context fields.

### `boundary/policy.py`

Classes:

```text
TouchDeclusterConfig
TouchDiagnostics
ConfluenceGateConfig
ConfluenceQualitySnapshot
RayTrackerConfig
TrackedRayState
```

Status:

- Byte-identical to active.

Role:

- Typed policy contracts for touch declustering, confluence gating, and ray tracking state.

### `boundary/touches.py`

Functions:

```text
decluster_touch_indices
_resolve_min_gap
```

Status:

- Byte-identical to active.

### Missing old file: `boundary/history.py`

Active package has:

```text
TrendlineSnapshot
TrendlineSnapshotHistory
```

Old package does not. This matters for temporal signals and RegimeV2 adapter history.

---

## 12. File-by-File Context — Signals

Most old signal files are byte-identical to active except `tests/test_signals.py` still references `app.alpha._runtime`.

### `signals/__init__.py`

Exports signal contract and extractor classes.

### `signals/base.py`

Classes:

```text
AlphaSignal
BaseAlphaExtractor
```

Role:

- Native trendline signal DTO and extractor protocol.

### `signals/constants.py`

Signal constants and interaction direction semantics.

### `signals/structural.py`

Class:

```text
StructuralAlphaExtractor
```

Emits signals around:

- interaction label
- hull squeeze
- support/resistance asymmetry

### `signals/temporal.py`

Class:

```text
TemporalAlphaExtractor
```

Emits signals around:

- hull convergence
- state transitions
- ray persistence bias
- slope acceleration

Depends on boundary history passed by caller.

### `signals/patterns.py`

Class:

```text
PatternAlphaExtractor
```

Detects structural patterns such as channel/triangle-like setups from support/resistance rays.

### `signals/fakeout.py`

Class:

```text
FakeoutAlphaExtractor
```

Detects:

- false breakout/breakdown
- wick rejection
- low-volume breakout/breakdown
- confirmed breakout/breakdown

Uses OHLCV context and history.

### `signals/quality.py`

Functions:

```text
clamp_unit
touch_count_confidence_factor
blended_quality_score
confluence_confidence
price_quality_for_direction
oscillator_quality_for_direction
```

Role:

- Shared confidence/quality helpers.

### `signals/orchestrator.py`

Class:

```text
TrendlineSignalOrchestrator
```

Function:

```text
_build_extractors_from_resolved
```

Behavior:

- Builds structural, temporal, pattern, fakeout extractors from resolved config.
- Runs all extractors fail-soft.
- Aggregates weighted direction and confidence.

Risk:

- Fail-soft behavior can hide extractor errors unless logs are reviewed.

---

## 13. File-by-File Context — Config

Config files are byte-identical to active.

### `config/__init__.py`

Aggregates config exports.

### `config/base_config.py`

Classes:

```text
AssetTimeframeConfig
AssetConfig
OptimizableDefaults
OscillatorDefaults
OscillatorOverride
TrendlinesConfig
TrendlinePipelineConfig
```

Role:

- Root config contracts.
- Holds global defaults, per-asset/timeframe overrides, oscillator defaults, evaluation protocol, search grids, signal weights.

### `config/asset_profile.py`

Class:

```text
AssetProfile
```

Functions:

```text
_tf_to_minutes
_mean_true_range_simple
```

Role:

- Computes per-run market stats from OHLCV.
- Supports adaptive derived params.

### `config/oscillator_profile.py`

Class:

```text
OscillatorProfile
```

Role:

- Oscillator-space equivalent of AssetProfile.
- Avoids price-scale assumptions like ATR/mean price.

### `config/derive.py`

Functions:

```text
derive_hold_bars
derive_volume_lookback
derive_min_history
derive_atr_window
derive_consecutive_penetration_bars
derive_forward_lookahead_bars
derive_parallel_tol
derive_flat_tol
derive_full_confidence_touches
derive_slope_match_tol
derive_slope_accel_threshold
compute_all_derived
compute_oscillator_derived
```

Role:

- Pure adaptive-parameter derivation from profile stats.

### `config/resolve.py`

Classes:

```text
ResolvedSignalConfig
ResolvedConfig
ResolvedOscillatorConfig
```

Functions:

```text
resolve_asset_config
resolve_oscillator_config
```

Role:

- Merges defaults -> asset/timeframe overrides -> derived values.
- Produces frozen runtime config used by boundary and signal stages.

### `config/loader.py`

Functions:

```text
_merge_dicts
_parse_asset_tf_config
_parse_assets
_parse_oscillator_defaults
_parse_oscillator_overrides
load_trendlines_config
```

Role:

- Loads YAML config with fallback defaults.

### `config/defaults.py`

Function:

```text
get_default_config_dict
```

Role:

- Python fallback for missing YAML.

### `config/evaluation_config.py`

Classes:

```text
FitnessConfig
WalkForwardDefaults
LookbackGridConfig
DriftMonitorConfig
EvaluationConfig
```

### `config/search_grid_config.py`

Classes:

```text
FractalSearchGrid
RDPSearchGrid
PathfindingSearchGrid
LeastSquaresSearchGrid
RansacSearchGrid
GridSearchConfig
```

### `config/signal_config.py`

Backward-compatible signal config classes.

Important note from docstring:

- Many fields moved to hardcoded constants, derived config, or `OptimizableDefaults`.

### `config/state_transitions.py`

Functions:

```text
_classify_transition
_compute_direction
build_state_transition_table
```

Role:

- Deterministically derives transition table from market logic.

### `config/trendlines.yaml`

YAML config source. Same as active.

---

## 14. File-by-File Context — Data / Replay

All data files are byte-identical to active.

### `data/__init__.py`

Exports data contracts, fetchers, artifacts, temporal helpers.

### `data/contracts.py`

Classes:

```text
TrendlineArtifactRef
TrendlineDataRequest
TrendlineDatasetManifest
```

Functions:

```text
_stable_hash
normalize_timeframes
_normalize_names
```

Role:

- Deterministic data request and replay identity.

### `data/fetchers.py`

Class:

```text
TrendlineDatasetLoader Protocol
```

Functions:

```text
_normalize_columns
_normalize_frame_map
build_dataset_manifest
load_dataset
```

Role:

- Source-agnostic data loading via injected loader.

### `data/artifacts.py`

Functions:

```text
artifact_path
_write_json_artifact
_read_json_artifact
_resolve_manifest_artifact
write_dataset_manifest
read_dataset_manifest
write_temporal_split_manifest
read_temporal_split_manifest
```

Role:

- Deterministic JSON artifact persistence.

### `data/temporal.py`

Classes:

```text
WalkForwardSplit
WalkForwardValidator
TemporalSplitSpec
TemporalSplitManifest
```

Functions:

```text
_stable_hash
resolve_trendline_auto_split_spec
build_temporal_split_manifest
```

Role:

- Trendline-owned walk-forward split planning.

---

## 15. File-by-File Context — Optimization

Most optimization code is byte-identical to active.

### `optimization/.DS_Store`

Mac metadata. Not source.

### `optimization/__init__.py`

Exports optimization models, optimizer, oscillator, walk-forward.

### `optimization/models.py`

Classes:

```text
TrendlinesBenchmarkResults
TrendlinesOptimizationWeights
TrendlinesOptimizationConfig
TrendlinesTrialResult
TrendlinesOptimizationResult
```

Role:

- DTOs for optimization config/results/trial histories.

Important objective context:

- Optimizes 5 continuous params:
  - `interaction_tolerance_atr`
  - `asymmetry_threshold`
  - `convergence_rate_threshold`
  - `wick_rejection_ratio`
  - `squeeze_threshold`
- Also samples categorical extractor/fitter params.

### `optimization/optimizer.py`

Class:

```text
TrendlinesOptimizer
```

Function:

```text
_default_pipeline_factory
```

Role:

- Optuna-based search loop.
- Walk-forward CV.
- Computes tiered objective.

### `optimization/walk_forward.py`

Classes:

```text
WalkForwardSplit
WalkForwardValidator
```

Role:

- Delegates to data temporal split infrastructure.

### `optimization/oscillator.py`

Class:

```text
OscillatorOptimizationConfig
```

Functions:

```text
_oscillator_pipeline_factory
optimize_oscillator_trendlines
apply_oscillator_result
```

Role:

- Reuses price-space optimizer for oscillator-space trendlines.

### `optimization/benchmarks/_tolerance.py`

Functions:

```text
compute_tolerance
_estimate_atr
```

Role:

- ATR-aware projected-line tolerance.

### `optimization/benchmarks/longevity.py`

Function:

```text
compute
```

Tier 1: line survival ratio.

### `optimization/benchmarks/touch_accuracy.py`

Function:

```text
compute
```

Tier 2: touch reaction prediction accuracy.

### `optimization/benchmarks/penetration_gate.py`

Functions:

```text
compute
gate_penalty
```

Tier 3: penetration-rate gate.

### `optimization/benchmarks/pivot_density.py`

Functions:

```text
compute
tent_score
constraint_penalty
```

Tier 4: pivot density constraint.

### `optimization/benchmarks/fold_stability.py`

Function:

```text
compute
```

Tier 5: cross-fold stability.

---

## 16. File-by-File Context — Optimization Results Artifacts

`src/libs/models/trendlines_old/optimization/results/` contains historical data and optimizer outputs.

Files include:

```text
.optimization_status.json
BTCUSDT_1h_2022-01-01_2026-03-01.csv
BTCUSDT_1h_2023-01-01_2026-03-01.csv
BTCUSDT_1h_2026-04-12_09-49_staged.json
BTCUSDT_1h_2026-04-12_11-53_staged.json
BTCUSDT_1h_2026-04-12_12-41_staged.json
BTCUSDT_1h_2026-04-12_13-23_staged.json
BTCUSDT_1h_2026-04-12_13-45_staged.json
BTCUSDT_1h_2026-04-12_14-32_staged.json
BTCUSDT_1h_2026-04-12_15-59_staged.json
BTCUSDT_1h_rsi_2026-04-12_20-07.json
BTCUSDT_1h_rsi_2026-04-12_20-21.json
ETHUSDT_1h_2023-01-01_2026-03-01.csv
ETHUSDT_1h_2026-04-12_16-29_staged.json
HYPEUSDT_1h_2022-01-01_2026-03-01.csv
HYPEUSDT_1h_2026-04-12_18-15_staged.json
SOLUSDT_1h_2023-01-01_2026-03-01.csv
SOLUSDT_1h_2026-04-12_16-59_staged.json
sweep_1h.log
```

Large payload examples by line count:

```text
BTCUSDT_1h_rsi_2026-04-12_20-21.json -> 241086 lines
BTCUSDT_1h_rsi_2026-04-12_20-07.json -> 144686 lines
BTCUSDT_1h_2022-01-01_2026-03-01.csv -> 36482 lines
BTCUSDT_1h_2023-01-01_2026-03-01.csv -> 27722 lines
ETHUSDT_1h_2023-01-01_2026-03-01.csv -> 27722 lines
SOLUSDT_1h_2023-01-01_2026-03-01.csv -> 27722 lines
```

Interpretation:

- These are historical optimization/data artifacts, not source modules.
- If `trendlines_old` is deleted later, these may need to be preserved separately if the user wants historical auditability.
- Recommended archival destination if preserving:
  - `artifacts/trendlines_old_optimization_results/`
  - or a compressed archive outside `src/`.

---

## 17. File-by-File Context — Scripts

### `scripts/__init__.py`

Empty marker module.

### `scripts/monitor_optimization.py`

Class:

```text
OptimizationMonitor
```

Function:

```text
main
```

Role:

- Polls optimization status JSON.
- Displays progress, best score, stage info, ETA, process health.

### `scripts/run_optimization.py`

Class:

```text
StatusFileWriter
```

Functions:

```text
fetch_data
load_data_from_csv
_backup_yaml
_make_status_callback
_plateau_analysis
_print_comparison
_print_full_metrics
_print_summary
run_single
run_staged
run_oscillator
_compute_oscillator_series
_prepare_oscillator_df
build_config
_load_universe
main
```

Role:

- Standalone Binance Futures data fetch + optimization runner.
- Supports single/staged/universe/oscillator modes.
- Writes status files and result JSONs.

Risk:

- Large script with network/data/config mutation responsibilities combined.
- Because old imports active `app.trendlines`, running this from old path may operate on active implementation.

---

## 18. File-by-File Context — Workflows

Most workflow files are byte-identical to active.

### `workflows/.DS_Store`

Mac metadata. Not source.

### `workflows/__init__.py`

Exports common workflow contracts.

### `workflows/benchmarking/__init__.py`

Placeholder/reserved benchmarking bounded context.

### `workflows/common/__init__.py`

Exports workflow common contracts and promotion helpers.

### `workflows/common/contracts.py`

Classes:

```text
WorkflowStudyStatus
WorkflowPromotionDecision
WorkflowPromotionSpec
WorkflowExperimentSpec
PipelineOptimizationSpec
```

Functions:

```text
_stable_hash
default_study_status
normalize_study_status
```

Role:

- Deterministic workflow/study DTOs.

### `workflows/common/promotion.py`

Function:

```text
decide_pipeline_promotion
```

Role:

- Promotion threshold helper.

### `workflows/monitoring/__init__.py`

Exports drift monitor.

### `workflows/monitoring/drift_monitor.py`

Functions:

```text
_fetch_futures_klines
_extract_ray_snapshot
build_monitor_snapshot
load_baseline
save_baseline
compare
_run_boundary_pipeline
run_monitor
main
```

Role:

- Runs boundary pipeline and compares quality snapshot against a baseline.

### `workflows/pipeline/__init__.py`

Exports pipeline workflow components.

### `workflows/pipeline/config_apply.py`

Functions:

```text
_deep_merge
build_yaml_snippet
apply_pipeline_optimization_to_config
```

Role:

- Builds and applies YAML config snippets from optimization results.

### `workflows/pipeline/data_fetch.py`

Functions:

```text
_build_default_connector
download_historical_data
fetch_pipeline_workflow_data
```

Role:

- Data fetching helper for pipeline workflows.

### `workflows/pipeline/evaluation.py`

Functions:

```text
_resolve_fit_frame
run_pipeline_with_params
_fit_window_bars
evaluate_trendlines_on_forward
walk_forward_evaluate
evaluate_pivot_count
_extractor_grid
_trendline_fitter_grid
search_pipeline_parameters
```

Role:

- Walk-forward scoring and parameter search logic.

### `workflows/pipeline/reporting.py`

Functions:

```text
print_results
print_pipeline_yaml_snippet
```

### `workflows/pipeline/support.py`

Functions:

```text
_index_to_date_str
build_pipeline_data_request
build_pipeline_artifact_ref
build_pipeline_split_manifest_ref
_merge_param_dicts
_deep_merge
```

Role:

- Artifact refs, request construction, and helper merges.

### `workflows/pipeline/temporal_spec.py`

Functions:

```text
generate_windows
_manifest_windows
resolve_pipeline_temporal_plan
_coerce_trendline_component_spec
resolve_trendlines_workflow_config
_trendline_lookback_grid
build_pipeline_optimization_spec
```

Role:

- Temporal plan and pipeline optimization spec builder.

### `workflows/pipeline/workflow.py`

Functions:

```text
parse_args
optimize_timeframe
_run_pipeline_cli
main
```

Diff vs active:

- Same line count but different hash. Needs focused diff before using or deleting if preservation matters.

Role:

- Public workflow wrapper around pipeline optimization.

---

## 19. File-by-File Context — Docs

All docs appear mirrored from active package.

### `docs/README.md`

Quick reference, module map, registered components, pipeline stages, scope.

### `docs/architecture.md`

Layer model, dependency graph, import-boundary rules, pipeline flow, config hierarchy, optimization architecture.

### `docs/agent-map.md`

Agent/coder guide for changing extractors, fitters, config, boundary, signals, pipeline, data, workflows, public API, CLI.

### `docs/pipeline.md`

Pipeline contracts and facade examples.

### `docs/pivots.md`

Fractal and RDP zigzag pivot extraction details.

### `docs/fitting.md`

Pathfinding, least-squares, RANSAC, ensemble fitting concepts.

### `docs/boundary.md`

Boundary adaptation and interaction semantics.

### `docs/signals.md`

Native trendline signal extractors and aggregation.

### `docs/config.md`

TrendlinesConfig hierarchy and YAML loading.

### `docs/data.md`

Dataset manifests, temporal split policies, artifact persistence.

### `docs/workflows.md`

Optimization workflow, fitness function, promotion, drift monitor.

Risk:

- Docs say `app/trendlines`, but old package path is `src/libs/models/trendlines_old`. Treat docs as copied from active architecture, not old-specific documentation.

---

## 20. File-by-File Context — Tests

### Key old tests identical or near-identical to active

```text
test_boundary_adapters.py
test_boundary_public_api.py
test_config.py
test_config_resolve.py
test_data_contracts.py
test_data_fetchers.py
test_derive.py
test_drift_monitor_workflow.py
test_end_to_end_pipeline.py
test_extractors.py
test_facade_equivalence.py
test_import_boundaries.py
test_integration_pipeline.py
test_least_squares_fitter.py
test_optimization_benchmarks.py
test_optimization_integration.py
test_optimization_models.py
test_optimizer.py
test_pipeline_executor.py
test_public_api.py
test_ransac_fitter.py
test_registry.py
test_signal_orchestrator_config.py
test_state_transitions_derived.py
test_temporal.py
test_trendlines_cli.py
test_trendlines_pipeline_workflow.py
test_workflow_contracts.py
```

### Tests missing in old compared to active

```text
test_boundary_history.py
test_boundary_quality_metrics.py
test_structure_semantics.py
```

These align with active package additions around boundary history, quality metrics, and structure-state semantics.

### Tests different from active

#### `tests/test_ensemble_fitter.py`

Old has 85 lines, active has 100.

Old missing newer coverage around pathfinding line-fit-mode propagation/validation.

#### `tests/test_pathfinding_fitter.py`

Old has 58 lines, active has 90.

Old missing newer tests for:

- `ols_on_path` refit behavior
- unknown line-fit-mode rejection

#### `tests/test_signals.py`

Old imports `app.alpha._runtime`, while active removed this dependency.

This is a major compatibility smell because trendline-native signals are supposed to be self-sufficient and not depend on alpha runtime compatibility.

#### `tests/test_import_boundaries.py`

Old copy includes same import-boundary suite, but the presence of old package under `src/libs/models` causes the active suite to flag duplicate canonical boundary symbols.

---

## 21. What Old Package Can Still Be Useful For

### Useful as archive

- Preserves old trendline implementation before active boundary/context expansion.
- Preserves old optimization result artifacts.
- Useful for comparing why active structure semantics were introduced.

### Useful as migration reference

The old-vs-active deltas show exactly what changed:

- Boundary result became richer.
- One-sided structures got explicit semantics.
- Normalized quality components were added.
- Boundary context became feature-ready for RegimeV2.
- Boundary history support was added.
- Alpha runtime compatibility was removed from signal tests.

### Not useful as runtime package

It is not self-contained due to `app.trendlines.*` imports. Running it can route into active package code.

---

## 22. Recommended Cleanup / Preservation Options

### Option A — Delete old package entirely

Best if no historical artifacts are needed.

Pros:

- Fixes duplicate symbol/import-boundary pollution.
- Reduces codebase-memory confusion.
- Removes dead source surface.

Cons:

- Loses historical optimization result artifacts unless moved first.

### Option B — Archive results, delete source

Recommended balanced approach.

Move or preserve:

```text
src/libs/models/trendlines_old/optimization/results/
```

Then delete the old package source/tests/docs.

Possible archive path:

```text
artifacts/trendlines_old_optimization_results/
```

Pros:

- Keeps useful historical payloads.
- Removes duplicate runtime code.

### Option C — Keep but exclude from tests/index

Less ideal.

Would need:

- import-boundary exclusions
- codebase-memory ignore/exclude behavior if supported
- possibly `.gitignore` or test path changes

Risk:

- Long-term confusion remains.

### Option D — Convert to explicit historical docs only

Keep summary docs and maybe compressed result artifacts, but remove importable Python package.

Pros:

- Context preserved without duplicate symbols.
- Safer than keeping importable old Python modules.

---

## 23. Specialist Review Notes

### quant-research pass

Old package is most useful for historical comparison: it shows the package before richer market-geometry feature context was added. For modeling, active package is strictly more useful because it exposes structure states and normalized quality metrics needed by RegimeV2 and regime-prob pipelines.

### quant-architect pass

Architecture risk is not inside individual old functions; it is the existence of a half-active/half-old duplicate package. Because imports point to `app.trendlines`, old modules are not an independent architecture boundary.

### quant-review pass

Blocking risk: duplicate symbols break canonical boundary ownership tests. Secondary risk: codebase-memory call graphs can attribute edges to old modules. Old should be deleted or archived before more trendline/regime integration work.

### quant-approval pass

Do not build new functionality on `src/libs/models/trendlines_old`. Treat active `src/libs/trendlines` as canonical. Preserve only historical optimization artifacts if needed.

---

## 24. Validation Performed

Read-only validation:

```text
Python AST parse over src/libs/models/trendlines_old/**/*.py
Parsed Python files: 113
Syntax errors: 0
```

No runtime tests were run for old package because it is not cleanly isolated from active `app.trendlines` imports.

---

## 25. Next Handoff / Next Step

Recommended next step:

1. Decide whether old optimization results should be preserved.
2. If yes, move/archive only `optimization/results/` outside source.
3. Delete or de-import `src/libs/models/trendlines_old` source/tests/docs.
4. Re-run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/libs/trendlines/tests/test_import_boundaries.py -q
```

5. Re-run full trendlines + RegimeV2 adapter tests:

```bash
PYTHONPATH=src .venv/bin/python -m pytest src/libs/trendlines/tests tests/test_regime_v2_trendline_feature_producer.py -q
```

Expected effect:

- Canonical boundary-symbol test should stop failing due to old duplicates.
- codebase-memory graph should become cleaner after re-index.
