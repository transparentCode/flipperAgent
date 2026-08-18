# S/R Optimization — Architecture & Reference

## Overview

The optimization subsystem (`app/sr/optimization/`) tunes the SR pipeline's hyperparameters to maximize zone quality. It operates in two stages:

| Stage | Scope | Objective | Module |
|-|-|-|-|
| 1 — Universe | Shared across all assets | Maximize average zone strength + cross-asset agreement lift | `universe_optimizer.py` |
| 2 — Per-Asset | Per (asset, timeframe) | Maximize zone lifecycle quality (survival, touch accuracy, coverage) with walk-forward validation | `asset_optimizer.py` |

Both stages use the same canonical dotted-parameter identities that match the live `sr.*` config contract, and output into the 4-tier config cascade.

## Module Map

```
app/sr/optimization/
├── __init__.py              # Public exports
├── universe_optimizer.py    # Stage 1: Universe-wide joint optimizer (Optuna)
├── asset_optimizer.py       # Stage 2: Per-asset kernel tuning with walk-forward CV
├── two_stage_optimizer.py   # Orchestrator: Stage 1 → Stage 2 → unified config
├── benchmark_tier6.py       # Cross-asset agreement benchmark
├── multi_bar_runner.py      # Bar-by-bar pipeline execution engine (sliding window)
├── quality_metrics.py       # Zone lifecycle quality metrics + composite scoring
├── data_driven_bounds.py    # Data-adaptive search-space bounds (canonical source)
├── _json_utils.py           # Shared NumpyDatetimeEncoder for result serialization
└── results/                 # Persisted optimization results (JSON)
```

## Optimizer Parameter Surface

### Live Parameters (13 total)

Organized into three categories. All use canonical dotted SR config identities.

#### Shared Universe-Wide (3 params)

These affect all assets and are only tuned in Stage 1.

| Parameter | Default | Bounds | Description |
|-|-|-|-|
| `ensemble.structural_vs_micro_ratio` | 0.50 | [0.40, 0.65] | Structural vs micro kernel weight blend |
| `lifecycle.age_lambda` | 0.002 | [0.0015, 0.0035] | Per-bar zone strength decay rate |
| `cross_asset.sector_cluster_eps_atr` | 0.50 | [0.40, 0.90] | Tier 6 cross-asset clustering radius |

#### Kernel High-Tune (9 params)

Per-kernel strictness knobs. Tuned globally in Stage 1, refined per-asset in Stage 2.

| Parameter | Default | Bounds | Kernel | Description |
|-|-|-|-|-|
| `kernels.volume_poc.hvn_prominence` | 0.20 | [0.10, 0.35] | volume_poc | HVN detection strictness |
| `kernels.fair_value_gap.gap_min_atr` | 0.50 | [0.35, 0.90] | fair_value_gap | Minimum FVG size in ATR |
| `kernels.fair_value_gap.fill_threshold` | 0.50 | [0.35, 0.65] | fair_value_gap | Gap fill strictness |
| `kernels.fair_value_gap.filled_penalty_multiplier` | 0.50 | [0.25, 0.75] | fair_value_gap | Filled-gap discount factor |
| `kernels.order_block.displacement_atr` | 1.50 | [1.00, 2.20] | order_block | Displacement move threshold |
| `kernels.order_block.imbalance_ratio` | 0.70 | [0.55, 0.85] | order_block | Order-block imbalance threshold |
| `kernels.regression_band.band_width_sigma` | 2.00 | [1.50, 2.75] | regression_band | Regression band width in σ |
| `kernels.liquidity_sweep.sweep_lookback` | 50 | [30, 80] | liquidity_sweep | Sweep detection horizon (int) |
| `kernels.liquidity_sweep.max_pierce_atr` | 1.00 | [0.50, 1.40] | liquidity_sweep | Maximum pierce depth in ATR |

#### Metadata-Gated (1 param)

Only active when the universe structurally supports it.

| Parameter | Default | Bounds | Gate | Description |
|-|-|-|-|-|
| `kernels.session_gap.gap_min_atr` | 0.50 | [0.35, 0.90] | `metadata.has_session_gaps == true` | Minimum session gap size |

### What's NOT Optimized (~190 params)

| Category | Count | Reason |
|-|-|-|
| Asset metadata | ~15 | Market-structural (crypto=24/7, equity=gaps, etc.) |
| Rule-derived coefficients | ~28 | Formula inputs, derived from ATR/volatility/volume |
| Scoring weights / formulas | ~30 | Ensemble internals, compositional semantics |
| Safety guardrails | ~15 | `max_age_bars`, `min_strength`, `max_active_zones` |
| Infrastructure / visualization | ~20 | Chart, heatmap, audit settings |
| Fixed kernel defaults | ~80 | Stable across assets (lookback, smoothing, etc.) |

## Stage 1: Universe-Wide Optimizer

### Architecture

```
UniverseSROptimizer
├── Uses: UniverseSRRouter (parallel multi-asset pipeline)
├── Uses: MultiBarRunner (bar-by-bar pipeline execution, eval_bars=300)
├── Uses: ZoneQualityEvaluator (composite quality scoring per asset/tf)
├── Uses: CrossAssetSRAnalyzer (enriches zones with agreement features)
├── Uses: CrossAssetBenchmark (Tier 6 score)
└── Backend: Optuna TPE sampler (seed from config, default 42) or deterministic fallback
```

### Objective Function

```
total_score = avg_quality × (1 - tier6_weight) + cross_asset_score × tier6_weight
```

Where:
- `avg_quality` = mean of per-(asset, tf) `ZoneQualityEvaluator.composite_score()` — the same 5-metric composite used in Stage 2
- `cross_asset_score` = `CrossAssetBenchmarkResult.score` (Tier 6) — only computed when `correlation_matrix` is provided
- `tier6_weight` = 0.10 (default)

#### Per-Asset Quality Evaluation

For each `(asset, tf)` pair in the data map:

1. Build a fresh `SRv2Pipeline` with the trial's suggested parameters
2. Run `MultiBarRunner` over the trailing `eval_bars=300` bars
3. Compute `ZoneQualityEvaluator.composite_score()` on the `MultiBarRunResult`
4. Store in `per_asset_scores["SYMBOL/TF"]` (e.g., `"BTC/1h"`)

This replaced the previous `mean(ScoredLevel.strength)` objective, aligning Stage 1 with Stage 2's lifecycle-based quality signal.

> **Key**: Both stages now optimize the same composite objective, eliminating the mismatch where Stage 1 optimized for raw strength while Stage 2 optimized for lifecycle quality.

### Tier 6: Cross-Asset Benchmark

Measures whether zones with cross-asset agreement outperform isolated zones.

