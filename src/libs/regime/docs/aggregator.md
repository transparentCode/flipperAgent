# FeatureAggregator

Rule-based combination of 4 regime layers into `RegimeFeatures`.

## Combined Regime Logic

```
                   LOW_VOL         HIGH_VOL
TRENDING        CLEAN_TREND    VOLATILE_TREND
NON_TRENDING      QUIET_MR         CHOPPY
```

Input decision:
- `hmm_regime == "TRENDING"` → trending axis
- `vol_regime == "HIGH_VOL"` → volatile axis

## Regime Aggregation Flow

```
HMMState            VolState
       |                   |
       v                   v
   [ 2x2 Combination Matrix ]
             |
             v
        (Raw Regime)
             |
             v
    [ Minimum Dwell Filter ]
             |
             v
    [ Continuous Blending + CP Decay ]
             |
             v
   Final Regime & Trading Params
```

## Direction Overlay

A non-hindsight ROC direction signal is computed over `direction_period` bars:
- `ROC > threshold` → BULL
- `ROC < -threshold` → BEAR
- Otherwise → FLAT

When `adaptive_roc=true` (default), threshold = `0.5 × rolling_std(ROC, 100)` instead of fixed.

This splits trending regimes into BULL/BEAR/FLAT sub-labels.

## Trading Parameters (9 labels)

| Regime | position_scale | atr_multiplier | holding_period |
|-|-|-|-|
| CLEAN_TREND_BULL | +1.0 | 2.0 | 20 bars |
| CLEAN_TREND_BEAR | -1.0 | 2.0 | 20 bars |
| CLEAN_TREND_FLAT | 0.0 | 2.0 | 15 bars |
| VOLATILE_TREND_BULL | +0.6 | 3.5 | 10 bars |
| VOLATILE_TREND_BEAR | -0.6 | 3.5 | 10 bars |
| VOLATILE_TREND_FLAT | 0.0 | 3.5 | 8 bars |
| QUIET_MR_RANGE | +0.3 | 1.5 | 8 bars |
| QUIET_MR_SQUEEZE | 0.0 | 1.5 | 5 bars |
| CHOPPY | 0.0 | 2.5 | 3 bars |

## Regime Hysteresis (Minimum Dwell Filter)

To prevent costly whipsaw trades from rapid regime flip-flops, the aggregator applies a minimum dwell filter via `min_dwell_bars` (default: 5).

Once a regime enters, it must hold for at least `min_dwell_bars` before it is allowed to switch to a different regime. If a switch is requested before the dwell is satisfied, the previous regime is held.

## Position Sizing & CP Decay

Position sizing uses **continuous blending** rather than a hard binary gate. Using the HMM's `p_trending` probability:

```python
blended = p_trending * trending_scale + (1 - p_trending) * non_trending_scale
position_scale = blended * cp_decay
```

The base scales (`trending_scale` and `non_trending_scale`) are determined by the volatility state.

### BCPD Decay
When the `ChangeDetector` fires a high-probability changepoint, the position scale is proportionally reduced:
```python
decay = 1.0 - (1.0 - cp_position_decay) * cp_prob   # cp_position_decay=0.5 default
position_scale *= decay
```

## Adaptive Period

2-tier logic using Hilbert confidence:

```python
# Level 1 (high confidence): direct Hilbert period
if hilbert_confidence >= hilbert_high_threshold:  # default 0.70
    scale = hilbert_period / bb_base

# Level 2 (low confidence): regime fallback
else:
    scale = regime_scale[regime]
    # CLEAN_TREND_*=1.0, VOLATILE_TREND_*=0.75, QUIET_MR_*=1.25, CHOPPY=0.5

period = max(5, round(bb_base * clamp(scale, 0.5, 2.0)))
```

## Config

```python
@dataclass(frozen=True)
class AggregatorConfig:
    bb_base: int = 20
    rsi_base: int = 14
    hilbert_high_threshold: float = 0.70
    direction_period: int = 20       # ROC direction window
    bull_roc_thresh: float = 0.02    # fixed threshold (used if adaptive_roc=False)
    adaptive_roc: bool = True        # use 0.5*rolling_std for threshold
    vol_squeeze_pct: float = 30.0    # vol_percentile < this -> SQUEEZE
    position_scale: dict   # per-regime (9 labels)
    atr_multiplier: dict   # per-regime (9 labels)
    holding_period: dict   # per-regime (9 labels)
    cp_position_decay: float = 0.5
    min_dwell_bars: int = 5
```

## API

```python
agg = FeatureAggregator()

# Single-bar
features = agg.aggregate(hmm_state, vol_state, cp_signal, period, confidence)

# Full series (needs pre-computed DataFrames from each layer)
df_out = agg.aggregate_series(hmm_df, vol_df, cp_df, hilbert_periods, hilbert_confidences)
```
