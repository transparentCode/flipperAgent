# RegimeOrchestrator

Top-level entry point for the regime detection module.

## Overview

`RegimeOrchestrator` wires the 4 independent layers into a single callable API:

| Layer          | Class             | Measures                    |
|----------------|-------------------|-----------------------------|
| BCPD           | ChangeDetector    | Structural breaks           |
| HMM            | HMMClassifier     | TRENDING / NON_TRENDING     |
| Vol Overlay    | VolOverlay        | LOW_VOL / HIGH_VOL          |
| Hilbert Cycle  | HilbertCycle      | Dominant cycle period       |

## Usage

```python
from app.regime import RegimeOrchestrator

# Create with per-asset config loading
orch = RegimeOrchestrator.create("BTCUSDT", "1h")

# Single-bar output
features = orch.analyze(df)          # RegimeFeatures

# Full series output
df_out = orch.analyze_series(df)     # DataFrame with all columns

# Reset HMM state (e.g. between backtest folds)
orch.reset_state()
```

## Factory

```python
@classmethod
def create(cls, asset=None, timeframe=None, **overrides) -> RegimeOrchestrator
```

Loads all layer configs from `app/regime/config/regime.yaml` with per-asset/TF overrides. Runtime `**overrides` have highest priority.

Example with overrides:
```python
orch = RegimeOrchestrator.create(
    "BTCUSDT", "1h",
    bcpd_hazard_lambda=200,
    vol_high_percentile=75,
)
```

## analyze()

```python
def analyze(self, df: pd.DataFrame) -> RegimeFeatures
```

Runs all 4 layers sequentially on `df`, then aggregates. `df` must have a `close` column. Volume is optional.

Execution order:
1. `ChangeDetector.detect(df)` → ChangePointSignal
2. **[Feedback Loop]** If changepoint probability > threshold, call `HMMClassifier.force_retrain()`
3. `HMMClassifier.classify(df)` → HMMState (freshly retrained if CP detected)
4. `VolOverlay.compute(df)` → VolState
5. `HilbertCycle.calculate(df['close'].values)` → (period, confidence)
6. `FeatureAggregator.aggregate(...)` → RegimeFeatures

## analyze_series()

```python
def analyze_series(self, df: pd.DataFrame) -> pd.DataFrame
```

Runs each layer over the full series and aggregates. Output columns:

| Column               | Description                                |
|----------------------|--------------------------------------------|
| `regime`             | CLEAN_TREND / VOLATILE_TREND / QUIET_MR / CHOPPY |
| `p_trending`         | HMM probability of TRENDING state         |
| `vol_percentile`     | Rolling vol percentile rank (0–100)        |
| `changepoint_prob`   | BCPD changepoint probability               |
| `adaptive_period`    | Hilbert / regime-derived indicator period  |
| `position_scale`     | -1.0 to 1.0 (long-short, continuous p_trending blending) |
| `vol_regime`         | LOW_VOL / HIGH_VOL                         |
| `hilbert_period`     | Raw Hilbert dominant period estimate       |
| `hilbert_confidence` | Hilbert period confidence (0–1)            |
| `bcpd_signal`        | Binary BCPD signal (1 = changepoint fired) |
| `bcpd_prob_returns`  | Per-channel BCPD prob (returns) — multichannel only |
| `bcpd_prob_volume`   | Per-channel BCPD prob (volume) — multichannel only |
| `bcpd_prob_range`    | Per-channel BCPD prob (range) — multichannel only |
| `trend_direction`    | BULL / BEAR / FLAT (ROC direction overlay) |

## analyze_series_mtf()

```python
def analyze_series_mtf(
    self,
    df_primary: pd.DataFrame,
    df_higher: pd.DataFrame,
    higher_timeframe: str = "4h",
    mtf_config: Optional[MTFConfig] = None,
) -> pd.DataFrame
```

Runs regime on both primary and higher TFs, then fuses via `MTFFusion`. Creates a second orchestrator for the higher TF with auto-scaled params. Output includes all `analyze_series()` columns plus `mtf_agreement` and adjusted `position_scale`.

## reset_state()

```python
def reset_state(self) -> None
```

Clears the HMM model (forces refit on next classify call). Use between backtest folds to prevent state leakage.

## BCPD → HMM Feedback

Inside `_run_layers()`:
```python
cp = self.change_detector.detect(df)
if cp.change_point_prob > self.change_detector.config.signal_threshold:
    self.hmm_classifier.force_retrain()
hmm_state = self.hmm_classifier.classify(df)
```

This ensures the HMM adapts immediately after a structural break is detected, **before** classifying the current bar, rather than waiting for the scheduled `retrain_window` or having a 1-bar stale output.

## Timeframe-Aware Scaling

When using default params (no asset-specific overrides), window-based params are auto-scaled by TF ratio relative to 1h:

```python
scale = 1.0 / timeframe_to_hours(tf)  # 15m -> 4x, 4h -> 0.25x
hmm_retrain_window *= scale
vol_lookback *= scale
min_dwell_bars *= scale
```

Walk-forward purge gap is also scaled: `purge_bars = ceil(24 / bar_hours)`.

## Market Structure Integration

The factory auto-infers asset type from symbol name (crypto/stock/fx) and passes a `MarketStructure` instance to `ChangeDetector`. Stock overnight gap returns are attenuated by 0.3x to prevent false BCPD triggers.
