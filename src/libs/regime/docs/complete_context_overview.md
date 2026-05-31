# Regime Module: Complete Context & Architecture Overview

This document provides a comprehensive, unified view of the `app/regime` module.
It is the foundational reference for understanding the regime detection pipeline,
its components, data contracts, optimization framework, and integration points.

> **Updated 2026-03-27**: Phase 1-4 upgrades -- multi-channel BCPD, Weibull hazard,
> bounded z-score, causal Hilbert, N-state HMM with BIC, Student-t scoring,
> market structure handler, MTF fusion, timeframe-aware scaling, 9-label taxonomy fix.

---

## 1. High-Level Architecture

The regime module is a **stateless, bar-close execution pipeline** with 4 detection layers
plus preprocessing (MarketStructure) and optional post-processing (MTFFusion), all wired by
`RegimeOrchestrator`. Each layer is orthogonal -- BCPD detects structural breaks, HMM learns
latent regime distributions, VolOverlay measures realized vol rank, and Hilbert extracts
cycle period. The aggregator fuses all four into a single `RegimeFeatures` object.

```
Pre:    MarketStructure   auto-infer crypto/stock/fx, attenuate gaps
Layer 1: ChangeDetector   multi-channel BCPD (returns+volume+range) -> changepoint_prob
Layer 2: HMMClassifier    N-state GaussianHMM (BIC, Student-t) -> p_trending, hmm_regime
Layer 3: VolOverlay       rolling_std -> vol_percentile, vol_regime (LOW/HIGH + hysteresis)
Layer 4: HilbertCycle     Ehlers causal FIR -> dominant_period, confidence
         |
Aggregator: regime in {CLEAN_TREND_BULL/BEAR/FLAT, VOLATILE_TREND_BULL/BEAR/FLAT,
                        QUIET_MR_RANGE, QUIET_MR_SQUEEZE, CHOPPY}
         |
Post:   MTFFusion         optional higher-TF overlay (CONFIRMING/CONFLICTING/SUPPRESSING)
```

**Nine combined regime labels (with direction overlay and squeeze):**

| hmm_regime | vol_regime | Direction | Combined Regime | position_scale |
|-|-|-|-|-|
| TRENDING | LOW_VOL | BULL | CLEAN_TREND_BULL | +1.0x (long) |
| TRENDING | LOW_VOL | BEAR | CLEAN_TREND_BEAR | -1.0x (short) |
| TRENDING | LOW_VOL | FLAT | CLEAN_TREND_FLAT | 0.0x (flat) |
| TRENDING | HIGH_VOL | BULL | VOLATILE_TREND_BULL | +0.6x (long) |
| TRENDING | HIGH_VOL | BEAR | VOLATILE_TREND_BEAR | -0.6x (short) |
| TRENDING | HIGH_VOL | FLAT | VOLATILE_TREND_FLAT | 0.0x (flat) |
| NON_TRENDING | LOW_VOL | -- | QUIET_MR_RANGE | +0.3x (long) |
| NON_TRENDING | LOW_VOL | -- (sqz) | QUIET_MR_SQUEEZE | 0.0x (flat) |
| NON_TRENDING | HIGH_VOL | -- | CHOPPY | 0.0x (skip) |

**BCPD -> HMM feedback loop:** When `changepoint_prob > signal_threshold`, the orchestrator
calls `hmm_classifier.force_retrain()` **before** the HMM classifies, so the current bar
gets a freshly retrained model (no 1-bar stale delay).

---

## 2. Data Contracts (`models.py`)

### `HMMState`
Output of `HMMClassifier`. Contains:
- `p_trending: float` -- P(TRENDING | data[0:t]), forward-filtered (no hindsight)
- `p_non_trending: float` -- 1 - p_trending
- `hmm_regime: str` -- "TRENDING" | "NON_TRENDING" | "MEAN_REVERTING" | "CRISIS"
- `model_age_bars: int` -- bars since last retrain
- `metadata: Dict` -- state means, covariances, BIC, n_states (for diagnostics)

### `VolState`
Output of `VolOverlay`. Contains:
- `vol_percentile: float` -- 0-100 rolling vol rank
- `vol_regime: str` -- "LOW_VOL" | "HIGH_VOL"
- `rolling_vol: float` -- raw rolling std (for adaptive params)

### `ChangePointSignal`
Output of `ChangeDetector`. Contains:
- `change_point_prob: float` -- P(changepoint at bar t | data[0:t])
- `run_length: int` -- estimated bars since last structural break
- `magnitude: float` -- KL-divergence magnitude of the break
- `entropy: float` -- run-length distribution entropy
- `change_detected: bool` -- True if prob > signal_threshold

