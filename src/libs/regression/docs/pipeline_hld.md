# Regression v2 — High-Level Design

## 1. System Boundary

```
                                ┌─────────────────────────────────┐
                                │        External Consumers       │
                                │  strategy/regime_regression.py  │
                                │  cross_sectional/orchestrator   │
                                │  backtest/features/regime_reg   │
                                └───────────┬─────────────────────┘
                                            │
                              ┌─────────────▼──────────────┐
                              │   api.py  |  compat.py     │  Public surface
                              └─────────────┬──────────────┘
                                            │
                   ┌────────────────────────▼────────────────────────┐
                   │              UniverseOrchestrator               │
                   │  (batch N-asset, MTF cascade, alignment score)  │
                   └────────┬───────────────────────────┬───────────┘
                            │                           │
              ┌─────────────▼──────────┐   ┌───────────▼───────────┐
              │   ConfigResolver       │   │    StateManager        │
              │   4-tier YAML          │   │    (stateless default) │
              └─────────────┬──────────┘   └───────────┬───────────┘
                            │                          │
                   ┌────────▼──────────────────────────▼────────┐
                   │            RegressionPipeline               │
                   │  Features -> Methods -> Uncertainty ->      │
                   │  Ensemble                                   │
                   └────────────────────┬───────────────────────┘
                                        │
                            ┌───────────▼──────────────┐
                            │     RegressionResult     │
                            │  (slope, bands, state)   │
                            └──────────────────────────┘
```

## 2. Config Architecture (4-Tier Resolution)

The config system resolves parameters for any (asset, timeframe) pair via 4 cascading tiers:

**Tier 1 — Global (`GlobalConfig`)**: Default features, methods, ensemble, uncertainty, ATR fractions, window bounds. Applies to everything.

**Tier 2 — Per-Timeframe (`TimeframeConfig`)**: Override window_size, ATR fractions, methods, ensemble per timeframe (e.g., "4h" uses larger window).

**Tier 3 — Per-Asset-Class (`AssetClassConfig`)**: Override volume_profile (CONTINUOUS/SESSION/PROXY), session gap handling, method choices by asset class.

**Tier 4 — Per-Asset (`AssetConfig`)**: Override anything per specific asset. Supports nested per-asset-per-timeframe overrides via `AssetTimeframeConfig`.

### Resolution Flow

```python
ConfigResolver(OrchestratorConfig).resolve("BTCUSDT", "1h")
# 1. Start with GlobalConfig defaults
# 2. Overlay TimeframeConfig["1h"] — non-None fields win
# 3. Look up AssetConfig["BTCUSDT"].asset_class → AssetClassConfig["crypto"]
# 4. Overlay AssetConfig["BTCUSDT"] → AssetConfig["BTCUSDT"].timeframes["1h"]
# → ResolvedPipelineConfig (flat, fully resolved, immutable)
```

### YAML Config (`config/regression.yaml`)

The YAML file uses `[OPT:tier]` annotations on comments to declare which parameters are optimizer-tunable:

```yaml
global:
  default_window_size: 100          # [OPT:per_tf] Search: 30-300
  trend_atr_fraction: 0.10          # [OPT:global] Search: 0.02-0.30
  methods:
    theil_sen:
      weight: 1.0                   # [OPT:per_tf]
```

The `SearchSpaceBuilder` reads these annotations to construct Optuna search spaces scoped to the correct tier.

## 3. Pipeline Architecture

`RegressionPipeline` processes a single (asset, timeframe) request through 4 sequential stages:

### Stage 1: Feature Extraction

Extracts weighted feature arrays from OHLCV data. Each enabled feature extractor contributes an array + confidence weight. In series mode, the pipeline extracts the raw columns once and passes exact NumPy window views into Stage 1 so feature logic stays window-local without repeated DataFrame slicing.

| Plugin | Description |
|-|-|
| `log_price` | Log-transformed close prices with NaN/zero guards |
| `volume_weighted` | Volume transforms (sqrt/log/linear) + window-local percentile clipping |
| `session_aware` | Session gap handling for stocks/fx |

### Stage 2: Regression Methods

Each method receives features and produces slope, intercept, residuals, confidence.

| Plugin | Description | Stateful |
|-|-|-|
| `theil_sen` | Numba-accelerated volume-weighted Theil-Sen. Uses Temporal Anchoring (most recent 25% window) and Volatility Gating for deterministic $O(N^2)$ subsampling. | No |
| `wls` | Weighted Least Squares | No |

