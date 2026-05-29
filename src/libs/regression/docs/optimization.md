# Regression v2 — Optimization Subsystem

## Overview

The optimization subsystem (`app/regression/optimization/`) implements Bayesian hyperparameter optimization for the regression pipeline using Optuna with walk-forward cross-validation and a 5-tier composite scoring framework.

## Architecture

```
optimize_regression()  (api.py facade)
        │
        ▼
RegressionOptimizer  (optimizer.py)
  ├── SearchSpaceBuilder   — Tier-aware param space from [OPT:tier] YAML annotations
  ├── WalkForwardValidator — Rolling/expanding train-test splits with purge gap
  └── BENCHMARK_REGISTRY   — 5-tier scoring pipeline
        ├── direction_accuracy      Tier 1 (20%)
        ├── band_calibration        Tier 2 (35%)
        ├── residual_quality        Tier 3 (GATE)
    ├── confidence_correlation  Tier 4 (confidence-return CONSTRAINT)
        └── strategy_utility        Tier 5 (35%)
```

## Usage

### One-Call Facade

```python
from app.regression.api import optimize_regression

result = optimize_regression(
    df,                     # OHLCV DataFrame
    asset="BTCUSDT",
    timeframe="1h",
    n_trials=200,           # Optuna trials
    timeout=3600,           # 1 hour max
)

print(result.best_params)       # Dict of optimized params
print(result.best_score)        # Composite score
print(result.benchmarks)        # RegressionBenchmarkResults
```

### Custom Config

```python
from app.regression.optimization.models import (
    RegressionOptimizationConfig,
    RegressionOptimizationWeights,
)

config = RegressionOptimizationConfig(
    n_trials=300,
    n_folds=5,
    walk_forward_mode="expanding",
    sampler="cma-es",
    weights=RegressionOptimizationWeights(
        direction_accuracy=0.50,   # Override tier 1 weight
        band_calibration=0.20,
        strategy_utility=0.30,
    ),
)

result = optimize_regression(df, config=config)
```

### Saving Results

```python
result.save("app/regression/optimization/results/btcusdt_1h.json")
# Path validation: must be under optimization/results/
```

## Walk-Forward Cross-Validation

`WalkForwardValidator` generates time-series-aware train/test splits.

### Modes

| Mode | Behavior |
|-|-|
| `rolling` | Fixed-size training window slides forward |
| `expanding` | Training window grows from start |

### Parameters

| Param | Default | Description |
|-|-|-|
| `n_folds` | 5 | Number of CV folds |
| `min_train_bars` | 2160 | Minimum training window (bars) |
| `test_fraction` | 0.2 | Fraction of data per test fold |
| `purge_gap` | 10 | Bars between train/test to prevent leakage |
| `mode` | "rolling" | "rolling" or "expanding" |

### Example Splits (Rolling, 5-fold)

```
Fold 1: [===TRAIN===]--gap--[TEST]
Fold 2:    [===TRAIN===]--gap--[TEST]
Fold 3:       [===TRAIN===]--gap--[TEST]
Fold 4:          [===TRAIN===]--gap--[TEST]
Fold 5:             [===TRAIN===]--gap--[TEST]
```

## 5-Tier Benchmark Scoring

Each trial runs the pipeline on every fold, then scores results through 5 tiers:

### Tier 1: Direction Accuracy (20% weight)

**Module**: `benchmarks/direction_accuracy.py`

Measures whether the regression slope correctly predicts price direction over multiple forward horizons. The live defaults are 4, 12, and 24 bars, and the score is a weighted directional agreement across those horizons.

- Range: [0.0, 1.0]
- Score of 0.5 = random, 1.0 = perfect direction prediction
- Down-weighted from 0.40 → 0.20: empirical 1h hit rate is sub-50%, so raw directional accuracy is not the signal's primary strength

### Tier 2: Band Calibration (35% weight)

**Module**: `benchmarks/band_calibration.py`

Evaluates uncertainty band quality via:
1. **Coverage score**: Fraction of prices inside bands, scored as tent function centered on target coverage
2. **Width stability**: Inverse of band width coefficient of variation (narrower + stable = better)