| Metric | Formula |
|-|-|
| `universe_agreement_lift` | `(agreed_bounce_rate - isolated_bounce_rate) / isolated_bounce_rate` |
| `dominant_alignment_lift` | Same formula for dominant-asset-aligned zones |
| `score` | `clamp(lift × 2.0, 0, 1)` — 50% lift → perfect score |

A zone is "agreed" when `universe_agreement_count >= min_agreement` (default 2).

### Key Classes

**`UniverseOptimizationConfig`**

| Field | Type | Default | Description |
|-|-|-|-|
| `n_trials` | int | 50 | Optuna trial count |
| `timeout_s` | float | 3600.0 | Max optimization time (seconds) |
| `tier6_weight` | float | 0.10 | Weight of cross-asset score in objective |
| `parameter_space` | Dict | 13 params | Search space (see above) |

Can be constructed from:
- `from_resolved_config(OptimizationConfig)` — from typed config
- `from_dict(dict)` — from raw YAML

**`UniverseTrialResult`**

| Field | Type | Description |
|-|-|-|
| `trial_number` | int | Optuna trial index |
| `params` | Dict[str, float] | Suggested parameter values |
| `per_asset_scores` | Dict[str, float] | Per-asset average strength |
| `cross_asset_score` | float | Tier 6 score |
| `total_score` | float | Weighted composite |

**`UniverseOptimizationResult`**

| Field | Type | Description |
|-|-|-|
| `best_params` | Dict[str, float] | Best trial parameters |
| `best_score` | float | Best composite score |
| `all_trials` | List[UniverseTrialResult] | Full trial history |
| `tier6_result` | CrossAssetBenchmarkResult | Best trial's cross-asset metrics |
| `assets` | List[str] | Optimized asset symbols |

### Usage

```python
from app.sr.optimization import UniverseSROptimizer
from app.sr.universe.config import UniverseSRConfig

universe_config = UniverseSRConfig(
    assets=[AssetSRConfig(symbol="BTCUSDT"), AssetSRConfig(symbol="ETHUSDT")],
    default_timeframes=["1h"],
    default_enabled_kernels=["pivot_hl", "volume_poc", "order_block", "fair_value_gap"],
)

optimizer = UniverseSROptimizer(universe_config)

# data_map: {asset: {tf: DataFrame}}
result = optimizer.optimize(data_map, correlation_matrix=corr_df)

print(result.best_params)   # {'ensemble.structural_vs_micro_ratio': 0.52, ...}
print(result.best_score)     # 0.734
```

### No-Optuna Fallback

When Optuna is not installed, `optimize()` evaluates the current config defaults as a single deterministic trial and returns those values as the "best" result. The same applies to `evaluate_trial()` which works without Optuna.

### Config Application

`apply_params_to_config(params)` converts flat dotted params to nested dict:

```python
{"kernels.order_block.displacement_atr": 1.8}
→ {"kernels": {"order_block": {"displacement_atr": 1.8}}}
```

This is deep-merged into `UniverseSRConfig.global_config` before building the trial's `UniverseSRRouter`.

## Multi-Bar Pipeline Runner

### Purpose

Runs `SRv2Pipeline.run()` bar-by-bar across a window, collecting all lifecycle events. This provides the temporal quality signal that single-bar snapshot scoring cannot capture.

### Architecture

```
MultiBarRunner
├── Wraps: SRv2Pipeline (stateful — accumulates zones across bars)
├── Input: OHLCV DataFrame + bar range
└── Output: MultiBarRunResult
```

At each bar `i`, the pipeline sees a sliding window of `max_lookback` bars (default 500) ending at bar `i`:

```python
bar_slice = df.iloc[max(0, bar_idx + 1 - max_lookback) : bar_idx + 1]
```

This eliminates the O(n²) memory/copy cost of growing slices from bar 0. The window is large enough to capture all kernel lookback requirements while keeping per-bar cost constant.

### `MultiBarRunResult`

| Field | Type | Description |
|-|-|-|
| `bar_count` | int | Total bars processed |
| `all_events` | List[ZoneLifecycleEvent] | Every lifecycle event emitted |
| `final_zones` | List[ManagedZone] | All zones at end of run |
| `total_zones_created` | int | Distinct zones that appeared |
| `total_touches` | int | Touch events (`touch`, `touch_confirm`) |
| `total_breakouts` | int | Breakout events (`breakout_up`, `breakout_down`) |
| `total_false_breakouts` | int | False breakout events (`price_returned`) |
| `zones_reached_active` | int | Zones that reached ACTIVE state |
| `zones_broken` | int | Zones that were broken |
| `zones_expired` | int | Zones that expired |
| `close_prices` | List[float] | Per-bar close prices |
| `bar_zone_snapshots` | List[List[dict]] | Per-bar active zone positions (center, lower, upper, atr) |

### Event Classification

Lifecycle events are classified during the run into aggregate counters:

| Trigger Pattern | Counter Incremented | Sets Tracked |
|-|-|-|
| `touch`, `touch_confirm` | `total_touches` | — |
| `breakout_*` | `total_breakouts` | `broken_ids` |
| `price_returned` | `total_false_breakouts` | — |
| `to_state == ACTIVE` (first time) | — | `ever_active_ids` |
| `to_state == EXPIRED` | — | `expired_ids` |

### Usage

```python
from app.sr.optimization.multi_bar_runner import MultiBarRunner
from app.sr.pipeline import SRv2Pipeline

pipeline = SRv2Pipeline(config, asset="BTCUSDT", timeframe="1h")
runner = MultiBarRunner(pipeline)

result = runner.run(df, start_bar=20, end_bar=500)
print(result.total_zones_created)   # 47
print(result.total_touches)          # 128
print(result.zones_reached_active)   # 35
```

## Zone Quality Metrics

### Purpose

Evaluates zone lifecycle outcomes from a multi-bar run. Produces 5 normalized [0, 1] metrics and a weighted composite score used as the Stage 2 optimizer objective.

### Metrics

| Metric | Formula | Measures |
|-|-|-|
| `survival_rate` | `zones_reached_active / total_zones_created` | Do detected zones confirm into actionable levels? |
| `touch_accuracy` | `(touches - breakouts) / touches` | Do touches produce bounces (not breakouts)? |
| `false_breakout_rate` | `false_breakouts / breakouts` | How often do breakouts reverse? (lower = better) |
| `strength_stability` | `1 - cv(strength)` across final zones | Are zone strengths consistent or wildly varied? |
| `coverage` | `covered_reversals / total_reversals` | Are significant price reversals happening near zones? |

### Coverage Metric Detail

1. **Find reversals**: Identify bars where price changed direction by at least `reversal_threshold_pct` (default 1.5%)
2. **Check proximity**: A reversal is "covered" if any active zone at that bar is within `coverage_proximity_atr × ATR` (default 0.3) of the reversal price
3. **Score**: `covered / total_reversals`