### Stage 3: Uncertainty Quantification

Wraps each method result with upper/lower bands.

| Plugin | Description |
|-|-|
| `percentile_bands` | MAD bands in log space; width is driven by `band_multiplier` |

### Stage 4: Ensemble

Blends N method results into a single consensus.

| Plugin | Description | Stateful |
|-|-|-|
| `simple_weighted` | Static weight × confidence blending | No |
| `confidence_weighted` | MoE: pure confidence-based voting power | No |

## 4. Multi-Timeframe Cascade

`UniverseOrchestrator._run_mtf_cascade()` processes timeframes in descending order:

```
4h → 1h → 30m
```

1. Highest TF computes normally (no cascade context)
2. Each subsequent TF receives the prior TF's result as `CascadeContext`
3. `CascadeContext` carries parent slope, confidence, and regime to child TF
4. Final `MTFOutput` includes per-TF results + weighted alignment score

Alignment score formula:
```
score = Σ (tf_weight × direction_agreement)
```

## 5. Universe Orchestration

`compute_universe()` processes N assets with M timeframes each:

```python
universe_data = {
    "BTCUSDT": {"4h": df, "1h": df},
    "ETHUSDT": {"1h": df},
}
result: UniverseResult = compute_universe(universe_data, resolver)
```

`UniverseResult` contains:

- `results`: dominant `RegressionResult` per asset
- `mtf_results`: `MTFOutput` per asset for assets that ran an MTF cascade
- processing stats such as timing, degraded count, and failed count

## 6. State Management

Three implementations of `StateManager` ABC:

| Impl | Persistence | Use Case |
|-|-|-|
| `NullStateManager` | None | Default, stateless processing |
| `InMemoryStateManager` | In-process dict | Testing, single-session |
| `RedisStateManager` | Redis | Production, cross-process |

State is keyed by `{plugin}:{asset}:{timeframe}`. Currently no production plugins require stateful persistence (Kalman and Dynamic MoE were removed as dead code).

## 7. Export Layer

The dedicated payload export layer has been removed from the v2 runtime. Downstream consumers should read structured fields directly from `RegressionResult` instead of relying on `result.metadata` export payloads.

## 8. Degradation Handling

Pipeline gracefully degrades when methods fail:

| Level | Meaning |
|-|-|
| `FULL` | All active stages produced a normal result |
| `PARTIAL` | Some components degraded but the result is still usable |
| `FALLBACK` | Primary path failed and fallback handling was used |
| `FAILED` | The pipeline could not produce a valid result |

`RegressionResult.degradation` reports the level. Consumers should check this before trusting signals.

## 9. Provenance

Every `RegressionResult` carries:

- `config_hash`: hash of the resolved config
- `asset`, `timeframe`: what was computed
- `timestamp`: when the result was produced

Trade payloads are not emitted by the core pipeline. Downstream consumers build
execution signals from structured result fields.

## 10. Optimization V2 — Multi-Objective MOTPE Pipeline

### 10.1 Overview

`optimization/` is a fully self-contained hyperparameter optimization module that uses
**Multi-Objective Tree-structured Parzen Estimator (MOTPE)** to search the regression pipeline's
parameter space. It replaces the V1 single-objective weighted-composite optimizer with a
3-objective Pareto search, 3-way walk-forward cross-validation, and a 5-tier benchmark suite.

```
┌──────────────────────────────────────────────────────────────────┐
│                  run_optimization.py  (CLI)                      │
│  --asset BTCUSDT --timeframe 1h --n-trials 200 --seed 42        │
└───────────┬──────────────────────────────────┬───────────────────┘
            │                                  │
  ┌─────────▼──────────┐            ┌──────────▼──────────┐
  │  BinanceConnector   │            │  ConfigResolver     │
  │  (paginated fetch)  │            │  (4-tier YAML)      │
  └─────────┬──────────┘            └──────────┬──────────┘
            │                                  │
            └──────────────┬───────────────────┘
                           │
              ┌────────────▼────────────────────────┐
              │   RegressionMOTPEOptimizer           │
              │   ┌────────────────────────────┐     │
              │   │  TPESampler (seed=42)      │     │
              │   │  3-way WalkForwardValidator│     │
              │   │  SearchSpaceBuilder        │     │
              │   │  5-tier BenchmarkSuite     │     │
              │   │  MetaFilterSelector        │     │
              │   │  ConvergenceCallback       │     │
              │   └────────────────────────────┘     │
              └────────────┬────────────────────────┘
                           │
              ┌────────────▼────────────────────────┐
              │   RegressionOptimizationResult       │
              │   best_objective_values: (3-tuple)   │
              │   best_params, best_benchmarks       │
              │   pareto_candidates, all_trials       │
              └─────────────────────────────────────┘
```

