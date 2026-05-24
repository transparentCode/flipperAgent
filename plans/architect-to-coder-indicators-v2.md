# Architect to Coder Handoff: Indicator Expansion (v2)

## 1. Intent & Scope
**Objective:** Expand the `libs/features` module with complex multi-line, volatility, and volume-weighted indicators.
**Scale/Depth:** Implement MACD (Momentum), ATR (Volatility), Bollinger Bands (Volatility), Supertrend (Trend), and VWAP (Volume). Maintain absolute strictness to the Dual-Mode Parity execution model and Numba vectorization.

## 2. Directory Structure Target
```text
/libs
  /features
    /indicators
      /momentum
        macd.py
      /trend
        supertrend.py
      /volatility
        atr.py
        bollinger.py
      /volume
        vwap.py
```

## 3. High-Level Requirements

### A. MACD (Moving Average Convergence Divergence)
- **Math:** 12-period EMA minus 26-period EMA. Signal line is 9-period EMA of the MACD line.
- **State:** Must track internal states for the fast EMA, slow EMA, and signal EMA during `.update()`.

### B. ATR (Average True Range)
- **Math:** 14-period smoothed moving average (RMA/Wilder's) of True Range (max of high-low, abs(high-prev_close), abs(low-prev_close)).
- **State:** Requires passing `(high, low, close)` tuples or structured arrays. The `.batch()` method must accept 2D arrays.

### C. Bollinger Bands
- **Math:** 20-period SMA, Upper Band (+2 StdDev of SMA), Lower Band (-2 StdDev of SMA).
- **State:** `.update()` must track a rolling window buffer of size 20 to compute variance continuously.

### D. Supertrend
- **Math:** ATR-based volatility bands trailing the price. Computes basic bands `(high + low) / 2 ± (multiplier * ATR)`, moving the active band only in the direction of the trend unless broken.
- **State:** Requires ATR composition internally. Must maintain state for the current trend direction (1 or -1), previous final upper/lower bands, and previous close.

### E. VWAP (Volume Weighted Average Price)
- **Math:** $\frac{\sum (\text{Typical Price} \times \text{Volume})}{\sum \text{Volume}}$. Typical price is usually `(High + Low + Close) / 3`.
- **State Constraint (Session Anchoring):** VWAP typically resets at the start of a new trading session. `.update()` must accept `(high, low, close, volume, timestamp)` so it can automatically reset cumulative volume and typical price accumulators upon date rollover.

## 4. Parity Testing
- Extend `tests/integration/features/test_indicator_parity.py` for all five new indicators.
- Guarantee Numba `@njit(cache=True)` is used for all `.batch()` array heavy lifting.
- VWAP parity tests MUST include date rollovers inside the random walk or simulated data to verify anchor resets.
