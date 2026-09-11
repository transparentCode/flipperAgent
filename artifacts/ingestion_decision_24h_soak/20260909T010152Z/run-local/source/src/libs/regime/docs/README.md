# Regime Detection Module

4-layer market regime detection pipeline with multi-asset support, multi-timeframe fusion, and Bayesian optimization.

## Architecture

```
RegimeOrchestrator
    |-- MarketStructure      (auto-infers crypto/stock/fx, attenuates gaps)
    |-- ChangeDetector       (BCPD -- multi-channel, Weibull hazard)
    |-- HMMClassifier        (N-state GaussianHMM, BIC selection, Student-t scoring)
    |-- VolOverlay           (rolling vol percentile with hysteresis)
    |-- HilbertCycle         (Ehlers causal FIR Homodyne Discriminator)
    |-- FeatureAggregator    (rule-based 9-regime combination)
    '-- MTFFusion            (optional higher-TF regime overlay)
```

Pipeline flow:

```
DataFrame(close, volume, high, low)
     |
     v
MarketStructure.preprocess()     -- attenuate stock overnight gaps
     |
     +---> ChangeDetector.detect()           --> ChangePointSignal
     |         Multi-channel BCPD (returns + volume + range)
     |         Weibull hazard, bounded rolling z-score
     |
     +---> HMMClassifier.classify()          --> HMMState
     |         N-state GaussianHMM (BIC auto-select 2-4)
     |         Student-t robust scoring
     |         BCPD triggers force_retrain()
     |
     +---> VolOverlay.compute()              --> VolState
     |         Rolling vol percentile + hysteresis band
     |
     +---> HilbertCycle.calculate()          --> (period, confidence)
     |         Ehlers causal FIR (no lookahead)
     |
     v
FeatureAggregator.aggregate()    --> RegimeFeatures (9 labels)
     |
     v
MTFFusion.fuse() [optional]      --> adjusted position_scale
```

## 9 Combined Regime Labels

```
                         LOW_VOL                    HIGH_VOL
TRENDING          CLEAN_TREND (Bull/Bear/Flat)   VOLATILE_TREND (Bull/Bear/Flat)
NON_TRENDING      QUIET_MR (Range/Squeeze)       CHOPPY
```

Full labels: `CLEAN_TREND_BULL`, `CLEAN_TREND_BEAR`, `CLEAN_TREND_FLAT`, `VOLATILE_TREND_BULL`, `VOLATILE_TREND_BEAR`, `VOLATILE_TREND_FLAT`, `QUIET_MR_RANGE`, `QUIET_MR_SQUEEZE`, `CHOPPY`

## Quick Start

```python
from app.regime import RegimeOrchestrator

orch = RegimeOrchestrator.create("BTCUSDT", "1h")

# Single-bar output
features = orch.analyze(df)
print(features.regime)          # "CLEAN_TREND_BULL"
print(features.p_trending)      # 0.82
print(features.position_scale)  # 1.0

# Full series output
df_out = orch.analyze_series(df)
# Columns: regime, p_trending, vol_percentile, changepoint_prob,
#          adaptive_period, position_scale, vol_regime,
#          hilbert_period, hilbert_confidence, bcpd_signal,
#          bcpd_prob_returns, bcpd_prob_volume, bcpd_prob_range (if multichannel)
```

## Output Contracts

### RegimeFeatures

```python
@dataclass
class RegimeFeatures:
    timestamp: pd.Timestamp
    regime: str               # 9-label (CLEAN_TREND_BULL, ..., CHOPPY)
    p_trending: float         # HMM: P(TRENDING | data[0:t])
    vol_percentile: float     # 0-100 rolling vol rank
    changepoint_prob: float   # BCPD: P(changepoint at t)
    adaptive_period: int      # Hilbert-derived or regime-fallback
    position_scale: float     # -1.0 to 1.0 (negative=short, BULL=1.0, BEAR=-1.0, CHOPPY=0.0)
    atr_multiplier: float
    holding_period: int
    hmm_state: HMMState
    vol_state: VolState
    change_signal: ChangePointSignal
    hilbert_period: float
    hilbert_confidence: float
```