Final score = 0.7 × coverage_score + 0.3 × width_stability.

### Tier 3: Residual Quality (GATE)

**Module**: `benchmarks/residual_quality.py`

Durbin-Watson test on first-differenced residuals. Checks for autocorrelation.

- Score: DW statistic normalized to [0, 1]
- **GATE behavior**: If score < `residual_quality_gate` (default 0.3), the entire trial score is penalized by 50%
- Does NOT contribute to weighted score — it's a pass/fail quality gate

### Tier 4: Confidence Correlation (CONSTRAINT)

**Module**: `benchmarks/confidence_correlation.py`

Spearman rank correlation between confidence scores and absolute forward returns.

- Score: raw Spearman rho between confidence and move magnitude
- **CONSTRAINT behavior**: If score < `min_confidence_rho` (default 0.01), the trial gets a `-confidence_constraint_penalty` penalty (default 0.3)
- Does NOT contribute to weighted score — it's a soft constraint

### Tier 5: Strategy Utility (35% weight)

**Module**: `benchmarks/strategy_utility.py`

Confidence-weighted Sharpe ratio proxy:
1. Compute confidence-weighted returns: `confidence × sign(direction) × realized return`
2. Calculate Sharpe ratio of the weighted returns
3. Compare it with buy-and-hold Sharpe and include both `confidence_sharpe` and `sharpe_improvement`

Up-weighted from 0.20 → 0.35: this is the metric downstream consumers actually use (confidence-scaled position sizing). Quant-lens audit found confidence is a move-magnitude estimator (Spearman rho ~0.15–0.18 with |fwd move|), so strategy utility better captures the signal's real value than raw direction accuracy.

### Composite Score Formula

```
raw_score = 0.20 × direction_accuracy
          + 0.25 × band_coverage_score
          + 0.10 × band_width_stability_score
          + 0.20 × sharpe_improvement_score
          + 0.15 × confidence_sharpe_score

penalties:
    residual gate applies multiplicatively
    confidence constraint applies multiplicatively

final_score = raw_score × gate_multiplier × constraint_multiplier
```

**Rationale (2026-04 quant-lens audit):** Confidence is R²-derived in-sample fit quality, not a calibrated forward probability. 1h directional hit rate was sub-50%, while confidence shows useful Spearman rho (~0.15–0.18) with absolute forward moves. Weights were rebalanced to prioritize strategy utility (confidence_sharpe + sharpe_improvement) and band calibration over raw direction accuracy.

## Search Space

`SearchSpaceBuilder` reads `OrchestratorConfig.optimization` to determine which params are tunable:

```python
optimization:
  global_tunable:
    - trend_atr_fraction        # float [0.02, 0.30]
    - spread_atr_fraction       # float [0.05, 0.40]
    - momentum_atr_fraction     # float [0.02, 0.30]
    - neutral_slope_atr_fraction # float [0.01, 0.15]
        - band_multiplier           # float [1.5, 3.0]
  per_tf_tunable:
    - window_size              # int [30, 300]
    - methods.theil_sen.weight # float [0.1, 3.0]
    - methods.vwr.weight       # float [0.1, 3.0]
    - slope_acceleration_alpha # float [0.01, 0.30]
```

## Optuna Samplers

| Sampler | When to Use |
|-|-|
| `tpe` (default) | General purpose, good for mixed param types |
| `cma-es` | Pure continuous params, high-dimensional |
| `random` | Baseline/sanity check |

## CLI Usage

Two scripts in `app/regression/scripts/` provide command-line access to the optimizer.

### Running Optimization

```bash
# Date-range run with single-threaded BLAS (recommended for reproducibility)
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regression/scripts/run_optimization.py \
    --asset ETHUSDT --timeframe 1h \
    --start-date 2022-01-01 --end-date 2026-03-01 \
    --n-trials 50 --timeout 600 --n-jobs 1

# Lookback-based (90 days from today)
python app/regression/scripts/run_optimization.py --asset BTCUSDT --timeframe 1h

# Custom: 4h, CMA-ES sampler, 200 trials, 2h timeout, 180-day lookback
python app/regression/scripts/run_optimization.py \
    -a ETHUSDT -t 4h --n-trials 200 --timeout 7200 --sampler cma-es --lookback 180

# With explicit YAML config
python app/regression/scripts/run_optimization.py --config config/regression.yaml --n-trials 50

# Quick test (quiet mode, smaller output)
python app/regression/scripts/run_optimization.py --n-trials 5 --timeout 60 --quiet --no-trial-history

# Faster run: fewer folds (larger step) + smaller training window
OMP_NUM_THREADS=1 python app/regression/scripts/run_optimization.py \
    -a BTCUSDT -t 1h --start-date 2022-01-01 --end-date 2026-03-01 \
    --n-trials 200 --step-bars 2160 --train-bars 2160
```

