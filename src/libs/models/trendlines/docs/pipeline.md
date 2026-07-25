# Pipeline

The trendlines pipeline converts raw OHLC price data into structured alpha signals through four
sequential stages. Each stage is independently swappable via the registry.

## Stages Overview

| Stage | Input | Output | Owner |
|-|-|-|-|
| EXTRACT | `pd.DataFrame` (OHLC) | `PivotSet` | `pivots/` |
| FIT | `pd.DataFrame`, `PivotSet` | `TrendlineFitResult` | `fitting/` |
| RESOLVE | `TrendlinesConfig`, df, fit_result | `ResolvedConfig` | `config/resolve.py` |
| ADAPT | `TrendlineFitResult`, df, resolved boundary | `BoundaryResult` | `boundary/` |
| SIGNAL | `BoundaryResult`, history, context, resolved signals | `{signals[], composite}` | `signals/` |

## Contracts

### PivotSet (`contracts/contracts.py`)

Pivot indices and prices extracted from raw OHLC data.

| Field | Type | Description |
|-|-|-|
| `high_indices` | `np.ndarray[int]` | Bar indices of swing highs |
| `high_values` | `np.ndarray[float]` | Price values at swing highs |
| `low_indices` | `np.ndarray[int]` | Bar indices of swing lows |
| `low_values` | `np.ndarray[float]` | Price values at swing lows |

Properties: `n_highs`, `n_lows`, `total_pivots`, `is_valid(min_pivots=2)`.

### Trendline (`contracts/contracts.py`)

A single fitted line (support or resistance).

| Field | Type | Description |
|-|-|-|
| `start_index` | `int` | First bar index of the line |
| `end_index` | `int` | Last bar index of the line |
| `start_value` | `float` | Price at start_index |
| `end_value` | `float` | Price at end_index |
| `slope` | `float` | Price change per bar |
| `intercept` | `float` | y-intercept of the linear equation |
| `touch_count` | `int` | Number of confirmed pivot touches |
| `is_support` | `bool` | True = support line, False = resistance |
| `method` | `str` | Fitter method identifier (e.g. `"pathfinding"`) |
| `score` | `float` | Fitter-specific quality score |
| `metadata` | `dict` | Fitter-specific extras |

Methods: `value_at(index) -> float`, `project(steps_ahead) -> float`, `to_dict()`.

### TrendlineFitResult (`contracts/contracts.py`)

Container for the full set of fitted lines.

| Field | Type | Description |
|-|-|-|
| `support_lines` | `List[Trendline]` | Fitted support lines (ascending score = better) |
| `resistance_lines` | `List[Trendline]` | Fitted resistance lines |
| `is_valid` | `bool` | True if at least one line on each side |
| `metadata` | `dict` | Extractor/fitter names, pivot counts, timing |

Properties: `best_support`, `best_resistance` (max score from each list).

### TrendlineOutput (`api.py`)

Wrapper returned by all facade functions.

| Field | Type | Description |
|-|-|-|
| `fit_result` | `TrendlineFitResult` | Raw fitted lines |
| `boundary_result` | `BoundaryResult \| None` | Boundary-adapted result |
| `signal_output` | `dict \| None` | Orchestrator output |
| `config` | `TrendlinePipelineConfig \| None` | Config used |
| `metadata` | `dict` | Timing, component names |

Properties: `is_valid`, `composite_direction`, `composite_confidence`.

## Facade API (`api.py`)

### `fit_trendlines(df, config, extractor, fitter, ...) -> TrendlineOutput`

Runs **Stage 1 + Stage 2** only (extract → fit). Returns `TrendlineOutput` with
`boundary_result=None` and `signal_output=None`.

```python
from libs.models.trendlines import fit_trendlines

output = fit_trendlines(
    df,                          # pd.DataFrame with open/high/low/close, DatetimeIndex
    extractor="fractal",         # registry name
    fitter="pathfinding",        # registry name
    extractor_kwargs={"window_left": 5, "window_right": 5},
)
best_support = output.fit_result.best_support
print(best_support.slope, best_support.touch_count)
```

### `fit_trendlines_to_boundary(df, asset, timeframe, ...) -> TrendlineOutput`

Runs **Stages 1 + 2 + 3** (extract → fit → boundary adaptation). Returns `TrendlineOutput`
with `boundary_result` populated. `signal_output` is still `None`.

```python
from libs.models.trendlines import fit_trendlines_to_boundary

output = fit_trendlines_to_boundary(
    df, asset="BTCUSDT", timeframe="1h",
    trendlines_config=my_config,   # TrendlinesConfig — controls atr_window, tolerance
)
ray = output.boundary_result.best_support
print(ray.project(bars_ahead=3), output.boundary_result.interaction)
```

### `fit_and_signal(df, asset, timeframe, ...) -> TrendlineOutput`

Runs the **full pipeline: Stages 1 + 2 + RESOLVE + 3 + 4**. Returns `TrendlineOutput` with
all fields populated.

After the fit stage, the function resolves the full config for this `(asset, timeframe)` via
`resolve_asset_config()`. This builds an `AssetProfile` from the DataFrame, computes derived
params, resolves optimizable overrides, and produces a frozen `ResolvedConfig`.