### `RegimeFeatures`
Final output consumed by the trading bot. Flat struct:
- **Labels**: `regime`, `p_trending`, `vol_percentile`, `changepoint_prob`, `adaptive_period`
- **Trading params**: `position_scale`, `atr_multiplier`, `holding_period`
- **Raw component states**: `hmm_state`, `vol_state`, `change_signal`, `hilbert_period`, `hilbert_confidence`

---

## 3. Component Breakdown

### A. `MarketStructure` (`market_structure.py`) [NEW]
Cross-asset preprocessing layer.

- **`infer_asset_type(symbol)`**: Auto-detects crypto/stock/fx from symbol name
  - Crypto suffixes (USDT, BUSD, etc.) -> crypto
  - Contains '/' (EUR/USD) -> fx
  - Otherwise -> stock
- **`preprocess(df)`**: Attenuates stock overnight gap returns by `gap_attenuation` (0.3x)
  - Gap detected when bar delta > `gap_threshold_mult` (2.0x) * median delta
  - Crypto/FX: pass-through (24/7 and 24/5 markets)
- **Config:** `MarketStructureConfig(asset_type, gap_attenuation=0.3, gap_threshold_mult=2.0)`

### B. `RegimeOrchestrator` (`orchestrator.py`)
The entry point and wiring layer.

- **`analyze(df) -> RegimeFeatures`**: Full pipeline for single analysis window.
  Runs MarketStructure preprocessing, all 4 layers, aggregator, then optional MTF fusion.
- **`analyze_series(df) -> pd.DataFrame`**: Vectorized path for backtesting/historical.
  Calls `_series` variants of all components, aligns outputs by index.
- **`create(asset, timeframe, **overrides) -> RegimeOrchestrator`**: Factory class method.
  Loads config from `regime.yaml`, applies asset+timeframe overrides, auto-scales params
  for timeframe via `_scale_defaults_for_timeframe()`, instantiates all components.
- **`reset_state()`**: Resets HMM model and internal state (for walk-forward CV splits).
- **Timeframe-aware scaling**: `timeframe_to_hours()` converts TF strings to hours.
  Window-based params auto-scaled by `bar_hours / reference_hours` ratio.
  Walk-forward purge gap = `ceil(24 / bar_hours)`.
- **BCPD->HMM retrain trigger**: In `_run_layers()`, if `cp.change_point_prob > signal_threshold`,
  calls `self.hmm_classifier.force_retrain()` before aggregation.

### C. `HMMClassifier` (`hmm_classifier.py`)
N-state GaussianHMM with BIC model selection and Student-t robust scoring.

**BIC model selection (new):**
- When `hmm_n_states=0` (default): fits models with 2 to `hmm_max_states` (4) states
- Selects the model with lowest BIC score
- States beyond 2: TRENDING, NON_TRENDING, MEAN_REVERTING, CRISIS
- Fixed mode: set `hmm_n_states=2` for backward-compatible 2-state behavior

**Student-t robust scoring (new):**
- When `hmm_robust_scoring=true`: replaces Gaussian log-likelihood with Student-t
- `hmm_student_df=5.0` controls tail heaviness (lower = heavier tails)
- Prevents state posteriors from snapping to 0/1 on outlier observations
- Implementation: `scipy.stats.t.logpdf()` on standardized residuals

**Feature construction:**
```python
log_returns = log(close / close.shift(1))
log_vol     = log(log_returns.rolling(log_vol_lookback).std())
hurst       = rolling_rs_hurst(log_returns, hurst_lookback)
X = np.column_stack([log_returns, log_vol, hurst])   # shape (T, 3+)
```

**State labeling (non-hindsight, post-fit) -- 3-signal majority vote:**
```
Signal 1 (2 votes): |mean(log_return)| per state
    -> TRENDING has non-zero drift; MR/choppy mean ~ 0
Signal 2 (1 vote):  run-level directional efficiency
    -> DE computed within consecutive state runs (not trailing windows)
Signal 3 (1 vote):  lag-1 autocorrelation within contiguous state runs
    -> Computed only on sequential bars within the same state run (>=10 bars)
    -> TRENDING has positive autocorr (momentum); MR tends negative
```

**Config:** `HMMConfig(retrain_window, min_train_bars, log_vol_lookback, hurst_lookback, use_hurst, hmm_n_states, hmm_max_states, hmm_covariance_type, hmm_robust_scoring, hmm_student_df)`

### D. `VolOverlay` (`vol_overlay.py`)
Orthogonal realized-volatility percentile rank with hysteresis.

```python
rolling_vol = log_returns.rolling(lookback).std()
percentile  = rolling_vol.rolling(rank_window).rank(pct=True) * 100
# Hysteresis band prevents flickering at boundary
if current == "LOW_VOL":
    vol_regime = "HIGH_VOL" if percentile > high_percentile + hysteresis_band else "LOW_VOL"
else:
    vol_regime = "LOW_VOL" if percentile < high_percentile - hysteresis_band else "HIGH_VOL"
```