### 10.2 Algorithm: MOTPE (Multi-Objective TPE)

**Why MOTPE over single-objective TPE:**
- V1 collapsed 6 benchmark scores into one weighted scalar → fragile, weight-sensitive, Pareto-blind
- MOTPE maintains 3 independent objectives → discovers the Pareto front → picks the best trade-off

**How MOTPE works:**
1. For each objective, TPE builds two density models: $\ell(x)$ for "good" trials and $g(x)$ for "bad" trials
2. Suggests params that maximize $\ell(x) / g(x)$ simultaneously across all objectives
3. Multi-objective extension uses Non-dominated Sorting to split trials into "good" (Pareto-dominated) vs "bad"

**Optuna integration:**
```python
# Optuna 4.x: TPESampler auto-selects MOTPE for multi-objective studies
sampler = optuna.samplers.TPESampler(seed=config.seed)
study = optuna.create_study(
    directions=["maximize", "maximize", "maximize"],
    sampler=sampler,
)
```

**Early stopping:** `_ConvergenceCallback` monitors the Pareto front size. If no new Pareto-optimal trials
appear for 50 consecutive trials, the study stops early.

### 10.3 Three Objectives

| # | Objective | Source Benchmark | Direction |
|-|-|-|-|
| 1 | `weighted_direction_score` | Direction Accuracy (Tier 1) | maximize |
| 2 | `band_coverage_pct` | Band Calibration (Tier 2) | maximize |
| 3 | `confidence_sharpe` | Strategy Utility (Tier 5) | maximize |

These three are **non-redundant** — improving one does not automatically improve the others.

### 10.4 Walk-Forward Cross-Validation (3-Way Split)

Each dataset is split into rolling folds with strict temporal ordering and purge gaps:

```
│◀── Train ──▶│ P │◀── Validate ──▶│ P │◀── Test ──▶│
              ↑                     ↑
           purge_bars            purge_bars
```

| Parameter | Default | Meaning |
|-|-|-|
| `train_bars` | 4320 | 6 months of 1h bars |
| `validate_bars` | 720 | 1 month |
| `test_bars` | 720 | 1 month |
| `step_bars` | 720 | Fold step (1 month) |
| `purge_bars` | 24 | 1 day gap to prevent leakage |
| `min_train_bars` | 2160 | 3-month minimum train size |
| `max_train_ratio` | 0.6 | Cap train at 60% of data |

**Two modes:**
- **Fixed window** (default): Train window stays at `train_bars`. Folds slide forward by `step_bars`.
- **Expanding window** (`--expanding-window`): Train start stays at bar 0, grows each fold.

**Optimization uses Validate fold; final evaluation uses Test fold.** This prevents the optimizer
from overfitting to its own scoring data.

**Fold aggregation:** Per-fold scores are aggregated via **10th-percentile** (worst-case stabilization).
This prevents the optimizer from cherry-picking folds where the pipeline happens to score well.

### 10.5 Five-Tier Benchmark Suite

All benchmarks receive pre-extracted arrays from `_common.extract_result_arrays()` (single extraction per fold).

#### Tier 1 — Direction Accuracy (Objective 1)

Measures whether the predicted slope correctly forecasts the sign of forward returns at multiple horizons.

| Horizon | Weight |
|-|-|
| 4-bar | 0.50 |
| 12-bar | 0.30 |
| 24-bar | 0.20 |

$$\text{weighted\_direction\_score} = \sum_h w_h \cdot \frac{1}{N} \sum_i \mathbf{1}[\text{sign}(\hat{s}_i) = \text{sign}(\Delta p_{i+h})]$$

#### Tier 2 — Band Calibration (Objective 2)

Measures how well the predicted upper/lower bands contain actual price movement.

- `band_coverage_pct`: Fraction of bars where close is within [lower, upper]
- `band_width_stability`: $1 - \text{CV}(\text{band\_width})$ — penalizes erratic band widths
- Score: $\max(0, 1 - |coverage - 0.95| / 0.95)$ — targets 95% coverage (2-sigma Gaussian)

#### Tier 3 — Residual Quality (GATE)

**Not an objective — acts as a hard gate.** Trials failing this gate are pruned.

