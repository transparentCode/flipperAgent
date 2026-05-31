# Regime Module -- High-Level Design

## Motivation

Regime detection exists to make strategy parameters (position size, stops, holding period, indicator periods) adapt to market conditions rather than staying fixed.

The module answers one question per bar:
> "What is the current market regime, and how should the strategy adapt?"

## Design Principles

1. **Non-hindsight** -- every computation uses only data up to bar *t*
2. **Minimal config** -- single YAML, auto-scaled per timeframe
3. **Interpretable** -- 9 discrete regime labels with clear trading semantics
4. **Orthogonal layers** -- each detector measures a different property
5. **Cross-asset** -- market structure handler adapts for crypto/stock/fx

## Architecture

```
app/regime/
|
|  [Pre-process] MarketStructure
|      Auto-infers crypto/stock/fx from symbol name.
|      Attenuates stock overnight gap returns by 0.3x.
|      Crypto/FX: pass-through (24/7 and 24/5 markets).
|      See: market_structure.py
|
|  [Layer 1] ChangeDetector (BCPD)
|      Detects structural breaks in the return distribution.
|      Non-hindsight: Adams & MacKay (2007) forward message passing.
|      Multi-channel: 3 independent channels (returns, volume-change, range),
|        fused via max(). Config: bcpd_multichannel=true
|      Weibull hazard: h(r)=(k/L)(r/L)^(k-1). Shape k=1.0 is constant
|        (backward-compat), k>1.0 = increasing hazard with run length.
|      Bounded z-score: rolling(2000) instead of expanding (prevents decay).
|      Output: changepoint_prob, run_length
|      See: change_detector.py, kernels/changepoint/core.py
|
|  [Layer 2] HMMClassifier (N-state GaussianHMM)
|      Identifies directional regime via BIC model selection (2-4 states).
|      States: TRENDING, NON_TRENDING, MEAN_REVERTING, CRISIS (3+ state mode)
|      Features: [log_return, log_vol, hurst, (volume)]
|      BIC auto-selection: fits 2 to hmm_max_states models, picks lowest BIC.
|      Student-t robust scoring: fat-tail-aware state posteriors (scipy.stats.t).
|      State labeled by 3-signal composite vote (no look-ahead):
|        1. |mean(log_return)| per state -- 2 votes (drift signal)
|        2. Run-level directional efficiency -- 1 vote
|        3. Lag-1 autocorrelation within contiguous runs -- 1 vote
|      classify_series() uses rolling segmented retraining.
|      BCPD fires -> force_retrain() called BEFORE classify (same-bar fresh model).
|      Output: p_trending, hmm_regime
|      See: hmm_classifier.py
|
|  [Layer 3] VolOverlay
|      Classifies volatility level: LOW_VOL vs HIGH_VOL.
|      Rolling vol -> percentile rank -> threshold with hysteresis band.
|      vol_hysteresis_band=2.0 prevents flickering at boundary.
|      Completely orthogonal to HMM.
|      Output: vol_percentile, vol_regime
|      See: vol_overlay.py
|
|  [Layer 4] HilbertCycle (Ehlers Causal FIR)
|      Estimates dominant market cycle period.
|      Ehlers Homodyne Discriminator (7-tap FIR, strictly causal, no FFT).
|      Replaced: scipy.signal.hilbert was FFT-based (non-causal, leaked future).
|      Used only for adaptive indicator periods.
|      Output: dominant_period, confidence
|      See: kernels/hilbert_cycle.py
|
|  [Aggregator] FeatureAggregator
|      Combines 4 layers into a single regime label + trading params.
|      Rule-based, no learned weights. 9 output labels.
|      See: aggregation/rule_based.py
|
|  [MTF Fusion] MTFFusion (optional)
|      Fuses higher TF regime into execution TF position_scale.
|      Hierarchical override:
|        CONFIRMING  -> boost 1.2x
|        CONFLICTING -> penalty 0.5x
|        SUPPRESSING -> penalty (higher TF is CHOPPY)
|      Disabled by default (mtf_higher_tf="").
|      See: mtf_fusion.py
|
'-- RegimeOrchestrator
        Wires all layers, market structure, and MTF fusion.
        Timeframe-aware: auto-scales default params by TF ratio.
        Entry point for consumers.
        See: orchestrator.py
```

## Combined Regime Labels (9)

The system uses 9 discrete regimes by combining HMM trend state, VolOverlay state, and a Direction overlay:

```
                         LOW_VOL                    HIGH_VOL
TRENDING          CLEAN_TREND (Bull/Bear/Flat)   VOLATILE_TREND (Bull/Bear/Flat)
NON_TRENDING      QUIET_MR (Range/Squeeze)       CHOPPY
```

Trading semantics:
- **CLEAN_TREND_BULL/BEAR**: full-size trend following, direction aligned
- **CLEAN_TREND_FLAT**: trending but direction indeterminate, reduced scale
- **VOLATILE_TREND_BULL/BEAR/FLAT**: reduced-size trend (wide stops), direction aligned
- **QUIET_MR_RANGE**: mean-reversion fade (tight stops, shorter hold)
- **QUIET_MR_SQUEEZE**: vol contracting (potential breakout setup, scale down)
- **CHOPPY**: flat -- erratic high vol, skip all trades

## Data Flow

