# Regime Optimization Framework

Bayesian hyperparameter optimization for the 4-layer regime detection pipeline.

## Overview

The regime module has **18 tunable parameters** per asset per timeframe. This framework optimizes them using:

1. **Data fetching** — BinanceConnector with paginated OHLCV + local CSV caching
2. **Optuna (TPE sampler)** — Bayesian search over 18-param space
3. **Walk-forward cross-validation** — temporal splits with purge gap
4. **5-tier composite objective** — weighted scoring with statistical validity gate and stability constraints
5. **3-stage hierarchical search** — avoids overfitting by progressively narrowing
6. **Result export** — writes optimized params to `config/regime.yaml` with backup

## Search Space

Default bounds (used by `--trading-style default`). Scalping and swing have separate presets — see [Trading Style Presets](#trading-style-presets) below.

| Parameter | Type | Default range | Layer |
|-|-|-|-|
| `bcpd_hazard_lambda` | float | [50, 1000] | BCPD |
| `bcpd_signal_threshold` | float | [0.20, 0.60] | BCPD |
| `bcpd_hazard_shape` | float | [0.8, 2.0] | BCPD (Weibull) |
| `vol_high_percentile` | float | [65, 85] | VolOverlay |
| `vol_lookback` | int | [48, 336] | VolOverlay |
| `vol_hysteresis_band` | float | [1.0, 5.0] | VolOverlay |
| `hmm_retrain_window` | int | [300, 2000] | HMM |
| `hmm_student_df` | float | [3.0, 15.0] | HMM (Student-t) |
| `hmm_crisis_vol_mult` | float | [1.5, 4.0] | HMM |
| `hurst_lookback` | int | [50, 200] | Hurst |
| `min_dwell_bars` | int | [3, 25] | Aggregator |
| `agg_direction_period` | int | [10, 50] | Aggregator |
| `agg_bull_roc_thresh` | float | [0.005, 0.05] | Aggregator |
| `agg_vol_squeeze_pct` | float | [10, 50] | Aggregator |
| `agg_cp_position_decay` | float | [0.2, 0.8] | Aggregator |
| `roc_std_window` | int | [50, 200] | Aggregator |
| `hilbert_min_period` | int | [5, 80] | Hilbert |
| `hilbert_max_period` | int | [40, 200] | Hilbert |

**Bound rationale:**
- `vol_high_percentile` floored at 65 — values below over-classify HIGH_VOL, reducing regime distinction
- `hmm_retrain_window` upper bound can be pushed to 6000 for swing — more history → more stable state estimates
- `min_dwell_bars` widened to 25 from 15 — previous runs pinned at ceiling, signalling the optimizer wanted longer holds

---

## Trading Style Presets

Regime hyperparams are **strategy-horizon-dependent**. The same objective with different hold-time expectations produces structurally different optima. Use `--trading-style` to constrain the search space to the appropriate regime sensitivity.

### Why style-specific bounds matter

Without style bounds, the optimizer converges to a single local optimum determined by the objective weights. In practice:
- **Balanced mode without style → swing params** (`hmm_retrain_window≈1776`, `hurst_lookback≈182`) because 25% strategy weight favors stable, durable labels over sensitive, fast-reacting ones.
- Running that config for scalping produces regime labels that flip too infrequently to time short-term entries.

You should run **separate optimizations** for scalping and swing, save results under different asset/style keys, and wire the correct config at runtime.

### Preset comparison (1h bars)

| Dimension | Scalping | Swing |
|-|-|-|
| Hold duration | 1–8 bars (1–8 h) | 12–80 bars (0.5–3 days) |
| `hazard_lambda` | [10, 150] | [300, 3000] |
| `hmm_retrain_window` | [100, 600] | [1000, 6000] |
| `hurst_lookback` | [15, 80] | [100, 500] |
| `min_dwell_bars` | [2, 8] | [12, 80] |
| `hilbert_min_period` | [5, 25] | [20, 100] |
| `hilbert_max_period` | [20, 80] | [80, 400] |
| `vol_lookback` | [24, 168] | [168, 720] |
| `roc_std_window` | [20, 80] | [100, 400] |
| `vol_hysteresis_band` | [1.0, 10.0] | [1.0, 10.0] |
| `min_avg_regime_duration` constraint | 3 bars | 24 bars |
| `max_flip_flop_rate` constraint | 0.25 | 0.06 |
| Default `objective_mode` | `classification` | `balanced` |

**Why different objective defaults:**
- Scalping uses `classification` by default — decouple regime quality from strategy (entry/exit logic changes frequently; don't overfit hyperparams to a specific scalping strategy).
- Swing uses `balanced` — 25% strategy weight guides toward regimes that are stable enough to hold and trade.

You can override with `--objective-mode` in both cases.

### CLI usage

```bash
# Scalping optimization
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --start-date 2022-01-01 --end-date 2026-03-01 \
    --staged --stage1-trials 50 --stage2-trials 50 --stage3-trials 100 \
    --plateau-stop --timeout 15000 --n-jobs 1 --step-bars 2160 \
    --trading-style scalping

# Swing optimization
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT --timeframe 1h \
    --start-date 2022-01-01 --end-date 2026-03-01 \
    --staged --stage1-trials 50 --stage2-trials 50 --stage3-trials 100 \
    --plateau-stop --timeout 15000 --n-jobs 1 --step-bars 2160 \
    --trading-style swing

# Override objective mode while keeping style bounds
... --trading-style scalping --objective-mode balanced
```

### Python API

```python
from app.regime.optimization import OptimizationConfig, WalkForwardConfig

wf = WalkForwardConfig(train_bars=4320, test_bars=720, step_bars=2160, purge_bars=24)

# Scalping preset — classification objective, fast detection bounds
config = OptimizationConfig.scalping(n_trials=200, walk_forward=wf)

# Swing preset — balanced objective, stable detection bounds
config = OptimizationConfig.swing(n_trials=200, walk_forward=wf)

# Override a specific bound within a preset
config = OptimizationConfig.swing(
    hmm_retrain_window=(1000, 8000),   # wider than default swing
    walk_forward=wf,
)
```

---

## Running Optimization

### Prerequisites

```bash
# Ensure you're in the project venv
source .venv/bin/activate

# Required packages
pip install optuna pyyaml

# IMPORTANT: Prevent BLAS thread oversubscription (causes 500%+ CPU on macOS)
# Add these env vars when running optimization:
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
```

### Step 1: Run the Optimizer

**Staged optimization (recommended):**

```bash
python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT \
    --timeframe 1h \
    --start-date 2023-01-01 \
    --end-date 2026-03-01 \
    --n-trials 150 --timeout 15000 \
    --staged --stage1-trials 40 --stage2-trials 40 --stage3-trials 70 \
    --n-jobs 1 \
    --step-bars 2160
```

**Key flags explained:**

| Flag | Purpose |
|------|---------|
| `--staged` | 3-stage hierarchical: BCPD -> Vol+HMM -> Full 18-param polish |
| `--stage1-trials 40` | Budget for BCPD params (hazard_lambda, signal_threshold, hazard_shape) |
| `--stage2-trials 40` | Budget for Vol+HMM+Aggregator params (fix BCPD at Stage 1 best) |
| `--stage3-trials 70` | Full 18-param polish with narrow ±20% bounds |
| `--n-jobs 1` | **Use 1 on macOS** — BLAS thread oversubscription causes 500%+ CPU |
| `--step-bars 2160` | Walk-forward step size (~3 months at 1h) — fewer folds, faster per trial |
| `--timeout 15000` | Hard timeout in seconds (~4 hours) |

**Single-pass optimization (simpler, less robust):**

```bash
python app/regime/scripts/run_optimization.py \
    --asset BTCUSDT \
    --timeframe 1h \
    --start-date 2023-01-01 \
    --end-date 2026-03-01 \
    --n-trials 100 --timeout 3600
```

**Multiple assets:**

```bash
python app/regime/scripts/run_optimization.py \
    --assets BTCUSDT ETHUSDT SUIUSDT \
    --timeframe 1h \
    --start-date 2023-01-01 \
    --end-date 2026-03-01 \
    --n-trials 100 --staged
```

**Universe mode (batch from YAML):**

```bash
python app/regime/scripts/run_optimization.py \
    --universe universe.yaml \
    --n-trials 100 --staged
```

Where `universe.yaml`:
```yaml
assets:
  - symbol: BTCUSDT
    timeframe: 1h
    start_date: "2023-01-01"
    end_date: "2026-03-01"
  - symbol: ETHUSDT
    timeframe: 1h
    start_date: "2023-06-01"
    end_date: "2026-03-01"
  - symbol: SUIUSDT
    timeframe: 1h
```

### Step 2: Monitor Progress (Separate Terminal)

While the optimizer runs, open a separate terminal to monitor:

```bash
python app/regime/scripts/monitor_optimization.py \
    --status-file app/regime/optimization/results/.optimization_status.json \
    --interval 5
```

The monitor shows real-time progress:
```
  ======================================
    Regime Optimization Monitor
  ======================================
  Asset:     BTCUSDT 1h
  Stage:     stage2 (Vol + HMM params)
  Status:    RUNNING

  Progress:  [==============------] 45/100 (45.0%)
  Best:      0.5257
  ETA:       ~12m 30s
  Elapsed:   15m 00s

  Process:   PID 12345 (alive)
  Updated:   10:45:00
  ======================================
```

**Monitor features:**
- ETA from trial rate
- Process health check (detects if optimizer crashed)
- Stale file detection (auto-removes leftover status from previous runs)
- Cross-platform: macOS, Linux, Windows, Docker
- `--json` flag for machine-readable output
- `--timeout 7200` for auto-exit after max wait

### Step 3: Review Results

After optimization completes, the script outputs:

1. **Per-stage summary** — objective value, gate pass rate, best params
2. **Param comparison** — old vs new side-by-side with deltas
3. **Full 5-tier metrics** — all benchmark scores
4. **Regime distribution** — on full dataset with optimized params
5. **Per-regime conditional returns** — mean, std, annualized Sharpe

Results are saved to:
```
app/regime/optimization/results/
├── BTCUSDT_1h_2026-03-18_14-30_staged.json   # Full result with all trials
├── .optimization_status.json                   # Status file (monitor reads this)
└── BTCUSDT_1h_2023-01-01_2026-03-01.csv       # Cached data (reusable)

app/regime/config/
├── regime.yaml                # Updated with best params
└── regime.yaml.bak.20260318_143000  # Auto-backup before overwrite
```

---

## Validating Optimized Params (Robustness Checklist)

After optimization, run through this checklist before trusting the params for live trading.

### Check 1: Tier 3 Gate — Statistical Validity

The optimized params **must** pass the Levene test (regimes produce statistically different return variances).

```
Levene p-value:  < 0.05   -> PASS (regimes are statistically distinct)
Cohen's d:       > 0.5    -> Good effect size (regimes are meaningfully different)
```

**Red flag:** `p-value > 0.05` means the regime labels don't partition returns into statistically distinct groups — the classification is no better than random.

### Check 2: Tier 4 — Stability Constraints

```
Avg regime duration:  >= 5 bars    (regimes persist long enough to act on)
Flip-flop rate:       <= 0.15      (< 15% of bars have a regime change)
```

**Red flag:** `avg_regime_duration < 5` or `flip_flop_rate > 0.15` means the optimizer found params that produce unstable, untradeable regime sequences. Check if any single param is near its bound ceiling (see Check 5).

### Check 3: Tier 1 — Strategy Utility

```
Sharpe improvement:   > 0.0    (regime-gated strategy beats buy-and-hold)
Drawdown reduction:   > 0.0    (max drawdown is smaller than buy-and-hold)
```

**Red flag:** Negative Sharpe improvement means the regime gating hurts performance vs. holding.

### Check 4: Regime Distribution

The distribution across the full dataset should be reasonable:

```
CLEAN_TREND:      5–30%    (pure trend-following conditions)
VOLATILE_TREND:   5–25%    (trend with elevated vol)
QUIET_MR:        30–60%    (mean-reverting, low vol — typical for crypto)
CHOPPY:          10–40%    (no edge, skip)
```

**Red flags:**
- Any single regime > 80% → classifier is degenerate (not discriminating)
- CLEAN_TREND + VOLATILE_TREND < 5% → HMM is classifying almost nothing as trending
- CHOPPY > 50% → too conservative (missing opportunities)

### Check 5: Param Boundary Check

No param should be stuck at its search bound ceiling/floor. What counts as "stuck" depends on trading style:

| Param | Scalping ceiling | Swing ceiling |
|-|-|-|
| `bcpd_hazard_lambda` | 150 | 3000 |
| `hmm_retrain_window` | 600 | 6000 |
| `hurst_lookback` | 80 | 500 |
| `min_dwell_bars` | 8 | 80 |
| `vol_high_percentile` | 85 (both) | 85 (both) |

**Red flag:** A param pinned at its ceiling typically means the optimizer wants a larger value than the search space allows. Common patterns:
- `hazard_lambda` at ceiling → BCPD wants even fewer changepoints → widen or switch to swing
- `hmm_retrain_window` at ceiling → HMM wants more history → widen or switch to swing
- `min_dwell_bars` at ceiling → labels are flipping too fast → widen or switch to swing

**Do not conflate swing params with stability gaming.** If you run `--trading-style swing` and see `hmm_retrain_window=5000`, that is expected and correct — it is not gaming, it is the style preference. Gaming only applies when stability is a *weighted reward* (pre-March 2026 setup). It is now a hard constraint.

If a param is still pinned after widening bounds, increase `stability_penalty` from 0.3 to 0.5.

### Check 6: Per-Regime Conditional Returns

Each regime should have returns consistent with its label:

```
CLEAN_TREND:     positive mean return, positive Sharpe
QUIET_MR:        near-zero or slightly positive mean return
CHOPPY:          ideally negative or zero (confirms "skip" is correct)
```

**Red flag:** If CHOPPY has the highest Sharpe, the regime labels are inverted or the HMM labeling is wrong.

### Check 7: Plateau Convergence

The script outputs plateau analysis per stage:

```
[Stage 1 (BCPD)] Plateau: tail_improvement=0.0001, top-10% CV=0.03 -> CONVERGED
[Stage 2 (Vol+HMM)] Plateau: tail_improvement=0.0003, top-10% CV=0.05 -> CONVERGED
[Stage 3 (Final)] Plateau: tail_improvement=0.0000, top-10% CV=0.02 -> CONVERGED
```

**Red flag:** `NOT YET` on the final stage means more trials are needed. Re-run with higher `--stage3-trials`.

### Check 8: Forward Return IC (Predictive Power)

```
Forward return IC:    > 0.02    (regime rank predicts 4-bar forward return direction)
IC decay score:       > 0.0     (predictive power holds across multiple horizons)
```

**Red flag:** `IC < 0.01` means regime labels have no forward-looking predictive power — they describe the past but don't help forecast.

### Check 9: Changepoint Quality (Tier 5)

```
CP precision:    > 0.1     (BCPD signals occur near actual vol regime transitions)
CP recall:       > 0.1     (actual transitions are detected by BCPD)
Detection lag:   < 20 bars (BCPD detects changes within 20 bars of ground truth)
```

**Red flag:** All zeros for CP metrics = `bcpd_signal` is not being propagated through the aggregator. This was fixed in the March 2026 update — ensure `rule_based.py` passes `bcpd_signal` from `cp_df`.

### Check 10: Walk-Forward Fold Consistency

Load the result JSON and check per-fold variance:

```python
from app.regime.optimization.models import OptimizationResult

result = OptimizationResult.load("app/regime/optimization/results/BTCUSDT_1h_staged.json")
best_trial = [t for t in result.all_trials if t.objective_value == result.best_objective][0]

for i, fold in enumerate(best_trial.fold_results):
    print(f"Fold {i}: sharpe_imp={fold.sharpe_improvement:+.3f}, "
          f"IC={fold.forward_return_ic:+.3f}, gate={'PASS' if fold.passed_validity_gate else 'FAIL'}")
```

**Red flag:** If some folds pass the validity gate and others don't, the params may be overfit to specific market periods. Look for folds with vastly different Sharpe or IC — this suggests the params don't generalize across regimes.

---

## Benchmark Tiers (Detailed)

### Tier 1: Strategy Utility (50%)

Simulates the regime-gated long-short strategy vs. buy-and-hold. Uses the
`position_scale` column from `features_df` — the same continuous p_trending-blended
weights that the live bot uses for sizing. Negative weights = short positions.

Position sizing per regime (from aggregator, continuous blending):
- **CLEAN_TREND_BULL** -> +1.0x long, **BEAR** -> -1.0x short, **FLAT** -> 0.0x flat
- **VOLATILE_TREND_BULL** -> +0.6x long, **BEAR** -> -0.6x short, **FLAT** -> 0.0x flat
- **QUIET_MR_RANGE** -> +0.3x long, **SQUEEZE** -> 0.0x flat
- **CHOPPY** -> 0.0x flat (skip)

Metrics:
- `sharpe_improvement` (weight: 0.325): Sharpe vs. buy-and-hold baseline
- `drawdown_reduction` (weight: 0.175): Max drawdown vs. buy-and-hold

### Tier 2: Predictive Power (40%)

Regime labels as forward-return predictors:

- `forward_return_ic` (weight: 0.175): Spearman IC between regime rank and 4-bar forward return
- `vol_forecast_error` (weight: 0.10): Rolling vol prediction error — lower is better
- `ic_decay_score` (weight: 0.125): IC weighted across [1, 4, 12, 24] bar horizons

### Tier 3: Statistical Validity (SOFT GATE)

Levene test — must pass or trial is penalized:

- Tests whether regimes produce significantly different return **variances**
- Threshold: `p < 0.05` (configurable via `validity_p_threshold`)
- Failed gate -> score divided by `validity_penalty` (default 5.0x)
- Cohen's d: bonus for effect size (`d > 0.5` adds bonus)

### Tier 4: Stability (HARD CONSTRAINT — not weighted)

Regime sequence robustness enforced as a **constraint, not a reward**. Thresholds differ by trading style:

| Constraint | Scalping | Default | Swing |
|-|-|-|-|
| `min_avg_regime_duration` | 3 bars | 5 bars | 24 bars |
| `max_flip_flop_rate` | 0.25 | 0.15 | 0.06 |

- Violation → 0.3x multiplicative penalty on entire score

**Why constraint, not reward:** When stability is a weighted reward in the objective, the
optimizer games ANY parameter that suppresses regime transitions (whack-a-mole pattern:
cap `hazard_lambda` -> inflates `hmm_retrain_window` -> cap that -> inflates `min_dwell_bars`).
Converting to a hard constraint eliminates the gaming vector entirely.

Metrics still computed for diagnostics:
- `avg_regime_duration`: Mean bars per regime episode
- `flip_flop_rate`: Fraction of bars where regime changed vs. prior bar
- `transition_entropy`: Shannon entropy of empirical transition matrix

### Tier 5: Changepoint Quality (10%)

BCPD detection quality using `vol_regime` transitions as ground truth:

- Ground truth: bars where `vol_regime` flips LOW_VOL <-> HIGH_VOL (~10-30 events/year at 1h BTC)
- `cp_precision` (weight: 0.05): Fraction of BCPD signals within detection window of a vol transition
- `detection_lag` (weight: 0.05): Mean bars between vol transition and nearest BCPD signal
- `cp_recall`: Fraction of vol transitions detected by BCPD (diagnostic, not weighted)

### Score Formula

```python
score = (
    0.325 * norm(sharpe_improvement)
  + 0.175 * norm(drawdown_reduction)
  + 0.175 * norm(forward_return_ic)
  + 0.100 * (1 - norm(vol_forecast_error))
  + 0.125 * norm(ic_decay_score)
  + 0.050 * cp_precision
  + 0.050 * norm(1 / (detection_lag + 1))
) * gate_mult * stability_mult + cohens_d_bonus
```

Where:
- `gate_mult` = 1.0 if Levene passes, else 1/5 (soft gate)
- `stability_mult` = 1.0 if constraints met, else 0.3
- `cohens_d_bonus` = bonus for large effect size

---

## Walk-Forward Validation

Rolling window splits with purge gap to prevent leakage:

```
|--- train (4320) ---|-- gap (24) --|-- test (720) --|
                                 |--- train (4320) ---|-- gap (24) --|-- test (720) --|
                                                                  ...
```

Default settings (1h timeframe):
- **Train:** 4320 bars (~6 months)
- **Test:** 720 bars (~1 month)
- **Step:** 720 bars (default) or 2160 bars (faster, fewer folds)
- **Purge:** `ceil(24h / bar_hours)` bars (timeframe-aware: 24 at 1h, 96 at 15m, 6 at 4h)
- **Min train:** 2160 bars (~3 months)

```python
from app.regime.optimization.walk_forward import WalkForwardValidator

wf = WalkForwardValidator(
    train_bars=4320,
    test_bars=720,
    step_bars=2160,   # 3-month steps for faster optimization
    purge_bars=24,
    min_train_bars=2160,
)

for split, train_df, test_df in wf.iterate_splits(df):
    print(f"Fold {split.fold_id}: train={split.train_size}, test={split.test_size}")
```

---

## Hierarchical Optimization (Staged)

To avoid overfitting all 18 params simultaneously:

**Stage 1: BCPD params only**
- Optimizes `bcpd_hazard_lambda`, `bcpd_signal_threshold`, `bcpd_hazard_shape`
- Fixes vol+HMM+aggregator at defaults
- Focus: changepoint detection quality

**Stage 2: Vol + HMM + Aggregator params (fix BCPD at Stage 1 best)**
- Optimizes `vol_high_percentile`, `vol_lookback`, `vol_hysteresis_band`, `hmm_retrain_window`, `hmm_student_df`, `hmm_crisis_vol_mult`, `hurst_lookback`, `min_dwell_bars`, `agg_direction_period`, `agg_bull_roc_thresh`, `agg_vol_squeeze_pct`, `agg_cp_position_decay`, `roc_std_window`, `hilbert_min_period`, `hilbert_max_period`
- Focus: regime classification + aggregation quality with known-good changepoint params

**Stage 3: Full 18-param polish**
- All 18 params, narrow bounds (±20% around Stage 1+2 bests)
- Warm start from best of prior stages
- Focus: joint optimization in the neighborhood of known-good params

**Plateau stop (`--plateau-stop`):**
- After each stage, checks if objective has converged (tail improvement < 0.005 and top-10% CV < 0.10)
- If converged, halves the trial budget for the next stage (min 10 trials)
- Saves significant time when early stages converge quickly

---

## Python API

```python
from app.regime.optimization import RegimeOptimizer, OptimizationConfig, WalkForwardConfig

config = OptimizationConfig(
    n_trials=100,
    timeout_seconds=3600,
    walk_forward=WalkForwardConfig(
        train_bars=4320,
        test_bars=720,
        step_bars=2160,
        purge_bars=24,
    ),
)

optimizer = RegimeOptimizer(config)
result = optimizer.optimize(df, asset="BTCUSDT", timeframe="1h")

print(f"Best Score:  {result.best_objective:.4f}")
print(f"Best Params: {result.best_params}")
print(f"Trials OK:   {result.n_trials_passed_gate}/{result.n_trials_total}")

# Auto-save to regime.yaml
result.apply_to_config("app/regime/config/regime.yaml")
```

---

## Data Models

### OptimizationConfig

```python
@dataclass
class OptimizationConfig:
    # Search space bounds (min, max) — 18 params
    # BCPD layer
    hazard_lambda: tuple = (50.0, 1000.0)
    signal_threshold: tuple = (0.20, 0.60)
    bcpd_hazard_shape: tuple = (0.8, 2.0)
    # VolOverlay layer
    vol_high_percentile: tuple = (65.0, 85.0)
    vol_lookback: tuple = (48, 336)
    vol_hysteresis_band: tuple = (1.0, 5.0)   # presets use (1.0, 10.0)
    # HMM layer
    hmm_retrain_window: tuple = (300, 2000)   # swing preset: (1000, 6000)
    hmm_student_df: tuple = (3.0, 15.0)
    hmm_crisis_vol_mult: tuple = (1.5, 4.0)
    hurst_lookback: tuple = (50, 200)          # swing preset: (100, 500)
    # Aggregator layer
    min_dwell_bars: tuple = (3, 25)
    agg_direction_period: tuple = (10, 50)
    agg_bull_roc_thresh: tuple = (0.005, 0.05)
    agg_vol_squeeze_pct: tuple = (10.0, 50.0)
    cp_position_decay: tuple = (0.2, 0.8)
    roc_std_window: tuple = (50, 200)
    # Hilbert layer
    hilbert_min_period: tuple = (5, 80)
    hilbert_max_period: tuple = (40, 200)

    # Run settings
    n_trials: int = 100
    timeout_seconds: int = 3600
    n_jobs: int = 1
    sampler: str = "tpe"       # "tpe" | "random" | "cmaes"
    pruner: str = "median"     # "median" | "hyperband" | "none"
    objective_mode: str = "full"  # "full" | "classification" | "balanced"

    # Validity gate (Tier 3)
    validity_p_threshold: float = 0.05
    soft_gate: bool = True
    validity_penalty: float = 5.0

    # Stability constraints (Tier 4 — hard, not optimized)
    # scalping preset: min_avg=3, max_flip=0.25
    # swing preset:    min_avg=24, max_flip=0.06
    min_avg_regime_duration: float = 5.0
    max_flip_flop_rate: float = 0.15
    stability_penalty: float = 0.3

    walk_forward: WalkForwardConfig
    weights: OptimizationWeights

    @classmethod
    def scalping(cls, **kwargs) -> "OptimizationConfig": ...
    @classmethod
    def swing(cls, **kwargs) -> "OptimizationConfig": ...
```

### BenchmarkResults

```python
@dataclass
class BenchmarkResults:
    # Tier 1: Strategy Utility
    sharpe_improvement: float
    drawdown_reduction: float
    # Tier 2: Predictive Power
    forward_return_ic: float
    vol_forecast_error: float
    ic_decay_score: float
    # Tier 3: Statistical Validity (Gate)
    levene_p_value: float
    cohens_d: float
    passed_validity_gate: bool
    # Tier 4: Stability (Constraint)
    avg_regime_duration: float
    flip_flop_rate: float
    transition_entropy: float
    # Tier 5: Changepoint Quality
    cp_precision: float
    detection_lag: float
    cp_recall: float
    # Meta
    computation_time_ms: float
    n_bars: int
```

---

## CLI Reference

```
python app/regime/scripts/run_optimization.py [OPTIONS]

Asset selection (mutually exclusive, one required):
  --asset SYMBOL            Single asset (e.g. BTCUSDT)
  --assets SYMBOL [...]     Multiple assets
  --universe FILE           YAML file with asset universe

Data:
  --timeframe TF            Timeframe (default: 1h)
  --start-date DATE         Start date YYYY-MM-DD (default: 2023-01-01)
  --end-date DATE           End date YYYY-MM-DD (default: 2026-03-01)
  --csv FILE                Load from CSV instead of Binance
  --cache-dir DIR           Data cache directory (default: optimization/results)

Optimization:
  --n-trials N              Total trials for single mode (default: 100)
  --timeout SECS            Hard timeout in seconds (default: 3600)
  --n-jobs N                Parallel Optuna jobs (default: 1, use 1 on macOS)
  --sampler {tpe,random,cmaes}  Sampler algorithm (default: tpe)
  --pruner {median,hyperband,none}  Pruner (default: median)
  --hard-gate               Hard-reject trials failing validity gate
  --trading-style STYLE     default | scalping | swing  (sets search bounds + stability constraints)
  --objective-mode MODE     full | classification | balanced
                            Overrides trading-style default (scalping→classification, swing→balanced)

Staged optimization:
  --staged                  Run 3-stage hierarchical optimization
  --stage1-trials N         Stage 1 budget (default: 50)
  --stage2-trials N         Stage 2 budget (default: 50)
  --stage3-trials N         Stage 3 budget (default: 100)
  --plateau-stop            Auto-reduce remaining trials on convergence

Walk-forward:
  --train-bars N            Training window (default: 4320)
  --test-bars N             Test window (default: 720)
  --step-bars N             Step size (default: 720)
  --purge-bars N            Purge gap (default: 24)
  --min-train-bars N        Minimum train bars (default: 2160)

Output:
  --output-dir DIR          Result JSON directory (default: optimization/results)
  --config-yaml FILE        Target YAML (default: config/regime.yaml)
  --no-apply                Skip writing to regime.yaml
  --no-status               Skip writing status file for monitor
  --no-full-metrics         Skip full metrics output
  --log-level {DEBUG,INFO,WARNING,ERROR}
```

### Monitor CLI

```
python app/regime/scripts/monitor_optimization.py [OPTIONS]

  --status-file FILE        Path to .optimization_status.json
  --interval SECS           Poll interval (default: 10)
  --timeout SECS            Max wait time (default: unlimited)
  --json                    Raw JSON output per poll
```

---

## Troubleshooting

### Optimizer at 500%+ CPU (macOS BLAS oversubscription)
**Cause:** NumPy/SciPy BLAS libraries (Accelerate, OpenBLAS) spawn their own threads per HMM fit. Even with `--n-jobs 1`, each `hmmlearn` call can use 4-8 threads internally.
**Fix:** Set thread limits before running:
```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python app/regime/scripts/run_optimization.py ...
```
This brings CPU to ~100% per trial and often runs faster due to reduced contention.

### Optimizer hangs at 0% CPU (macOS)
**Cause:** BLAS thread oversubscription when `n_jobs > 1` on macOS.
**Fix:** Always use `--n-jobs 1` on macOS.

### Monitor shows "Waiting for status file..." indefinitely
**Cause (most common):** Monitor running from a different working directory than the optimizer — relative paths diverge.
**Fix:** Both scripts now resolve paths to absolute from the project root. No `--status-file` arg needed; just run from anywhere:
```bash
python app/regime/scripts/monitor_optimization.py
```
The banner prints the full absolute path being watched — verify it matches the optimizer output.

### Monitor shows stale status from previous run
**Cause:** `.optimization_status.json` left from a prior run that finished or crashed.
**Behaviour:** Monitor detects dead PID (any status, not just terminal) and prints a notice. It does **not** delete the file — the new optimizer overwrites it on startup. Once the new optimizer starts, the monitor picks up the fresh file on the next poll.

### All Tier 5 metrics are zero
**Cause:** `bcpd_signal` column not propagated through the aggregator.
**Fix:** Ensure `rule_based.py` copies `bcpd_signal` from `cp_df` in `aggregate_series()`.

### Params near search bounds
**Cause:** Optimizer gaming stability by suppressing regime transitions.
**Fix:** The Tier 4 hard constraint (March 2026) prevents this. If still happening, increase `stability_penalty` from 0.3 to 0.5 or tighten the offending param's search range.

### Not enough data for walk-forward
**Cause:** Dataset shorter than `train_bars + test_bars`.
**Fix:** Use a longer date range or reduce `--train-bars`.