- Durbin-Watson statistic on regression residuals
- Threshold: `min_durbin_watson ≥ 0.5`
- DW < 0.5 indicates severe positive autocorrelation → the regression is not capturing the signal

#### Tier 4 — Confidence Correlation (CONSTRAINT)

**Not an objective — acts as a soft constraint.** Trials failing are penalized during fold counting.

- Spearman $\rho$ between predicted confidence and |forward returns| over 12-bar horizon
- Threshold: `min_confidence_rho ≥ 0.01`
- Ensures the pipeline's confidence output has predictive value

#### Tier 5 — Strategy Utility (Objective 3)

Simulates a confidence-weighted strategy vs buy-and-hold:

$$\text{sharpe\_improvement} = \text{confidence\_sharpe} - \text{bah\_sharpe}$$

- **Confidence Sharpe**: Annualized Sharpe of a strategy that sizes positions by confidence magnitude
- **Max Drawdown**: Computed on the equity curve $e^{\sum \log(1 + r_t)}$, using percentage drawdown from running max
- Annualization factor sourced from `BARS_PER_YEAR[timeframe]` (e.g., 8760 for 1h)

### 10.6 Search Space

The `SearchSpaceBuilder` reads `[OPT:tier]` annotations from the YAML config and constructs Optuna suggest calls:

| Parameter | Range | Type |
|-|-|-|
| `window_size` | 30 – 200 | int |
| `band_multiplier` | 1.5 – 4.0 | float |
| `trend_atr_fraction` | 0.05 – 0.20 | float |
| `spread_atr_fraction` | 0.08 – 0.25 | float |
| `momentum_atr_fraction` | 0.05 – 0.20 | float |
| `neutral_slope_atr_fraction` | 0.02 – 0.08 | float |
| `slope_acceleration_alpha` | 0.0 – 0.5 | float |
| `methods.theil_sen.weight` | 0.2 – 2.0 | float |
| `methods.vwr.weight` | 0.2 – 2.0 | float |

The `ensemble.params.*` parameters are added dynamically from the resolved config.

### 10.7 Meta-Filter (Pareto Tie-Breaking)

After MOTPE produces a Pareto front (typically 5–30 trials), a single winner must be selected.
`MetaFilterSelector` picks the trial with the best value on an **orthogonal metric** not used
as any of the 3 objectives.

Default: `max_drawdown` (minimized) — selects the Pareto-optimal trial with the smallest drawdown.

The metric name is validated against `RegressionBenchmarkResults.__dataclass_fields__` at construction
to prevent silent typos.

### 10.8 Pipeline Factory & Param Overlay

The optimizer doesn't import pipeline internals. Instead, `run_optimization.py` builds a
`pipeline_factory` callable:

```python
def pipeline_factory(params: dict, asset: str, timeframe: str) -> (pipeline, config):
    base_config = resolver.resolve(asset, timeframe)
    # Overlay trial params onto frozen config (methods.X.weight, ensemble.params.Y, etc.)
    config = replace(base_config, **overrides)
    pipeline = RegressionPipeline(config, NullStateManager())
    return pipeline, config
```

The overlay handles dotted keys: `methods.theil_sen.weight` → modifies the theil_sen PluginConfig weight.

### 10.9 Status File Contract

`StatusFileWriter` writes atomic JSON to `.optimization_status.json` on every trial:

```json
{
  "pid": 12345,
  "asset": "BTCUSDT",
  "timeframe": "1h",
  "status": "running",
  "trial_current": 42,
  "n_trials_target": 200,
  "best_objective_values": [0.583, 0.912, 0.341],
  "best_params": {"window_size": 120, ...},
  "n_trials_passed_gate": 28,
  "n_trials_pruned": 6,
  "start_time": "2026-05-16T10:00:00",
  "last_update": "2026-05-16T10:05:32"
}
```

`monitor_optimization.py` polls this file for its watch dashboard.

### 10.10 CLI Scripts

#### run\_optimization.py

```bash
# Full run: BTCUSDT 1h, 2022-01-01 to 2026-01-01, 200 trials
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regression/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --start-date 2022-01-01 --end-date 2026-01-01 \
    --n-trials 200 --timeout 3600 --seed 42

# Quick test run
python app/regression/scripts/run_optimization.py \
    --n-trials 5 --timeout 60 --quiet --no-trial-history

# With custom V2 YAML config
python app/regression/scripts/run_optimization.py \
    --opt-config app/regression/optimization/config/optimization.yaml
```