### Composite Score

```
composite = w_survival × survival_rate
          + w_touch   × touch_accuracy
          + w_fbr     × (1 - false_breakout_rate)    ← inverted
          + w_stab    × strength_stability
          + w_cov     × coverage
```

Default weights:

| Weight | Value | Rationale |
|-|-|-|
| `survival_rate` | 0.25 | Zones must confirm to be useful |
| `touch_accuracy` | 0.30 | Primary trading signal quality |
| `false_breakout_rate` | 0.20 | Reliability of breakout signals |
| `strength_stability` | 0.10 | Consistent scoring aids position sizing |
| `coverage` | 0.15 | Zones should capture key market turning points |

### Key Classes

**`ZoneQualityMetrics`** (frozen dataclass)

All 5 metric values, each in [0, 1].

**`ZoneQualityEvaluator`**

| Method | Description |
|-|-|
| `evaluate(run_result)` | Computes all 5 metrics from `MultiBarRunResult` |
| `composite_score(metrics)` | Weighted composite in [0, 1] |

Constructor accepts optional `weights`, `reversal_threshold_pct`, `coverage_proximity_atr`.

### Usage

```python
from app.sr.optimization.quality_metrics import ZoneQualityEvaluator

evaluator = ZoneQualityEvaluator()
metrics = evaluator.evaluate(run_result)

print(metrics.survival_rate)      # 0.74
print(metrics.touch_accuracy)     # 0.82
print(metrics.false_breakout_rate) # 0.18

score = evaluator.composite_score(metrics)
print(score)  # 0.71
```

## Stage 2: Per-Asset Optimizer

Refines kernel high-tune params per (asset, timeframe) using multi-bar quality score with walk-forward cross-validation.

### Design

Adopted from `app.regression.optimization` cross-module review: walk-forward CV, trial pruning, gate/constraint penalties, result persistence.

| Property | Value |
|-|-|
| Starting point | Stage 1 global best params |
| Search bounds | ±25% of Stage 1 optimum, clamped to original bounds |
| Objective | `composite_score × gate_mult × constraint_mult - regularization_penalty` |
| Walk-forward | Rolling multi-fold CV via the SR-owned `WalkForwardValidator` (`libs.sr.optimization.walk_forward`). Default: `train_bars=300`, `test_bars=100`, `step_bars=100`, `purge_bars=10` |
| Trial pruning | `MedianPruner(n_startup_trials=5, n_warmup_steps=1)` — kills unpromising trials mid-fold |
| Zone count gate | Trials producing < `min_zone_count_gate` (default 3) zones get `score × gate_penalty` (default 0.5) |
| Survival constraint | Trials with `survival_rate < min_survival_rate_constraint` (default 0.20) get soft penalty: `score × (floor + (1 - floor) × survival / min_survival)` where `floor = constraint_penalty_floor` (default 0.50) |
| Regularization | `0.3 × mean(\|param - global\| / bound_range)` |
| Rejection | If `mean_val_score < mean_train_score × (1 - validation_drop_threshold)` across folds, revert to global defaults |
| Min data | 500 bars (≥2 walk-forward folds) |
| Persistence | `AssetOptimizationResult.save()` (JSON, path-validated) + `.apply_to_yaml()` (tier-4, `.bak` backup) |
| Output | Per-asset overrides at `assets.{symbol}.{tf}.*` in config cascade |

### Stage 2 Acceptance Interpretation

`accepted=True` means the Stage 2 validation-drop check passed. It does not always mean a full per-asset search occurred.

| Case | How to identify | Interpretation | Action |
|-|-|-|-|
| Full Stage 2 pass | `accepted=True` and `n_folds >= 2` | Per-asset params validated by walk-forward CV | Safe to keep overrides if audits also pass |
| Stage 2 fallback accepted | `accepted=True`, `fallback_to_global=True`, `n_folds >= 2` | Per-asset search did not beat global robustly | Keep Stage 1 globals for that asset/timeframe |
| Stage 2 no-op accepted | `accepted=True` and `n_folds == 0` | Not enough folds generated, so no effective Stage 2 validation | Treat as Stage 1-only run and require wider audit windows |
| Stage 2 rejected | `accepted=False` | Validation drop too large vs train | Do not apply per-asset overrides |

For daily timeframe runs with limited bars, `n_folds == 0` can occur even when Stage 1 is valid. This is expected behavior, not a runtime error.

### Plateau Robustness Criteria (Optimizer)

Use these checks to decide whether a run is a robust plateau (stable region) versus a fragile peak (overfit point):

| Check | Good plateau signal | Weak signal |
|-|-|-|
| Stage 1 convergence | Best score stabilizes in final 20 to 30 percent of trials | Best score jumps only in last 1 to 2 trials |
| Local sensitivity | Small parameter perturbations keep score within 2 to 4 percent | Minor perturbations collapse score materially |
| Stage 2 validation | Median `val_score / train_score >= 0.80` across assets with folds | Frequent large train-val gaps |
| Stage 2 accept rate | At least 50 percent for multi-asset runs (or justified fallback-to-global) | Very low accept rate without clear data limits |
| Regime transfer | Extended audit window score drop <= 0.03 vs optimization window | Large score decay on older/newer regime |

If at least 4 of the 5 checks are good, classify the run as plateau-robust.

### Cross-Module Reuse from Regression

| Component | Source | How Used in SR |
|-|-|-|
| `WalkForwardValidator` | `libs.sr.optimization.walk_forward` | Rolling CV with purge gap for per-asset fold evaluation |
| Gate/constraint pattern | `app.regression.optimization.optimizer._compute_fold_score` | Zone count gate + survival rate constraint as multiplicative penalties |
| Result persistence | `app.regression.optimization.models.RegressionOptimizationResult` | `save()` with path validation, `apply_to_yaml()` with backup + ruamel.yaml |
| Trial pruning | `app.regression.optimization.optimizer._objective` | `trial.report()` per fold + `MedianPruner` |

### Key Classes

**`AssetOptimizationConfig`** (dataclass)