**Config:** `VolConfig(lookback=168, high_percentile=70.0, rank_window=1000, hysteresis_band=2.0)`

### E. `ChangeDetector` (`change_detector.py`)
Multi-channel BCPD with Weibull hazard and bounded z-score.

**Multi-channel (new):** 3 independent BCPD channels, fused via `max()`:
1. Returns channel: MAD-standardized log-returns (always active)
2. Volume channel: log volume change (requires `volume` column)
3. Range channel: log(high/low) (requires `high`, `low` columns)

**Weibull hazard (new):** `h(r) = (k/lambda)(r/lambda)^(k-1)`
- `bcpd_hazard_shape=1.0`: constant hazard (backward-compatible, exponential)
- `bcpd_hazard_shape>1.0`: increasing hazard (longer runs more likely to end)

**Bounded z-score (fix):** Uses `rolling(zscore_max_window=2000)` instead of expanding window.
Prevents sensitivity decay over long series where expanding std dilutes recent volatility.

**Config:**
```python
ChangeDetectorConfig(
    hazard_lambda=150.0,    # expected run length between breaks
    hazard_shape=1.0,       # Weibull shape parameter
    alpha=1.0, beta=1.0,    # Normal-Gamma prior
    signal_threshold=0.35,  # P(CP) above which is_signal=True
    zscore_max_window=2000, # bounded rolling z-score window
    min_periods=20,
    truncation=500,
    multichannel=True,      # enable 3-channel BCPD
)
```

### F. `HilbertCycle` (`kernels/hilbert_cycle.py`)
Ehlers Homodyne Discriminator -- causal dominant cycle estimator.

**Replaced:** Previous `scipy.signal.hilbert` was FFT-based (non-causal, leaked future data
via bidirectional transform and global mean centering).

**Current:** 7-tap causal FIR Hilbert transform (Ehlers, "Cybernetic Analysis" 2004).
Extracts in-phase and quadrature components, derives instantaneous period via homodyne
discrimination. Strictly causal -- every computation uses only current and past bars.

- `min_period` / `max_period`: clamp bounds (default 10/40, use 20+/100+ for stocks)
- `stability_bars`: trailing bars for rolling median/confidence (default 10)

### G. `FeatureAggregator` (`aggregation/rule_based.py`)
Rule-based fusion of 4 layers into 9 regime labels. See [aggregator.md](aggregator.md).

### H. `MTFFusion` (`mtf_fusion.py`) [NEW]
Multi-timeframe regime fusion. Fuses higher TF regime into execution TF.

**Agreement classification:**
- `CONFIRMING`: both TFs agree (both trending or both non-trending) -> boost position_scale by `confirmation_boost` (1.2x, capped at 1.0)
- `CONFLICTING`: TFs disagree (one trending, one not) -> penalty `conflict_penalty` (0.5x)
- `SUPPRESSING`: higher TF is CHOPPY -> penalty regardless of lower TF

**Config:** `MTFConfig(higher_tf="", higher_tf_weight=0.4, conflict_penalty=0.5, confirmation_boost=1.2)`

Disabled by default (`higher_tf=""`). Enable by setting e.g. `mtf_higher_tf: "4h"` in regime.yaml.

---

## 4. Configuration (`config/regime.yaml`)

Single YAML file. Full defaults section:

```yaml
defaults:
  # Core 7 (original optimizable)
  hmm_retrain_window: 1000
  vol_lookback: 168
  vol_high_percentile: 70
  bcpd_hazard_lambda: 150
  bcpd_signal_threshold: 0.35
  hurst_lookback: 100
  min_dwell_bars: 5

  # BCPD enhancements
  bcpd_hazard_shape: 1.0          # Weibull: 1.0=constant, >1.0=increasing
  bcpd_multichannel: true          # 3-channel BCPD
  bcpd_zscore_max_window: 2000     # Bounded rolling z-score

  # HMM enhancements
  hmm_n_states: 0                  # 0=auto-BIC, 2-5=fixed
  hmm_max_states: 4
  hmm_covariance_type: "full"
  hmm_robust_scoring: true
  hmm_student_df: 5.0
  hmm_log_vol_lookback: 24

  # Vol overlay
  vol_hysteresis_band: 2.0
  vol_rank_window: 1000

  # Aggregator
  cp_position_decay: 0.5

  # Hilbert
  hilbert_stability_bars: 10

  # Market structure
  market_structure_gap_attenuation: 0.3
  market_structure_gap_threshold_mult: 2.0

  # MTF fusion (disabled by default)
  mtf_higher_tf: ""
  mtf_higher_tf_weight: 0.4
  mtf_conflict_penalty: 0.5
  mtf_confirmation_boost: 1.2

assets:
  BTCUSDT:
    1h:
      bcpd_hazard_lambda: 131.75
      bcpd_signal_threshold: 0.46
      ...
```