```python
from libs.models.trendlines import fit_and_signal

output = fit_and_signal(
    df, asset="BTCUSDT", timeframe="1h",
    trendlines_config=my_config,           # TrendlinesConfig — with per-asset/TF overrides
    history=[prev_boundary_result],        # Optional List[BoundaryResult] for temporal signals
    context={"ohlcv": df, "atr": 250.0},  # Optional context for fakeout signals
)

print(output.composite_direction)    # float in [-1.0, 1.0]
print(output.composite_confidence)   # float in [0.0, 1.0]
print(output.metadata["asset_profile"])  # dict with tf_minutes, mean_atr, etc.
for sig in output.signal_output["signals"]:
    print(sig["name"], sig["direction"], sig["confidence"])
```

## Low-Level Pipeline API (`pipeline/orchestrator.py`)

Use these when you want to control extractor/fitter directly without the facade.

### `run_trendline_pipeline(df, extractor, fitter, extractor_kwargs, fitter_kwargs) -> TrendlineFitResult`

Builds extractor and fitter from the registry, runs extract → fit.

```python
from libs.models.trendlines import run_trendline_pipeline

result = run_trendline_pipeline(
    df,
    extractor="rdp_zigzag",
    fitter="ransac",
    extractor_kwargs={"epsilon_atr": 0.3},
    fitter_kwargs={"max_trials": 100},
)
```

### `execute_trendline_pipeline(df, config) -> tuple[TrendlineFitResult, TrendlinePipelineConfig]`

Takes a typed `TrendlinePipelineConfig` (or `TrendlinesConfig`) and runs the pipeline.
Returns both the result and the resolved config. Used by the optimization workflow.

## Config-Driven Execution

The pipeline reads defaults from the config hierarchy. All stages respect the same
`TrendlinesConfig` root:

```python
from libs.models.trendlines.config import load_trendlines_config

cfg = load_trendlines_config()           # Loads trendlines.yaml (falls back to defaults.py)
output = fit_and_signal(df, "BTCUSDT", "1h", trendlines_config=cfg)
```

To override specific optimizable parameters:

```python
from dataclasses import replace
from libs.models.trendlines.config import TrendlinesConfig, OptimizableDefaults

cfg = replace(
    TrendlinesConfig(),
    extractor="rdp_zigzag",
    defaults=replace(OptimizableDefaults(), squeeze_threshold=2.0),
)
```

## Config Resolution

At execution time, `resolve_asset_config(root, asset, timeframe, df, fit_result)` produces
a frozen `ResolvedConfig`. Resolution order:

1. **OptimizableDefaults** — universe-level baselines from `defaults:`
2. **Per-asset/TF overrides** — from `assets.{asset}.timeframes.{tf}` (overrides defaults)
3. **AssetProfile** — computed from the DataFrame (df length, ATR, price level, etc.)
4. **Derived params** — pure functions of AssetProfile (hold_bars, volume_lookback, etc.)
5. **State transitions** — derived from market physics (14-entry table)
6. **Assembly** — merged into `ResolvedConfig(signals, boundary, protocol, profile, ...)`

Derived and hardcoded params are never in the YAML. They are always computed or constant.

## Metadata Flow

Every stage attaches metadata that flows through to `TrendlineOutput.metadata`:

```
pipeline/orchestrator.py:
  metadata["pipeline"]["extractor_name"]      = "fractal"
  metadata["pipeline"]["fitter_name"]         = "pathfinding"
  metadata["pipeline"]["n_high_pivots"]       = 12
  metadata["pipeline"]["n_low_pivots"]        = 11

api.py (after resolve):
  metadata["asset_profile"]                   = {tf_minutes, mean_atr, mean_price, n_bars, ...}

boundary/adapters.py (in BoundaryResult.metadata):
  metadata["source"]                          = "trendlines"
  metadata["trendlines"]["adapter"]["atr_window"]          = 14
  metadata["trendlines"]["adapter"]["interaction_tolerance_atr"] = 0.25
  metadata["trendlines"]["trendline_method"]  = "pathfinding"
  metadata["trendlines"]["extractor"]         = "fractal"
```

## Optimization Pipeline

The `optimization/` submodule wraps the evaluation pipeline in Bayesian search:

```
trendlines.yaml (search_grids + defaults + protocol.walk_forward)
    ↓
TrendlinesOptimizer.optimize(df, asset, timeframe)
    ↓
Optuna TPE study (n_trials × n_folds):
  trial → sample 5 continuous + 3 categorical params
       → walk-forward CV loop
         → run_pipeline_with_params(train) → TrendlineFitResult
         → evaluate on test_df via 5-tier benchmarks
       → aggregate fold scores + stability bonus
    ↓
Best params → TrendlinesOptimizationResult
    ↓
result.save("results.json")           # Full trial history
result.apply_to_config("trendlines.yaml")  # Write to per-asset/TF YAML
```

**Facade:** `optimize_trendlines(df, asset, timeframe, config)` in `api.py`.