| Field | Type | Default | Description |
|-|-|-|-|
| `n_trials` | int | 30 | Optuna trial count |
| `timeout_s` | float | 600.0 | Max optimization time (seconds) |
| `sampler` | str | `"tpe"` | Optuna sampler (`tpe`, `cmaes`, `random`) |
| `bound_fraction` | float | 0.25 | ±% of Stage 1 optimum for narrowed bounds |
| `min_bars` | int | 500 | Minimum OHLCV bars to attempt optimization |
| `train_bars` | int | 300 | Walk-forward training window |
| `test_bars` | int | 100 | Walk-forward test window |
| `step_bars` | int | 100 | Walk-forward step size |
| `purge_bars` | int | 10 | Purge gap between train/test |
| `validation_drop_threshold` | float | 0.15 | Max allowed train→val score drop |
| `regularization_weight` | float | 0.3 | Penalty for deviation from global |
| `min_zone_count_gate` | int | 3 | Gate threshold |
| `gate_penalty` | float | 0.5 | Score multiplier when gate fails |
| `min_survival_rate_constraint` | float | 0.20 | Survival floor |
| `constraint_penalty_floor` | float | 0.50 | Minimum multiplier when survival constraint fires |
| `seed` | int | 42 | Optuna sampler seed |
| `quality_reversal_threshold_pct` | float | 0.015 | Reversal detection threshold for coverage metric |
| `quality_coverage_proximity_atr` | float | 0.3 | ATR proximity for coverage |
| `quality_weights` | Dict | 5 weights | Composite score weights (passed to ZoneQualityEvaluator) |

**`AssetOptimizationResult`** (dataclass)

| Field | Type | Description |
|-|-|-|
| `asset` | str | Asset symbol |
| `timeframe` | str | Timeframe |
| `best_params` | Dict[str, float] | Optimized kernel params |
| `train_score` | float | Mean training fold score |
| `val_score` | float | Mean validation fold score |
| `accepted` | bool | Passed validation check |
| `fallback_to_global` | bool | Reverted to Stage 1 defaults |
| `n_folds` | int | Walk-forward fold count |
| `fold_scores` | List[float] | Per-fold scores |
| `gate_failures` | int | Total gate violations |
| `constraint_failures` | int | Total constraint violations |

Methods:
- `save(path)` — JSON persistence (path-validated to `results/` directory)
- `apply_to_yaml(yaml_path)` — Write to tier-4 config with `.bak` backup
- `load(path)` — Reconstruct from saved JSON

### Usage

```python
from app.sr.optimization import AssetSROptimizer, AssetOptimizationConfig

optimizer = AssetSROptimizer(
    asset="BTCUSDT",
    timeframe="1h",
    global_best_params=stage1_result.best_params,
    base_raw_config=raw_config,
    opt_config=AssetOptimizationConfig(n_trials=30),
)

result = optimizer.optimize(df)  # df: OHLCV DataFrame (≥500 bars)

print(result.accepted)       # True
print(result.train_score)    # 0.68
print(result.val_score)      # 0.62
print(result.best_params)    # {'kernels.order_block.displacement_atr': 1.82, ...}

result.save("app/sr/optimization/results/BTCUSDT_1h.json")
result.apply_to_yaml("app/sr/config/sr.yaml")
```

## Two-Stage Orchestrator

### Architecture

```
TwoStageOptimizer
├── Stage 1: UniverseSROptimizer.optimize(data_map, corr_matrix)
│   └── Returns: global_best_params, global_score
├── Stage 2: AssetSROptimizer.optimize(df) × N (asset, tf) pairs
│   └── Returns: per_asset_params, per_asset_results
└── emit_config(result) → unified config dict
```

### Key Classes

**`TwoStageResult`** (dataclass)

| Field | Type | Description |
|-|-|-|
| `global_params` | Dict[str, float] | Stage 1 best params |
| `global_score` | float | Stage 1 best score |
| `per_asset_params` | Dict[str, Dict[str, Dict]] | asset → tf → params |
| `per_asset_results` | List[AssetOptimizationResult] | All Stage 2 results |
| `stage1_result` | UniverseOptimizationResult | Full Stage 1 output |
| `metadata` | Dict | Timing, counts, skipped assets |

Methods:
- `save(path)` — JSON persistence (path-validated)
- `apply_to_yaml(yaml_path)` — Stage 1 → `sr.*`, Stage 2 → `assets.{sym}.{tf}.*`, `.bak` backup

**`TwoStageOptimizer`**

| Method | Description |
|-|-|
| `optimize(data_map, correlation_matrix)` | Run Stage 1 then Stage 2 per (asset, tf) |
| `emit_config(result)` | Build unified config dict for YAML output |

`emit_config()` uses `defaults.*` when all TFs for an asset share identical params, otherwise `{tf}.*` per-timeframe.

### Usage

```python
from app.sr.optimization import TwoStageOptimizer
from app.sr.optimization.asset_optimizer import AssetOptimizationConfig
from app.sr.universe.config import UniverseSRConfig

optimizer = TwoStageOptimizer(
    universe_config=UniverseSRConfig(...),
    stage2_config=AssetOptimizationConfig(n_trials=30, min_bars=500),
)

result = optimizer.optimize(data_map, correlation_matrix=corr_df)

print(result.global_score)                    # 0.73
print(len(result.per_asset_results))          # 5
print(result.metadata["stage2_assets_accepted"])  # 4

# Emit to YAML
config = optimizer.emit_config(result)
result.apply_to_yaml("app/sr/config/sr.yaml")
```

### Two-Stage Flow

```
┌─────────────────────────────────────┐
│ Stage 1: UniverseSROptimizer        │
│   - Runs all assets × TFs jointly   │
│   - Optimizes 13 shared params      │
│   - Includes Tier 6 cross-asset     │
│   - Output: global best params      │
└───────────────┬─────────────────────┘
                │ global_best_params
                ▼
┌─────────────────────────────────────┐
│ Stage 2: AssetSROptimizer (× N)     │
│   - Per (asset, tf) independently   │
│   - Optimizes 10 kernel params      │
│   - Walk-forward CV (multi-fold)    │
│   - Pruned, gated, regularized      │
│   - Output: per-asset overrides     │
└───────────────┬─────────────────────┘
                │ per_asset_params
                ▼
┌─────────────────────────────────────┐
│ TwoStageOptimizer.emit_config()     │
│   - Stage 1 → sr.* (tiers 1-2)     │
│   - Stage 2 → assets.{sym}.{tf}.*  │
│   - save() + apply_to_yaml()       │
└─────────────────────────────────────┘
```

## Config Integration

Optimizer outputs map directly to the 4-tier config cascade:

| Optimizer Stage | Config Tier | YAML Path | Example |
|-|-|-|-|
| Stage 1 global | Tier 2 (global) | `sr.kernels.order_block.displacement_atr` | 1.8 |
| Stage 2 per-TF | Tier 3 (per-TF) | `per_tf.4h.kernels.order_block.displacement_atr` | 2.1 |
| Stage 2 per-asset | Tier 4 (per-asset) | `assets.BTCUSDT.1h.kernels.order_block.displacement_atr` | 1.6 |

The `SRConfigResolver` cascade resolves these with highest-tier winning, so per-asset values override per-TF, which override global.

## Config Schema

Stage 2 config fields live under `sr.optimization` alongside Stage 1 fields:

```yaml
sr:
  optimization:
    # Stage 1
    n_trials: 50
    timeout_s: 3600.0
    tier6_weight: 0.10
    parameters: { ... }

    # Stage 2 (per-asset)
    per_asset_n_trials: 30
    per_asset_timeout_s: 600.0
    per_asset_bound_fraction: 0.25
    per_asset_regularization_weight: 0.3
    per_asset_min_bars: 500
    per_asset_train_bars: 300
    per_asset_test_bars: 100
    per_asset_step_bars: 100
    per_asset_purge_bars: 10
    per_asset_validation_drop_threshold: 0.15
    per_asset_min_zone_count_gate: 3
    per_asset_min_survival_rate_constraint: 0.20
    per_asset_gate_penalty: 0.5
    per_asset_sampler: tpe
    per_asset_constraint_penalty_floor: 0.5
    per_asset_fold_stride: 3
    seed: 42

    # Quality metric tuning
    quality_reversal_threshold_pct: 0.015
    quality_coverage_proximity_atr: 0.3
    quality_weights:
      survival_rate: 0.25
      touch_accuracy: 0.30
      false_breakout_rate: 0.20
      strength_stability: 0.10
      coverage: 0.15
```

Resolved via `SRConfigResolver.resolve_typed_optimization_config()` into `OptimizationConfig` (frozen dataclass with all Stage 1 + Stage 2 fields).

## Tests

| Test File | Tests | Covers |
|-|-|-|
| `test_phase4.py` | 26 | Universe optimizer, cross-asset benchmark, heatmap |
| `test_phase1_optimizer.py` | 30 | MultiBarRunner, ZoneQualityMetrics, composite scoring, integration |
| `test_phase2_optimizer.py` | 22 | AssetSROptimizer: narrowed bounds, regularization, gates/constraints, walk-forward, Optuna/fallback, persistence |
| `test_phase3_optimizer.py` | 17 | TwoStageOptimizer: orchestration, emit_config, YAML round-trip, resolver cascade integration |
| `test_scripts_utils.py` | 11 | Shared utilities: `_ensure_utc`, `_parse_date`, `SRStatusFileWriter` lifecycle/atomic/fail |
| `test_run_optimization_cli.py` | 10 | `run_optimization.py` CLI: arg parsing, config building, exit codes |
| `test_monitor_cli.py` | 17 | `monitor_optimization.py` CLI: show/list/compare, arg parsing, helpers |
| `test_zone_quality_audit_cli.py` | 5 | `zone_quality_audit.py` CLI: arg parsing, synthetic audit, insufficient data |

Key test patterns:
- **Unit**: Synthetic `MultiBarRunResult` with known counters → verify each metric formula
- **Event classification**: Feed individual `ZoneLifecycleEvent` → verify counter increments
- **Integration**: Create real `SRv2Pipeline`, run `MultiBarRunner` bar-by-bar on synthetic OHLCV, then `evaluate()` + `composite_score()`
- **Cascade round-trip**: `emit_config()` → merge into raw config → `SRConfigResolver.resolve()` → verify per-asset overrides take precedence
- **CLI**: Arg parsing, synthetic data mocking, exit code validation, result JSON round-trip
- **Edge cases**: Zero zones, zero touches, frozen dataclass immutability

---

## Operational Scripts

CLI scripts for running, monitoring, and diagnosing SR optimization.

### run_optimization.py

Main CLI entry point for two-stage S/R optimization on real market data.

```bash
# Single asset
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h --n-trials 50

# Multi-asset with date range
python app/sr/scripts/run_optimization.py \
    -a BTCUSDT,ETHUSDT,SOLUSDT -t 1h,4h \
    --start-date 2023-01-01 --end-date 2026-03-01 \
    --n-trials 100 --timeout 7200

# Apply best params to YAML (with diff preview)
python app/sr/scripts/run_optimization.py -a BTCUSDT -t 1h \
    --n-trials 50 --apply --dry-run
```

| Flag | Default | Description |
|-|-|-|
| `-a/--assets` | `BTCUSDT` | Comma-separated trading pairs |
| `-t/--timeframes` | `1h` | Comma-separated timeframes |
| `--n-trials` | 50 | Stage 1 Optuna trials |
| `--timeout` | 3600 | Stage 1 timeout (seconds) |
| `--stage2-n-trials` | 30 | Stage 2 per-asset trials |
| `--stage2-timeout` | 600 | Stage 2 per-asset timeout |
| `--config` | — | Path to sr.yaml |
| `--start-date/--end-date` | — | Date range (YYYY-MM-DD) |
| `-l/--lookback` | 90 | Lookback days (if no date range) |
| `--sampler` | tpe | tpe, cma-es, random |
| `--apply` | off | Write best params to YAML |
| `--dry-run` | off | Preview YAML diff without writing |
| `--quiet` | off | Suppress progress |
| `--seed` | 42 | Optuna sampler seed (overrides YAML) |

Exit codes: 0 = success, 1 = failure/insufficient data.

**`main()` execution order**: fetch data → `build_configs()` → validate min_bars → run optimization.

### monitor_optimization.py

Subparser CLI for inspecting and watching optimization results.

```bash
python app/sr/scripts/monitor_optimization.py show results/BTCUSDT_1h_20260429.json
python app/sr/scripts/monitor_optimization.py list --sort score
python app/sr/scripts/monitor_optimization.py watch --interval 3
python app/sr/scripts/monitor_optimization.py compare run1.json run2.json
```

| Command | Description |
|-|-|
| `show <path>` | Detailed result: Stage 1 + Stage 2 per-asset table |
| `list` | All result files sorted by time/score/asset |
| `watch` | Live progress dashboard (polls `.optimization_status.json`) |
| `compare <a> <b>` | Side-by-side delta: scores, params, per-asset |

### zone_quality_audit.py

Real-data zone quality diagnostic using `MultiBarRunner` + `ZoneQualityEvaluator`.

```bash
python app/sr/scripts/zone_quality_audit.py -a BTCUSDT -t 1h --lookback 90
python app/sr/scripts/zone_quality_audit.py -a ETHUSDT -t 4h \
    --start-date 2025-01-01 --end-date 2026-01-01
```

Reports 5 quality metrics, composite score, zone statistics, and event histogram.

### Audit Acceptance Bands

Use the following bands to classify audit quality for deployment decisions.

| Metric | Accept | Borderline | Reject |
|-|-|-|-|
| Composite score | >= 0.68 | 0.62 to 0.67 | < 0.62 |
| Touch accuracy | >= 0.82 | 0.76 to 0.81 | < 0.76 |
| False breakout rate | <= 0.30 | 0.31 to 0.36 | > 0.36 |
| Survival rate | >= 0.65 | 0.58 to 0.64 | < 0.58 |
| Coverage | 0.45 to 0.70 | 0.35 to 0.44 or > 0.70 | < 0.35 |