**Flags:**

| Flag | Default | Description |
|-|-|-|
| `-a, --asset` | `BTCUSDT` | Trading pair |
| `-t, --timeframe` | `1h` | Timeframe |
| `--n-trials` | `100` | Number of Optuna trials |
| `--timeout` | `3600` | Max time in seconds |
| `--start-date` | None | Start date `YYYY-MM-DD` (overrides `--lookback`) |
| `--end-date` | None | End date `YYYY-MM-DD` (defaults to today if `--start-date` set) |
| `-l, --lookback` | `90` | Lookback days from today (ignored if `--start-date` set) |
| `--config` | None | Path to regression YAML |
| `--sampler` | `tpe` | `tpe`, `cma-es`, or `random` |
| `--n-jobs` | `1` | Parallel Optuna jobs |
| `--output` | auto | Explicit output path |
| `--no-trial-history` | off | Omit per-trial data (smaller JSON) |
| `--log-interval` | `10` | Print progress every N trials |
| `--quiet` | off | Suppress output |
| `--step-bars` | `720` | Walk-forward step size. Larger = fewer folds = faster |
| `--train-bars` | `4320` | Training window size. Smaller = faster per fold |
| `--apply` | off | Write best params back to YAML config (Tier 4: `assets.<asset>.timeframes.<tf>`) |
| `--dry-run` | off | Preview YAML diff without writing (use with `--apply`) |
| `--weights` | None | Override tier weights: 5-6 comma-separated floats (dir,band,width,sharpe,conf_sharpe[,turnover_penalty]). First 5 must sum to ~1.0 |

> **Performance tuning:** With default `step_bars=720` (1 month of 1h bars), a 4-year date range produces ~44 folds per trial.
> Use `--step-bars 2160` (3 months) to reduce to ~15 folds.
> Bad trials are auto-pruned after 2-3 folds by Optuna's median pruner.

Results are auto-saved to `optimization/results/{asset}_{timeframe}_{timestamp}.json`.

### Monitoring Results

```bash
# Show a result file
python app/regression/scripts/monitor_optimization.py show \
    app/regression/optimization/results/BTCUSDT_1h_20260414_120000.json

# List all result files (sorted by time, score, or asset)
python app/regression/scripts/monitor_optimization.py list
python app/regression/scripts/monitor_optimization.py list --sort score

# Watch a running optimization (polls file every 5s)
python app/regression/scripts/monitor_optimization.py watch \
    app/regression/optimization/results/BTCUSDT_1h_20260414_120000.json --interval 3

# Compare two runs side-by-side
python app/regression/scripts/monitor_optimization.py compare run_a.json run_b.json
```

**Subcommands:**

| Command | Description |
|-|-|
| `show <path>` | Detailed view: benchmarks, params, config |
| `list` | Table of all results with score, trials, gate rate |
| `watch <path>` | Poll file for changes during a live run |
| `compare <a> <b>` | Side-by-side diff of scores, benchmarks, params |

### Typical Workflow

```bash
# Terminal 1: start optimization with date range
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regression/scripts/run_optimization.py \
    -a BTCUSDT -t 1h --start-date 2022-01-01 --end-date 2026-03-01 --n-trials 200

# Terminal 2: monitor progress
python app/regression/scripts/monitor_optimization.py watch \
    app/regression/optimization/results/BTCUSDT_1h_*.json

# After completion: inspect
python app/regression/scripts/monitor_optimization.py show \
    app/regression/optimization/results/BTCUSDT_1h_20260414_120000.json

# Compare with previous run
python app/regression/scripts/monitor_optimization.py compare \
    app/regression/optimization/results/BTCUSDT_1h_20260410.json \
    app/regression/optimization/results/BTCUSDT_1h_20260414.json
```