---

## 5. Optimization Framework (`optimization/`)

Bayesian hyperparameter optimization using Optuna + walk-forward CV.

### Search Space (10 params)
| Param | Range | Notes |
|-|-|-|
| `bcpd_hazard_lambda` | [50, 200] | Cap 200: higher suppresses transitions |
| `bcpd_signal_threshold` | [0.20, 0.60] | |
| `bcpd_hazard_shape` | [0.8, 2.0] | Weibull shape (NEW) |
| `vol_high_percentile` | [65, 85] | Floor 65: lower over-classifies HIGH_VOL |
| `vol_lookback` | [48, 336] | |
| `vol_hysteresis_band` | [1.0, 5.0] | Vol classification hysteresis (NEW) |
| `hmm_retrain_window` | [300, 2000] | |
| `hmm_student_df` | [3.0, 15.0] | Student-t tail heaviness (NEW) |
| `hurst_lookback` | [50, 200] | |
| `min_dwell_bars` | [3, 15] | |

### 5-Tier Objective Function

| Tier | Name | Weight | Description |
|-|-|-|-|
| 1 | Strategy Utility | 50% | position_scale-weighted Sharpe + drawdown vs buy-and-hold |
| 2 | Predictive Power | 40% | Spearman IC at 4-bar horizon + vol RMSE + IC decay |
| 3 | Statistical Validity | GATE | Levene's test + Cohen's d (soft penalty if p > 0.05) |
| 4 | Stability | CONSTRAINT | avg_regime_duration >= 5, flip_flop_rate <= 0.15 (0.3x penalty) |
| 5 | CP Quality | 10% | Precision/recall/lag vs vol_regime transition ground truth |

**Tier 2 regime names fixed:** Now uses correct 9-label taxonomy (CLEAN_TREND_BULL/BEAR/FLAT, etc.) for regime rank -> forward return IC computation.

### Walk-Forward CV
- **Train:** 4320 bars (~6 months at 1h)
- **Test:** 720 bars (~1 month at 1h)
- **Step:** 720 bars (rolling, not expanding)
- **Purge:** `ceil(24 / bar_hours)` bars (timeframe-aware, 24 bars at 1h)

### 3-Stage Hierarchical Optimization
1. **Stage 1** (40 trials): BCPD params only (hazard_lambda, signal_threshold, hazard_shape)
2. **Stage 2** (40 trials): Vol + HMM params (fix BCPD at Stage 1 best)
3. **Stage 3** (70 trials): Full 10-param polish, narrow bounds +/-20% around Stage 1+2 bests

---

## 6. Usage

```python
from app.regime import RegimeOrchestrator
import pandas as pd, numpy as np

# Create orchestrator (loads regime.yaml for BTCUSDT 1h)
orch = RegimeOrchestrator.create("BTCUSDT", "1h")

# Single analysis window
features = orch.analyze(df)  # -> RegimeFeatures
print(features.regime, features.p_trending, features.position_scale)

# Full time-series (backtesting)
df_out = orch.analyze_series(df)  # -> pd.DataFrame
print(df_out[["regime", "p_trending", "vol_percentile", "changepoint_prob", "adaptive_period"]].tail())
```

### Bot Brain Integration
- **`features.regime`**: Primary directional gate. `CHOPPY` -> skip all trades.
- **`features.position_scale`**: Long-short position sizing multiplier (-1.0 to 1.0, negative = short).
- **`features.atr_multiplier`**: Stop-loss/TP distance multiplier.
- **`features.adaptive_period`**: RSI/BB period for downstream indicators.
- **`features.changepoint_prob`**: Emergency risk gate. If > 0.8, reduce size immediately.

---

## 7. Public Exports (`__init__.py`)

```python
from app.regime import (
    RegimeOrchestrator,
    HMMClassifier, HMMConfig, HMMState,
    VolOverlay, VolConfig, VolState,
    ChangeDetector, ChangeDetectorConfig,
    FeatureAggregator, AggregatorConfig, BaseAggregator,
    ChangePointSignal, RegimeFeatures,
    MarketStructure, MarketStructureConfig,
    MTFFusion, MTFConfig,
)
```

---

## 8. Testing

72 tests passing:

```bash
.venv/bin/python -m pytest app/regime/tests/ -v
```

Test files:
- `test_hmm_classifier.py` -- N-state HMM, BIC selection, Student-t scoring
- `test_vol_overlay.py` -- Vol percentile + hysteresis
- `test_orchestrator.py` -- Full pipeline integration, market structure, MTF
- `test_adaptive_periods.py` -- 2-tier adaptive period logic
- `test_hilbert_integration.py` -- Ehlers causal Hilbert + orchestrator
- `test_timeframe_scaling.py` -- Timeframe-aware param scaling