Suggested decision rule:
- Accept run if composite is in Accept and no more than one metric is Borderline.
- Borderline if composite is Accept but two or more metrics are Borderline, or composite is Borderline with no Reject metrics.
- Reject run if composite is Reject, or any two metrics are in Reject.

For altcoins, always run at least two audits before accepting:
- Optimization window audit (same window used for optimizer).
- Regime-transfer audit (expanded or shifted window, for example adding earlier cycle data).

### SRStatusFileWriter

Atomic JSON status file for cross-process monitoring of two-stage optimization.

- **Path**: `app/sr/optimization/results/.optimization_status.json`
- **Write method**: `tempfile` + `os.replace()` (crash-safe)
- **Schema**: `{pid, assets, timeframes, start_time, last_update, status, stage, stage1_trial_current, stage1_n_trials_target, stage1_best_score, stage2_asset_current, stage2_tf_current, stage2_assets_completed, stage2_assets_total, error}`

### Typical Workflow

1. **Run**: `python app/sr/scripts/run_optimization.py -a BTCUSDT,ETHUSDT -t 1h --n-trials 50`
2. **Watch** (in another terminal): `python app/sr/scripts/monitor_optimization.py watch`
3. **Inspect**: `python app/sr/scripts/monitor_optimization.py show results/<file>.json`
4. **Compare**: `python app/sr/scripts/monitor_optimization.py compare run1.json run2.json`
5. **Apply**: `python app/sr/scripts/run_optimization.py ... --apply --dry-run` (preview), then `--apply` (write)

---

## End-to-End Pipeline — Detailed View

This section traces the complete optimization flow from CLI invocation through every internal step.

### 1. CLI Entry (`run_optimization.py::main()`)

```
CLI args
  │
  ▼
┌──────────────────────────────┐
│ 1. Parse arguments           │  -a, -t, --n-trials, --seed, --sampler, etc.
│ 2. Fetch OHLCV data          │  fetch_multi_asset_data() → data_map: {asset: {tf: DataFrame}}
│ 3. Build configs             │  build_configs(args) → (stage1_config, stage2_config, universe_config)
│ 4. Validate min_bars         │  Reject if any (asset, tf) has < stage2_config.min_bars (default 500)
│ 5. Initialize status writer  │  SRStatusFileWriter for cross-process monitoring
│ 6. Run TwoStageOptimizer     │  .optimize(data_map, correlation_matrix)
│ 7. Save + optionally apply   │  .save() JSON, .apply_to_yaml() if --apply
└──────────────────────────────┘
```

`build_configs()` wires YAML fields from `OptimizationConfig` into runtime configs:
- Stage 1: `UniverseOptimizationConfig(n_trials, timeout_s, tier6_weight, seed, parameter_space)`
- Stage 2: `AssetOptimizationConfig(n_trials, timeout_s, sampler, seed, constraint_penalty_floor, quality_*)` — loaded from YAML `per_asset_*` and `quality_*` fields
- Universe: `UniverseSRConfig(assets, timeframes, kernels)`

### 2. Two-Stage Orchestrator (`TwoStageOptimizer.optimize()`)

```
                    data_map, correlation_matrix
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       │
  ┌───────────────────┐                           │
  │  Stage 1           │                          │
  │  Universe-wide     │                          │
  │  joint optimizer   │                          │
  │                    │                          │
  │  Optimize 13 params│                          │
  │  across all assets │                          │
  └────────┬──────────┘                           │
           │ global_best_params                   │
           ▼                                      │
  ┌───────────────────┐                           │
  │  For each (asset,  │◄─────────────────────────┘
  │  tf) in data_map:  │         per-asset DataFrames
  │                    │
  │  Stage 2           │
  │  Per-asset refine  │
  │  10 kernel params  │
  │  walk-forward CV   │
  └────────┬──────────┘
           │ per_asset_results[]
           ▼
  ┌───────────────────┐
  │  emit_config()     │
  │  Merge into tiers  │
  │  Save + Apply      │
  └───────────────────┘
```

### 3. Stage 1 — Universe Optimizer (Detail)

```
UniverseSROptimizer.optimize(data_map, correlation_matrix)
  │
  ├── Create Optuna study (TPESampler, seed from config)
  │
  └── For each trial:
        │
        ├── 1. Suggest 13 parameters from search space
        │     (Optuna trial.suggest_float / suggest_int)
        │
        ├── 2. apply_params_to_config(params) → nested config dict
        │     {"kernels.order_block.displacement_atr": 1.8}
        │     → {"kernels": {"order_block": {"displacement_atr": 1.8}}}
        │
        ├── 3. Build UniverseSRRouter with trial config
        │
        ├── 4. evaluate_trial(data_map, correlation_matrix)
        │     │
        │     ├── For each (asset, tf):
        │     │     ├── Build SRv2Pipeline with trial config
        │     │     ├── MultiBarRunner.run(df, last eval_bars=300)
        │     │     ├── ZoneQualityEvaluator.composite_score(run_result)
        │     │     └── Store in per_asset_scores["SYMBOL/TF"]
        │     │
        │     ├── avg_quality = mean(per_asset_scores.values())
        │     │
        │     ├── If correlation_matrix provided:
        │     │     ├── CrossAssetSRAnalyzer.enrich_zones()
        │     │     ├── CrossAssetBenchmark.evaluate()
        │     │     └── cross_asset_score = benchmark_result.score
        │     │
        │     └── total = avg_quality × (1 - 0.10) + cross_score × 0.10
        │
        └── Return UniverseOptimizationResult(best_params, best_score, all_trials)
```

**Objective formula (Stage 1)**:
```
per_asset_score[sym/tf] = ZoneQualityEvaluator.composite_score(
    MultiBarRunner.run(df[-eval_bars:])
)

avg_quality = mean(per_asset_score.values())

total_score = avg_quality × (1 - tier6_weight) + cross_asset_score × tier6_weight
            = avg_quality × 0.90 + cross_asset_score × 0.10
```

### 4. Stage 2 — Per-Asset Optimizer (Detail)