### ChangePointSignal
```python
change_point_prob: float   # 0.0-1.0
run_length: int            # Bars since last detected CP
magnitude: float           # |standardised return| at detection
change_detected: bool      # True when prob > signal_threshold
```

### HMMState
```python
p_trending: float          # P(TRENDING | data[0:t]) -- non-hindsight
p_non_trending: float
hmm_regime: str            # "TRENDING" | "NON_TRENDING" | "MEAN_REVERTING" | "CRISIS"
model_age_bars: int        # Bars since last retrain
```

### VolState
```python
vol_percentile: float      # 0-100
vol_regime: str            # "LOW_VOL" | "HIGH_VOL"
rolling_vol: float
```

## Regime Trading Parameters

| Regime | position_scale | atr_multiplier | holding_period |
|-|-|-|-|
| CLEAN_TREND_BULL | +1.0 | 2.0 | 20 bars |
| CLEAN_TREND_BEAR | -1.0 | 2.0 | 20 bars |
| CLEAN_TREND_FLAT | 0.0 | 2.0 | 20 bars |
| VOLATILE_TREND_BULL | +0.6 | 3.5 | 10 bars |
| VOLATILE_TREND_BEAR | -0.6 | 3.5 | 10 bars |
| VOLATILE_TREND_FLAT | 0.0 | 3.5 | 8 bars |
| QUIET_MR_RANGE | +0.3 | 1.5 | 8 bars |
| QUIET_MR_SQUEEZE | 0.0 | 1.5 | 5 bars |
| CHOPPY | 0.0 | 2.5 | 3 bars |

Position scale is further decayed by `changepoint_prob` when a BCPD transition fires, and adjusted by MTF fusion when enabled.

## Adaptive Period

2-tier Hilbert-based adaptive period for RSI/BB indicators:

```
if hilbert_confidence >= 0.70:
    scale = hilbert_period / bb_base          # Level 1: direct Hilbert
else:
    scale = regime_scale[regime]              # Level 2: regime fallback
period = max(5, round(bb_base * clamp(scale, 0.5, 2.0)))
```

## Configuration

Single YAML: `app/regime/config/regime.yaml`

10 core optimizable params (+ additional fixed params):

| Parameter | Default | Range |
|-|-|-|
| `bcpd_hazard_lambda` | 150 | 50-200 |
| `bcpd_signal_threshold` | 0.35 | 0.20-0.60 |
| `bcpd_hazard_shape` | 1.0 | 0.8-2.0 |
| `bcpd_multichannel` | true | -- |
| `bcpd_zscore_max_window` | 2000 | -- |
| `vol_high_percentile` | 70 | 65-85 |
| `vol_lookback` | 168 | 48-336 |
| `vol_hysteresis_band` | 2.0 | 1.0-5.0 |
| `vol_rank_window` | 1000 | -- |
| `hmm_retrain_window` | 1000 | 300-2000 |
| `hmm_n_states` | 0 (auto-BIC) | -- |
| `hmm_max_states` | 4 | -- |
| `hmm_covariance_type` | "full" | -- |
| `hmm_robust_scoring` | true | -- |
| `hmm_student_df` | 5.0 | 3.0-15.0 |
| `hmm_log_vol_lookback` | 24 | -- |
| `hurst_lookback` | 100 | 50-200 |
| `min_dwell_bars` | 5 | 3-15 |
| `cp_position_decay` | 0.5 | -- |
| `hilbert_stability_bars` | 10 | -- |
| `market_structure_gap_attenuation` | 0.3 | -- |
| `market_structure_gap_threshold_mult` | 2.0 | -- |
| `mtf_higher_tf` | "" (disabled) | -- |
| `mtf_higher_tf_weight` | 0.4 | -- |
| `mtf_conflict_penalty` | 0.5 | -- |
| `mtf_confirmation_boost` | 1.2 | -- |