## Data Models

### `RegressionOptimizationConfig`

Core optimization settings — search bounds, CV, sampler choice.

### `RegressionOptimizationResult`

Complete optimization output:
- `best_params`: Dict of optimized parameters
- `best_score`: Best composite score achieved
- `benchmarks`: `RegressionBenchmarkResults` for best trial
- `trials`: List of all `RegressionTrialResult`
- `save(path)` / `load(path)`: JSON serialization with path validation
- `apply_to_yaml(yaml_path, asset?, timeframe?)`: Write `best_params` into Tier 4 of the YAML config. Uses `ruamel.yaml` for comment preservation (falls back to `pyyaml`). Params are written to `assets.<asset>.timeframes.<timeframe>` path.

### `RegressionBenchmarkResults`

Per-trial benchmark breakdown:
- `direction_accuracy`, `band_calibration`, `residual_quality`
- `confidence_correlation`, `strategy_utility`
- `composite_score`

## YAML Write-Back (`apply_to_yaml`)

Optimized params can be written back to the regression YAML config automatically:

### Programmatic

```python
result = optimize_regression(df, asset="BTCUSDT", timeframe="1h", n_trials=100)
result.apply_to_yaml("app/regression/config/regression.yaml")
# Writes best_params into assets.BTCUSDT.timeframes.1h
```

### CLI

```bash
python app/regression/scripts/run_optimization.py \
    -a BTCUSDT -t 1h --n-trials 100 --apply
# Runs optimization, then writes best params to default regression.yaml

python app/regression/scripts/run_optimization.py \
    -a ETHUSDT -t 4h --n-trials 200 --apply --config custom.yaml
# Writes to custom.yaml instead
```

### How It Works

1. Loads the YAML with `ruamel.yaml` (preserves comments and structure) or falls back to `pyyaml`
2. Navigates to `assets.<asset>.timeframes.<timeframe>` (Tier 4 overrides)
3. Creates the path if it doesn't exist
4. Creates a `.bak` backup of the original file (unless `backup=False`)
5. Validates params against search bounds (logs warnings for out-of-bounds)
6. Merges optimized params into that section
7. Writes the file back

## IC Decay Diagnostic

`app/regression/scripts/ic_decay.py` computes the Information Coefficient (Spearman rho) between confidence and absolute forward returns at multiple horizons, characterizing the signal's half-life.

### Usage

```bash
# Default: BTC/ETH/SOL, 1h+4h, horizons 1/4/12/24/48
python app/regression/scripts/ic_decay.py

# Custom assets and horizons
python app/regression/scripts/ic_decay.py --assets BTCUSDT,ETHUSDT --horizons 1,4,12,24,48,96

# With regime-family split
python app/regression/scripts/ic_decay.py --regime-split
```

### Flags

| Flag | Default | Description |
|-|-|-|
| `--assets` | `BTCUSDT,ETHUSDT,SOLUSDT` | Comma-separated asset list |
| `--timeframes` | `1h,4h` | Comma-separated timeframes |
| `--horizons` | `1,4,12,24,48` | Forward horizons in bars |
| `--config` | default YAML | Path to regression YAML config |
| `--regime-split` | off | Also compute per-regime-family IC curves |

### Interpreting Results

The output table shows `(asset, timeframe, horizon, rho, p_value, top_quintile_move_ratio)` for each combination.

- **Peak rho horizon**: The horizon where confidence has the strongest rank correlation with |forward move|. This is the signal's natural time scale.
- **Top/bottom quintile ratio**: How much larger the average absolute move is in the top confidence quintile vs the bottom. Values above 1.3x suggest useful move-magnitude discrimination.
- **Decay shape**: If rho drops sharply after the peak, the signal has a short half-life. If it decays slowly, the signal has persistence.

Use these results to:
1. Set optimizer direction accuracy horizons to match peak IC
2. Identify assets where confidence is stronger or weaker
3. Determine whether the signal is better suited for short-term or medium-term strategies