```
AssetSROptimizer.optimize(df)
  │
  ├── Narrow bounds: ±bound_fraction (25%) around Stage 1 global best
  │     clamped to original parameter space bounds
  │
  ├── Create Optuna study
  │     ├── Sampler: TPE (default) | CMA-ES | Random — seeded from config
  │     └── Pruner: MedianPruner(n_startup_trials=5, n_warmup_steps=1)
  │
  └── For each trial:
        │
        ├── 1. Suggest parameters (narrowed bounds)
        │
        ├── 2. Walk-forward CV via WalkForwardValidator
        │     │
        │     │   ┌──────────┬───────┬──────────┬───────┬────────────
        │     │   │ train_0  │purge_0│ test_0   │       │
        │     │   │  300 bars│10 bars│ 100 bars │       │
        │     │   └──────────┴───────┴──────────┘       │
        │     │              ┌──────────┬───────┬───────┴──┐
        │     │              │ train_1  │purge_1│ test_1   │
        │     │              │  300 bars│10 bars│ 100 bars │
        │     │              └──────────┴───────┴──────────┘
        │     │
        │     └── For each fold:
        │           │
        │           ├── 3. Build SRv2Pipeline with trial params
        │           ├── 4. Run MultiBarRunner on TEST fold (not train!)
        │           │     └── sliding window: max_lookback=500 bars
        │           ├── 5. ZoneQualityEvaluator.evaluate(run_result) → 5 metrics
        │           ├── 6. raw_score = composite_score(metrics)
        │           │
        │           ├── 7. Apply gate multiplier:
        │           │     if zones_created < min_zone_count_gate (3):
        │           │       gate_mult = gate_penalty (0.5)
        │           │     else:
        │           │       gate_mult = 1.0
        │           │
        │           ├── 8. Apply survival constraint:
        │           │     if survival_rate < min_survival (0.20):
        │           │       constraint_mult = floor + (1 - floor) × (survival / min_survival)
        │           │       where floor = constraint_penalty_floor (0.50)
        │           │     else:
        │           │       constraint_mult = 1.0
        │           │
        │           ├── 9. Compute regularization penalty:
        │           │     reg = regularization_weight × mean(|param - global| / bound_range)
        │           │        = 0.3 × mean(normalized_deviations)
        │           │
        │           ├── 10. fold_score = raw × gate_mult × constraint_mult - reg
        │           │
        │           └── 11. trial.report(fold_score, fold_idx) → pruner may kill trial
        │
        ├── mean_train_score, mean_val_score across folds
        │
        ├── 12. Rejection check:
        │     if mean_val < mean_train × (1 - validation_drop_threshold):
        │       → revert to global defaults (fallback_to_global=True)
        │
        └── Return AssetOptimizationResult
```

**Objective formula (Stage 2, per fold)**:
```
raw_score = ZoneQualityEvaluator.composite_score(
    MultiBarRunner.run(test_df, max_lookback=500)
)

gate_mult = 0.5  if zones_created < 3  else 1.0

constraint_mult = (0.5 + 0.5 × survival/0.20)  if survival < 0.20  else 1.0

reg_penalty = 0.3 × mean(|param_i - global_i| / (high_i - low_i))

fold_score = raw_score × gate_mult × constraint_mult - reg_penalty
```

### 5. Composite Quality Score (Shared Objective)

Both stages use the same `ZoneQualityEvaluator.composite_score()`:

```
composite = 0.25 × survival_rate
          + 0.30 × touch_accuracy
          + 0.20 × (1 - false_breakout_rate)       ← inverted: lower FBR = better
          + 0.10 × strength_stability
          + 0.15 × coverage
```

Each metric computed from `MultiBarRunResult`:

```
survival_rate       = zones_reached_active / total_zones_created
touch_accuracy      = (touches - breakouts) / touches
false_breakout_rate = false_breakouts / breakouts
strength_stability  = 1 - cv(strength) across final zones
coverage            = covered_reversals / total_reversals
```

Coverage algorithm:
1. Scan close prices for reversals ≥ `reversal_threshold_pct` (1.5%) direction change
2. For each reversal bar, check if any active zone center is within `coverage_proximity_atr × ATR` (0.3 × ATR) of the reversal price
3. `coverage = count(covered) / count(total_reversals)`

All weights and thresholds are configurable via `quality_weights`, `quality_reversal_threshold_pct`, and `quality_coverage_proximity_atr` in `sr.yaml`.

### 6. MultiBarRunner Execution Model

```
run(df, start_bar=N, end_bar=M, max_lookback=500)
  │
  For bar_idx in range(start_bar, end_bar):
  │
  ├── bar_slice = df[max(0, bar_idx+1-500) : bar_idx+1]   ← sliding window
  │
  ├── pipeline.run(bar_slice)                               ← SRv2Pipeline (stateful)
  │     ├── Kernel detection (volume_poc, order_block, ...)
  │     ├── Feature extraction
  │     ├── Ensemble scoring
  │     ├── Zone gate (emission control)
  │     └── Lifecycle management (touches, breakouts, expiry)
  │
  ├── Collect lifecycle events from pipeline state
  │     ├── Touch events → total_touches++
  │     ├── Breakout events → total_breakouts++, broken_ids.add()
  │     ├── Price-returned events → total_false_breakouts++
  │     ├── State → ACTIVE → ever_active_ids.add()
  │     └── State → EXPIRED → expired_ids.add()
  │
  └── Snapshot active zones (center, lower, upper, atr)
  │
  Return MultiBarRunResult(bar_count, all_events, final_zones, counters, ...)
```

**Complexity**: O(n) per bar (constant-size window), O(n × bars) total. Previously O(n²) due to growing slices from bar 0.

---

## Data-Driven Search-Space Bounds

### Purpose

`data_driven_bounds.py` computes data-adaptive search-space bounds for 6 kernel parameters based on the actual OHLCV data distribution. This prevents the optimizer from exploring regions that are structurally impossible for the given asset.

### Architecture

```
compute_data_driven_bounds(df, base_space)
  │
  ├── Compute ATR, volume, price statistics from df
  │
  ├── For each of 6 derivable parameters:
  │     ├── Derive bounds from data percentiles (p20/p80, p75/p95, etc.)
  │     └── Clamp to canonical bounds from _default_parameter_space()
  │
  └── Return updated parameter_space dict
```

### Canonical Bounds Source

All clamp operations now source their limits from the single canonical definition in `_default_parameter_space()`, eliminating duplicated magic numbers:

```python
_PARAM_KEYS = {
    "gap_min_atr":      "kernels.fair_value_gap.gap_min_atr",
    "displacement_atr": "kernels.order_block.displacement_atr",
    "max_pierce_atr":   "kernels.liquidity_sweep.max_pierce_atr",
    "sweep_lookback":   "kernels.liquidity_sweep.sweep_lookback",
    "imbalance_ratio":  "kernels.order_block.imbalance_ratio",
    "band_width_sigma": "kernels.regression_band.band_width_sigma",
}

def _canonical_bounds():
    space = _default_parameter_space()
    return {name: (space[name]["low"], space[name]["high"]) for name in space}
```

Each `_derive_*` function uses:
```python
canon = _canonical_bounds()[_PARAM_KEYS["param_name"]]
low = max(canon[0], data_derived_low)
high = min(canon[1], data_derived_high)
```

### Derivation Methods