| Flag | Default | Description |
|-|-|-|
| `--asset` | BTCUSDT | Trading pair |
| `--timeframe` | 1h | Bar timeframe |
| `--n-trials` | from YAML (200) | Optuna trial count |
| `--timeout` | from YAML (3600) | Timeout in seconds |
| `--seed` | from YAML (42) | MOTPE random seed |
| `--start-date` | — | Explicit start (YYYY-MM-DD) |
| `--end-date` | — | Explicit end (YYYY-MM-DD) |
| `--lookback` | 90 | Days from today (if no --start-date) |
| `--expanding-window` | off | Use expanding train window |
| `--opt-config` | auto-detect | Path to optimization YAML |
| `--config` | auto-detect | Path to regression pipeline YAML |
| `--no-trial-history` | off | Omit per-trial data from JSON |

**Exit code:** 0 if gate pass rate > 10%, else 1.

#### monitor\_optimization.py

```bash
# Show saved result
python app/regression/scripts/monitor_optimization.py show <path.json>

# List all results sorted by Sharpe
python app/regression/scripts/monitor_optimization.py list --sort score

# Watch live progress during a run
python app/regression/scripts/monitor_optimization.py watch --interval 5

# Compare two runs side-by-side
python app/regression/scripts/monitor_optimization.py compare run_a.json run_b.json
```

### 10.11 Module File Map

```
optimization/
├── __init__.py
├── constants.py          # All magic numbers, thresholds, defaults
├── models.py             # RegressionOptimizationConfig, Result, TrialResult, BenchmarkResults
├── optimizer.py          # RegressionMOTPEOptimizer + ConvergenceCallback
├── walk_forward.py       # WalkForwardValidator (3-way split generator)
├── search_space.py       # SearchSpaceBuilder (reads [OPT:tier] YAML annotations)
├── meta_filter.py        # MetaFilterSelector (Pareto tie-breaker)
├── config/
│   └── optimization.yaml   # Runtime-tunable YAML config
├── benchmarks/
│   ├── _common.py              # extract_result_arrays (shared extraction)
│   ├── direction_accuracy.py   # Tier 1 — multi-horizon direction scoring
│   ├── band_calibration.py     # Tier 2 — coverage + width stability
│   ├── residual_quality.py     # Tier 3 — Durbin-Watson gate
│   ├── confidence_correlation.py  # Tier 4 — Spearman constraint
│   └── strategy_utility.py     # Tier 5 — confidence Sharpe + drawdown
├── tests/
│   ├── test_models.py          # 19 tests (config, results, YAML, constants)
│   ├── test_walk_forward.py    # 7 tests (splits, expanding, edge cases)
│   ├── test_search_space.py    # 7 tests (space builder, tier merging)
│   └── test_meta_filter.py     # 6 tests (selection, validation)
└── results/                    # Saved JSON output directory
```

### 10.12 End-to-End Execution Flow

```
1. CLI parses args → build_config() loads YAML + CLI overrides
2. fetch_data() paginated-fetches OHLCV from Binance API
3. build_pipeline_factory() creates (params, asset, tf) → (pipeline, config) callable
4. RegressionMOTPEOptimizer constructed with config + factory
5. optimizer.optimize(df, asset, timeframe):
   a. WalkForwardValidator generates N 3-way folds
   b. SearchSpaceBuilder reads [OPT:tier] annotations → Optuna specs
   c. TPESampler(seed) + study(directions=3×maximize) — auto MOTPE
   d. For each trial:
      i.   Sample params from search space
      ii.  For each fold: fit on Train, score on Validate via 5-tier benchmarks
      iii. If gate/constraint fails on >max_failed_folds: prune trial
      iv.  Aggregate fold scores via 10th-percentile
      v.   Return (dir_score, coverage, sharpe) to Optuna
   e. ConvergenceCallback checks Pareto front stagnation
   f. After all trials: MetaFilter picks best from Pareto front (min drawdown)
   g. Final OOS evaluation on Test folds
6. Result printed + saved to optimization/results/<asset>_<tf>_<timestamp>.json
7. StatusFileWriter marks completed
```

## 11. Dependencies

| Package | Required By |
|-|-|
| `pandas` | All (OHLCV DataFrames) |
| `numpy` | All (numeric operations) |
| `numba` | `theil_sen.py` (JIT-compiled hot loop) |
| `optuna` | `optimization/optimizer.py` (MOTPE HPO) |
| `pyyaml` | `optimization/models.py` (YAML config loading) |
| `pydantic` | `optimization/models.py` (config validation) |
| `scipy` | `scripts/ic_decay.py` (Spearman correlation) |