```
DataFrame(close, volume, high, low)
     |
     v
MarketStructure.preprocess(df)
     |  attenuate gaps (stocks only)
     |
     +---> ChangeDetector.detect(df)          --> ChangePointSignal
     |         Multi-channel BCPD: max(returns, volume, range)
     |         Weibull hazard + bounded rolling z-score
     |
     +---> HMMClassifier.classify(df)         --> HMMState
     |         N-state GaussianHMM (BIC selected)
     |         Student-t robust scoring
     |         triggered retrain if BCPD fires
     |
     +---> VolOverlay.compute(df)             --> VolState
     |         rolling std -> percentile rank + hysteresis
     |
     +---> HilbertCycle.calculate(prices)     --> (period, confidence)
               Ehlers causal FIR -> inst. frequency -> period
     |
     v
FeatureAggregator.aggregate(hmm, vol, cp, period, conf)
     |
     v
RegimeFeatures
     |
     v
MTFFusion.fuse(features, higher_tf_features) [if mtf_higher_tf set]
     |
     v
Final RegimeFeatures (position_scale adjusted)
```

## Config Resolution

```
runtime overrides  >  assets.{SYMBOL}.{TF} in regime.yaml  >  defaults in regime.yaml  >  dataclass defaults
```

Single file: `app/regime/config/regime.yaml`

Timeframe-aware scaling: `_scale_defaults_for_timeframe()` auto-scales window-based params by `timeframe_to_hours(tf) / 1.0` ratio relative to 1h reference. Walk-forward purge = `ceil(24h / bar_hours)`.

## BCPD -> HMM Feedback

When `changepoint_prob > signal_threshold`:
1. `HMMClassifier.force_retrain()` is called **before** `classify()`
2. The HMM is refitted on the latest `retrain_window` bars on the **same** bar
3. This ensures the regime output is immediately updated after a structural break

## Regime Hysteresis (Dwell Time)

Minimum `min_dwell_bars=5` before regime label can switch:
- Prevents costly whipsaw trades from rapid flip-flops
- Configurable per asset/timeframe via `regime.yaml`

## Vol Hysteresis Band

`vol_hysteresis_band=2.0` creates a +/- dead zone around `vol_high_percentile`:
- Transition LOW_VOL -> HIGH_VOL only when percentile > threshold + band
- Transition HIGH_VOL -> LOW_VOL only when percentile < threshold - band
- Prevents flickering at the vol classification boundary

## Continuous p_trending Blending

```python
# position_scale uses HMM probability as continuous weight
blended = p_trending * trending_scale + (1 - p_trending) * non_trending_scale
position_scale = blended * cp_decay
```
Regime label stays discrete (for logging/diagnostics), but position sizing uses the continuous gradient.

## Adaptive Period Logic

```python
# 2 tiers -- Hilbert first, regime fallback
if hilbert_confidence >= 0.70:
    scale = hilbert_period / bb_base        # direct Hilbert period
else:
    scale = regime_scale[regime]            # CLEAN=1.0, VOLATILE=0.75, MR=1.25, CHOPPY=0.5

period = max(5, round(bb_base * clamp(scale, 0.5, 2.0)))
```

## Why This Architecture

**Why N-state HMM with BIC instead of fixed 2-state?**
- BIC auto-selects the right complexity for the data (2-4 states)
- Additional states (MEAN_REVERTING, CRISIS) capture finer market structure
- Full backward compatibility: 2-state mode identical to prior behavior

**Why Student-t robust scoring?**
- Financial returns have fat tails; Gaussian scoring underweights extreme observations
- Student-t with df=5.0 gives heavier tails, preventing state posteriors from snapping to 0/1 on outliers
- Configurable: `hmm_robust_scoring=true`, `hmm_student_df=5.0`

**Why multi-channel BCPD?**
- Single-channel (returns only) misses volume-driven and range-driven regime shifts
- 3 channels (returns, volume-change, range) capture complementary structural breaks
- Fusion via max() ensures any channel detecting a break triggers the signal

**Why Weibull hazard?**
- Constant hazard (exponential, shape=1.0) assumes memoryless run lengths
- Increasing hazard (shape>1.0) models the prior that longer runs are more likely to end
- Backward compatible: shape=1.0 recovers the original constant hazard

**Why causal Hilbert (Ehlers FIR)?**
- scipy.signal.hilbert uses a bidirectional FFT -- leaks future data into past estimates
- Ehlers Homodyne Discriminator is a 7-tap causal FIR filter -- strictly non-hindsight

**Why market structure preprocessing?**
- Stock overnight gaps produce outsized log-returns that trigger false BCPD changepoints
- Attenuating gap returns (0.3x) preserves directional info while preventing false positives
- Auto-inference from symbol name means no manual asset-type configuration

**Why MTF fusion?**
- Higher TF regimes provide structural context that execution TF cannot see
- Hierarchical override prevents trading against the dominant trend
- Disabled by default; opt-in via `mtf_higher_tf` config param

## Extension Points

- **New assets**: add entry to `regime.yaml` assets section
- **New aggregation logic**: implement `BaseAggregator` and inject into `RegimeOrchestrator`
- **Custom HMM features**: extend `HMMClassifier._build_features()`
- **Alternative CP detector**: replace `ChangeDetector` while keeping the interface
- **Custom MTF strategy**: replace `MTFFusion` with alternative fusion logic