| Parameter | Data Signal | Percentile Range | Notes |
|-|-|-|-|
| `gap_min_atr` | ATR-normalized bar ranges | p20 → p80 | Smaller ATR = tighter FVG threshold |
| `displacement_atr` | ATR-normalized move sizes | p75 → p95 | Large moves define displacement |
| `max_pierce_atr` | ATR-normalized wicks | p80 → p95 | Wick depth defines sweep pierce |
| `sweep_lookback` | Volatility regime duration | Adaptive | Higher vol = shorter lookback |
| `imbalance_ratio` | Volume asymmetry distribution | p60 → p90 | Volume skew defines imbalance |
| `band_width_sigma` | Return distribution kurtosis | Adaptive | Fat tails = wider bands |

---

## Shared Utilities

### NumpyDatetimeEncoder (`_json_utils.py`)

Shared JSON encoder used by `AssetSROptimizer.save()` and `TwoStageOptimizer.save()` for result serialization:

```python
class NumpyDatetimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):       return bool(obj)
        if isinstance(obj, np.integer):     return int(obj)
        if isinstance(obj, np.floating):    return float(obj)
        if isinstance(obj, np.ndarray):     return obj.tolist()
        if isinstance(obj, datetime):       return obj.isoformat()
        return super().default(obj)
```

Previously duplicated as inline classes in both `asset_optimizer.py` and `two_stage_optimizer.py`.

---

## Design Decisions & Rationale

### Why both stages use the same objective

Prior to the Stage 1 alignment change, Stage 1 optimized for `mean(ScoredLevel.strength)` while Stage 2 optimized for `ZoneQualityEvaluator.composite_score()`. This created a mismatch: Stage 1 could find parameters that produce high-strength zones that don't survive, don't get touched accurately, or don't cover reversals. By using the same lifecycle-based composite in both stages, the global starting point that Stage 2 refines is already optimized for the metrics that matter.

### Why test folds, not train folds

The Optuna objective in Stage 2 evaluates `test_df` (the held-out validation window), not `train_df`. This is the standard practice for walk-forward CV: scoring on the training window would reward overfitting. The test window provides an unbiased estimate of out-of-sample performance.

### Why sliding window instead of growing slices

The `MultiBarRunner` previously used `df.iloc[:bar_idx + 1]` which copies an increasing number of rows at each bar, producing O(n²) total memory allocation. With `max_lookback=500`, each bar sees exactly `min(500, available_bars)` rows, making per-bar cost constant and total cost O(n × 500).

### Why regularization towards global params

Without regularization, per-asset optimization could drift parameters far from the global optimum found in Stage 1, especially on small datasets. The penalty `0.3 × mean(|Δ| / range)` keeps parameters close to the global solution unless the per-asset data strongly supports divergence.

### Why constraint_penalty_floor from config

The survival constraint uses a soft penalty rather than hard rejection. The `constraint_penalty_floor` (default 0.50) ensures that even trials with zero survival rate still get a non-zero score, allowing Optuna's TPE to learn from poor regions rather than treating them as black holes.

---

## Appendix: Full Config Schema for Optimization

All optimization-related fields in `sr.yaml` under `optimization:`:

```yaml
optimization:
  # ── Stage 1: Universe-wide ──
  n_trials: 50                              # Optuna trials for Stage 1
  timeout_s: 3600.0                         # Max time (seconds)
  tier6_weight: 0.10                        # Cross-asset score weight
  parameters: { ... }                       # 13-param search space

  # ── Stage 2: Per-asset ──
  per_asset_n_trials: 30                    # Trials per (asset, tf)
  per_asset_timeout_s: 600.0                # Max time per asset
  per_asset_bound_fraction: 0.25            # ±% narrowing from global
  per_asset_regularization_weight: 0.3      # Deviation penalty
  per_asset_min_bars: 500                   # Minimum data requirement
  per_asset_train_bars: 300                 # Walk-forward train window
  per_asset_test_bars: 100                  # Walk-forward test window
  per_asset_step_bars: 100                  # Walk-forward step size
  per_asset_purge_bars: 10                  # Train/test purge gap
  per_asset_validation_drop_threshold: 0.15 # Max train→val score drop
  per_asset_min_zone_count_gate: 3          # Zone count gate threshold
  per_asset_min_survival_rate_constraint: 0.20  # Survival floor
  per_asset_gate_penalty: 0.5              # Score multiplier on gate fail
  per_asset_sampler: tpe                    # tpe | cmaes | random
  per_asset_constraint_penalty_floor: 0.5   # Min multiplier on constraint fail
  per_asset_fold_stride: 3                  # Walk-forward fold stride

  # ── Shared ──
  seed: 42                                  # Optuna sampler seed (all stages)

  # ── Quality metric tuning ──
  quality_reversal_threshold_pct: 0.015     # Reversal detection threshold
  quality_coverage_proximity_atr: 0.3       # ATR proximity for coverage
  quality_weights:                          # Composite score weights
    survival_rate: 0.25
    touch_accuracy: 0.30
    false_breakout_rate: 0.20
    strength_stability: 0.10
    coverage: 0.15
```

These are resolved by `SRConfigResolver.resolve_typed_optimization_config()` into the `OptimizationConfig` frozen dataclass, which feeds into `build_configs()` in `run_optimization.py`.

---

## Appendix: Parameter Flow Diagram

```
sr.yaml                    CLI flags (--seed, --sampler, ...)
  │                              │
  ▼                              ▼
SRConfigResolver          argparse (run_optimization.py)
  │                              │
  ▼                              │
OptimizationConfig ◄─────────────┘  (CLI overrides YAML)
  │
  ├──► UniverseOptimizationConfig (n_trials, timeout, seed, tier6_weight, parameter_space)
  │       │
  │       └──► UniverseSROptimizer.optimize()
  │              └──► global_best_params
  │
  ├──► AssetOptimizationConfig (n_trials, timeout, seed, sampler, bounds, quality_*, gates)
  │       │
  │       └──► AssetSROptimizer.optimize() × N
  │              └──► per_asset_params
  │
  └──► UniverseSRConfig (assets, timeframes, kernels)
          │
          └──► UniverseSRRouter (parallel multi-asset pipeline)
```

```
Optuna Study
  │
  ├── TPESampler(seed=config.seed)
  │
  ├── MedianPruner(n_startup=5, n_warmup=1)     ← Stage 2 only
  │
  └── Objective closure
        │
        ├── trial.suggest_float(name, low, high) × N params
        │
        ├── Walk-forward folds (Stage 2)
        │     or eval_bars=300 (Stage 1)
        │
        ├── SRv2Pipeline → MultiBarRunner → ZoneQualityEvaluator
        │
        ├── Gate / Constraint / Regularization (Stage 2)
        │
        └── trial.report(score, fold_idx) + pruner check (Stage 2)
```