### Key Features
- **Hurst exponent**: Rolling R/S Hurst as HMM feature (H>0.5 trending, H<0.5 MR)
- **Regime hysteresis**: Minimum dwell time before regime label can switch (prevents whipsaws)
- **Continuous p_trending**: Position scale blends between trending/non-trending using HMM probability
- **Multi-channel BCPD**: 3 independent channels (returns, volume-change, range), fused via max()
- **Weibull hazard**: Configurable hazard shape (1.0=constant, >1.0=increasing)
- **Student-t robust scoring**: Fat-tail-aware state posteriors for HMM
- **BIC model selection**: Auto-selects 2-4 HMM states based on BIC
- **Market structure**: Auto-infers crypto/stock/fx, attenuates stock overnight gaps
- **MTF fusion**: Optional higher-TF regime overlay (CONFIRMING/CONFLICTING/SUPPRESSING)
- **Timeframe-aware scaling**: Default params auto-scaled by TF ratio to reference 1h

## Directory Structure

```
app/regime/
|-- __init__.py
|-- models.py                 # ChangePointSignal, HMMState, VolState, RegimeFeatures
|-- change_detector.py        # ChangeDetector (multi-channel BCPD, Weibull hazard)
|-- hmm_classifier.py         # HMMClassifier (N-state, BIC, Student-t scoring)
|-- vol_overlay.py            # VolOverlay (rolling vol percentile + hysteresis)
|-- market_structure.py       # MarketStructure (crypto/stock/fx gap handling)
|-- mtf_fusion.py             # MTFFusion (higher-TF regime overlay)
|-- orchestrator.py           # RegimeOrchestrator (wires all layers + MTF)
|-- config_validator.py       # RegimeConfigValidator
|-- config/
|   '-- regime.yaml           # Single config file
|-- aggregation/
|   |-- base.py               # BaseAggregator ABC
|   '-- rule_based.py         # FeatureAggregator (9-regime combination)
|-- kernels/
|   |-- __init__.py
|   |-- hilbert_cycle.py      # Ehlers causal FIR Homodyne Discriminator
|   |-- hurst.py              # Rolling R/S Hurst exponent
|   '-- changepoint/
|       |-- __init__.py
|       '-- core.py           # NumPy BCPD (Weibull hazard, no Numba)
|-- optimization/
|   |-- __init__.py
|   |-- models.py             # BenchmarkResults, OptimizationConfig, etc.
|   |-- optimizer.py          # RegimeOptimizer (Optuna, 10 params)
|   |-- walk_forward.py       # WalkForwardValidator
|   '-- benchmarks/
|       |-- strategy_utility.py    # Tier 1 (50%)
|       |-- predictive_power.py    # Tier 2 (40%)
|       |-- statistical_validity.py # Tier 3 GATE
|       |-- stability.py           # Tier 4 CONSTRAINT
|       '-- changepoint_quality.py # Tier 5 (10%)
|-- scripts/
|   |-- run_optimization.py
|   |-- monitor_optimization.py
|   |-- benchmark_adaptive_periods.py
|   '-- test_tsla_regime.py
|-- tests/                    # 72 tests passing
|   |-- test_hmm_classifier.py
|   |-- test_vol_overlay.py
|   |-- test_orchestrator.py
|   |-- test_adaptive_periods.py
|   |-- test_hilbert_integration.py
|   '-- test_timeframe_scaling.py
'-- docs/
    |-- README.md
    |-- hld.md
    |-- optimization.md
    |-- orchestrator.md
    |-- aggregator.md
    '-- complete_context_overview.md
```

## Testing

```bash
.venv/bin/python -m pytest app/regime/tests/ -v
# 72 tests passing
```

## See Also

- [HLD](hld.md) -- Architecture and data flow
- [Optimization](optimization.md) -- Hyperparameter tuning
- [Orchestrator](orchestrator.md) -- Orchestrator API
- [Aggregator](aggregator.md) -- 9-regime labels and trading params
