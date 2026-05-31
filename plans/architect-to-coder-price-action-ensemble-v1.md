---
goal: Implement PriceAction scoring model — a pure price-geometry ensemble orthogonal to oscillator-based models, targeting QUIET_RANGE alpha
stage: architect-to-coder
date_created: 2026-05-31
last_updated: 2026-05-31
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, price-action, scoring-model, ensemble, kernels, regime-ensemble]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: PriceAction Ensemble Model v1

## 1. Objective

Implement a `PriceActionModel` — a `ScoringModel` subclass that produces continuous
`edge_score` from pure OHLCV price geometry, orthogonal to all existing
oscillator-based models (MR, Momentum, SqueezeBreakout).

**Why:**
- Momentum (Sharpe +1.22 BTC 1h, 39 trades/6mo) is the only alpha source; MR and SB
  are structurally broken for crypto 1h.
- Momentum Sharpe in QUIET_RANGE = −1.03 (anti-suited), yet QUIET_RANGE = 25% of bars.
- The blender currently wastes ~25% of market time.
- Price action uses different information (swing geometry, candle morphology,
  liquidity structure) and should have low correlation with RSI/MACD/BB indicators.

**Design target:** A model that fires 30–80 meaningful signals per 6 months on BTC 1h,
with positive edge in QUIET_RANGE and neutral-to-positive in other regimes.

---

## 2. Context Retrieved

### Prior Decisions (from memory)
- MR v2 z-score redesign already done; emits continuous `ScoringOutput`.
- Regime Ensemble Blender v2 designed with 6 groups × N models weights.
  Adding a new model = adding one column per group to `blender.weights`.
- Phase 3B research found candle patterns detected at reasonable frequencies
  (engulfing 3%, hammer 10.6%, doji 10.7%) and Pattern Momentum was uncorrelated
  with Momentum (r < 0.13).
- `@ModelRegistry.register("PriceAction")` for discovery.
- `migration_mode: scoring` already exists in `ModelManager`.
- Liquidity models notebook (2026-05-30) proved textbook signals are arbitraged;
  kernels must be combined, not used standalone.

### Confirmed Facts
- BTC 1h data: 4345 bars, OHLCV available, regime labels available.
- Regime distribution: SQUEEZE 40.1%, CHOPPY 26.5%, QUIET_RANGE 25.1%, trends ~8.3%.
- Numba `@njit` pattern established in MR v2 for batch evaluation.
- `FeatureVector.bar_data` provides `open`, `high`, `low`, `close`, `volume`.
- ATR already computed in feature pipeline (can use for normalization).

---

## 3. Kernel Selection (6 kernels for v1)

### Selection Criteria Applied
1. Uses only OHLCV data (no external data)
2. Deterministic — no subjective zone drawing or ML fitting
3. Computationally efficient — O(n) scan, Numba-friendly (no dynamic allocation)
4. Covers both reversal and continuation signals
5. Likely to work in QUIET_RANGE (range-bound price action)
6. Prior research supports candle morphology detection at useful frequencies

### Selected Kernels

| # | Kernel | Category | Signal Type | QUIET_RANGE Fit | Rationale |
|---|--------|----------|-------------|-----------------|-----------|
| K1 | **Fair Value Gap (FVG)** | Institutional | Reversal/Continuation | HIGH | 3-candle gap is deterministic; price fills FVGs in ranges. Highly testable. |
| K2 | **Liquidity Sweep** | Liquidity | Reversal | HIGH | Wick beyond swing high/low + rejection. Classic range reversal. |
| K3 | **Pin Bar / Rejection** | Candle Morphology | Reversal | HIGH | Long wick at level = rejection. High frequency in ranges. |
| K4 | **Engulfing** | Candle Morphology | Reversal/Momentum | MEDIUM | Full body engulf = momentum shift. Works in all regimes. |
| K5 | **Break of Structure (BOS)** | Structure | Continuation | MEDIUM | HH/HL or LL/LH break. Primary trend signal, pairs with reversal kernels. |
| K6 | **Inside Bar Breakout** | Candle Morphology | Continuation | HIGH | Compression → expansion. Natural range-break signal. |

### Rejected Kernels (with rationale)

| Kernel | Reason |
|--------|--------|
| CHoCH / MSS | Requires multi-swing tracking; too complex for v1; can be added in v2 as BOS extension |
| Equal Highs/Lows | Fuzzy "equal" definition (tolerance param) makes it semi-subjective |
| Order Block | Requires identifying "last opposite candle before impulse" — lookahead contamination risk in batch mode |
| Breaker Block | Requires tracking failed OBs — too stateful for v1 |
| Displacement Candle | Overlaps with Engulfing + FVG; redundant |
| Session/Key Level | No session data in current OHLCV pipeline |
| Swing Reclaim | Requires multi-bar swing tracking; planned for v2 |
| Absorption | Requires tick-level volume analysis; 1h volume too coarse |
| Wyckoff Phase | Multi-bar state machine; too complex for v1 |
| Double Top/Bottom | Well-known to be arbitraged at 1h frequency (per liquidity notebook findings) |
| Consolidation Squeeze | Overlaps with existing SqueezeBreakout model |
| Trap Candle | Variant of liquidity sweep; covered by K2 |
| Momentum Exhaustion | Requires volume-body relationship analysis; add in v2 |
| Gap / Opening Range | Crypto is 24/7; no meaningful session gaps |

---

## 4. Kernel Mathematical Specifications

All kernels emit a **kernel score** in the range **[-1.0, +1.0]** where:
- Positive = bullish bias
- Negative = bearish bias
- 0 = no signal

Scores represent **normalized signal strength**, not direction probability.

### 4.1 Swing Point Detection (Shared Prerequisite)

All structure/liquidity kernels need swing highs and swing lows. Use a simple
N-bar pivot detection:

```
swing_high[i] = True if high[i] == max(high[i-N:i+N+1])  # confirmed at bar i+N
swing_low[i]  = True if low[i]  == min(low[i-N:i+N+1])   # confirmed at bar i+N
```

**Parameters:**
- `swing_lookback` (N): default 5 (look 5 bars left and right)
- **Confirmation delay:** swing is confirmed N bars after its actual position.
  In batch mode, this is handled by shifting. In live mode, we need N bars
  of future data, so the most recent confirmed swing is always N bars old.
  This is NOT lookahead — we only use confirmed (past) swings.

**State tracked:**
- `last_swing_high_price: float` — price of most recent confirmed swing high
- `last_swing_high_idx: int` — bar index of that swing high
- `last_swing_low_price: float` — price of most recent confirmed swing low
- `last_swing_low_idx: int` — bar index of that swing low

### 4.2 K1: Fair Value Gap (FVG)

**Definition:** A 3-candle formation where C1.high < C3.low (bullish FVG) or
C1.low > C3.high (bearish FVG). The gap between C1 and C3 is the "fair value gap"
that price tends to fill.

```
Bullish FVG at bar i:
  gap_size = low[i] - high[i-2]     # C3.low - C1.high
  fvg_bullish = gap_size > 0

Bearish FVG at bar i:
  gap_size = low[i-2] - high[i]     # C1.low - C3.high
  fvg_bearish = gap_size > 0

Score:
  if fvg_bullish:
    k1 = +min(1.0, gap_size / (atr[i] * fvg_atr_scale))
  elif fvg_bearish:
    k1 = -min(1.0, gap_size / (atr[i] * fvg_atr_scale))
  else:
    k1 = 0.0
```

**Parameters:**
- `fvg_atr_scale`: float, default 1.0 (gap size normalized by ATR; 1 ATR gap = score ±1.0)

**Lookback:** 2 bars.

### 4.3 K2: Liquidity Sweep

**Definition:** Price wicks beyond the most recent swing high/low, then closes
back inside. This is a stop-hunt reversal pattern.

```
Bullish sweep at bar i (sweep of swing low):
  swept = low[i] < last_swing_low_price
  rejected = close[i] > last_swing_low_price
  wick_ratio = (close[i] - low[i]) / (high[i] - low[i] + 1e-10)

  if swept and rejected:
    k2 = +min(1.0, wick_ratio * sweep_wick_scale)
  else:
    k2 = 0.0  (check bearish)

Bearish sweep at bar i (sweep of swing high):
  swept = high[i] > last_swing_high_price
  rejected = close[i] < last_swing_high_price
  wick_ratio = (high[i] - close[i]) / (high[i] - low[i] + 1e-10)

  if swept and rejected:
    k2 = -min(1.0, wick_ratio * sweep_wick_scale)
```

**Parameters:**
- `sweep_wick_scale`: float, default 1.5 (wick_ratio multiplier; wick=67% of range → score ±1.0)

**Lookback:** Depends on swing detection (swing_lookback + recency of last swing).

### 4.4 K3: Pin Bar / Rejection

**Definition:** A candle with a long wick relative to its body, indicating rejection
at a price level.

```
body = abs(close[i] - open[i])
range_ = high[i] - low[i]
upper_wick = high[i] - max(open[i], close[i])
lower_wick = min(open[i], close[i]) - low[i]

if range_ < atr[i] * pin_min_range_atr:
    k3 = 0.0  # too small to be meaningful

elif lower_wick > body * pin_wick_body_ratio and lower_wick > upper_wick * pin_wick_dominance:
    # Bullish pin bar (long lower wick, small upper wick)
    k3 = +min(1.0, (lower_wick / range_) * pin_strength_scale)

elif upper_wick > body * pin_wick_body_ratio and upper_wick > lower_wick * pin_wick_dominance:
    # Bearish pin bar (long upper wick, small lower wick)
    k3 = -min(1.0, (upper_wick / range_) * pin_strength_scale)

else:
    k3 = 0.0
```

**Parameters:**
- `pin_wick_body_ratio`: float, default 2.0 (wick must be 2× body)
- `pin_wick_dominance`: float, default 1.5 (dominant wick 1.5× other wick)
- `pin_min_range_atr`: float, default 0.3 (candle must be at least 30% of ATR)
- `pin_strength_scale`: float, default 1.5 (wick/range=67% → score ±1.0)

**Lookback:** 0 bars (current bar only).

### 4.5 K4: Engulfing

**Definition:** Current candle's body fully engulfs the previous candle's body.

```
prev_body_high = max(open[i-1], close[i-1])
prev_body_low  = min(open[i-1], close[i-1])
curr_body_high = max(open[i], close[i])
curr_body_low  = min(open[i], close[i])

prev_body_size = prev_body_high - prev_body_low
curr_body_size = curr_body_high - curr_body_low

bullish_engulf = (
    curr_body_low < prev_body_low
    and curr_body_high > prev_body_high
    and close[i] > open[i]
    and curr_body_size > atr[i] * engulf_min_body_atr
)

bearish_engulf = (
    curr_body_low < prev_body_low
    and curr_body_high > prev_body_high
    and close[i] < open[i]
    and curr_body_size > atr[i] * engulf_min_body_atr
)

if bullish_engulf:
    k4 = +min(1.0, curr_body_size / (prev_body_size + 1e-10) * engulf_ratio_scale)
elif bearish_engulf:
    k4 = -min(1.0, curr_body_size / (prev_body_size + 1e-10) * engulf_ratio_scale)
else:
    k4 = 0.0
```

**Parameters:**
- `engulf_min_body_atr`: float, default 0.5 (engulfing body must be ≥ 50% of ATR)
- `engulf_ratio_scale`: float, default 0.5 (body ratio 2:1 → score ±1.0)

**Lookback:** 1 bar.

### 4.6 K5: Break of Structure (BOS)

**Definition:** Price breaks above the most recent swing high (bullish BOS) or
below the most recent swing low (bearish BOS), confirming trend continuation.

```
Bullish BOS at bar i:
  broken = close[i] > last_swing_high_price and close[i-1] <= last_swing_high_price
  displacement = (close[i] - last_swing_high_price) / (atr[i] + 1e-10)

  if broken:
    k5 = +min(1.0, displacement * bos_displacement_scale)

Bearish BOS at bar i:
  broken = close[i] < last_swing_low_price and close[i-1] >= last_swing_low_price
  displacement = (last_swing_low_price - close[i]) / (atr[i] + 1e-10)

  if broken:
    k5 = -min(1.0, displacement * bos_displacement_scale)
```

**Parameters:**
- `bos_displacement_scale`: float, default 1.0 (1 ATR displacement = score ±1.0)

**Lookback:** Depends on swing detection.

### 4.7 K6: Inside Bar Breakout

**Definition:** Current bar's range is fully contained within the previous bar's
range (inside bar). On the NEXT bar, a breakout is detected.

```
# Detect inside bar at bar i-1 relative to bar i-2
is_inside = high[i-1] <= high[i-2] and low[i-1] >= low[i-2]

if is_inside:
    # Breakout detection on bar i
    if close[i] > high[i-1]:
        k6 = +min(1.0, (close[i] - high[i-1]) / (atr[i] * ib_breakout_scale + 1e-10))
    elif close[i] < low[i-1]:
        k6 = -min(1.0, (low[i-1] - close[i]) / (atr[i] * ib_breakout_scale + 1e-10))
    else:
        k6 = 0.0  # inside bar but no breakout yet
else:
    k6 = 0.0
```

**Parameters:**
- `ib_breakout_scale`: float, default 0.5 (0.5 ATR breakout = score ±1.0)

**Lookback:** 2 bars.

---

## 5. Ensemble Scoring Formula

### Architecture: Weighted Sum with Confluence Bonus

```
raw_score = Σ(w_k * k_score)  for k in [K1..K6]

# Confluence bonus: when multiple kernels agree in direction,
# the combined signal is more reliable
n_agreeing = count(k_score_i * sign(raw_score) > 0)  # kernels agreeing with majority
confluence_bonus = 1.0 + confluence_scale * max(0, n_agreeing - confluence_min)

edge_score = raw_score * confluence_bonus
```

**Why weighted sum + confluence, not max-vote or stacking:**
1. **Weighted sum** preserves continuous signal strength (required for `ScoringOutput`).
2. **Max-vote** would discard conviction magnitude information.
3. **Confluence bonus** rewards agreement without killing individual kernel signals.
4. **Stacking (ML)** is a non-goal for v1 (deterministic only).

**Parameters:**
- `w_fvg`: float, default 0.20
- `w_sweep`: float, default 0.25
- `w_pin`: float, default 0.15
- `w_engulf`: float, default 0.15
- `w_bos`: float, default 0.15
- `w_inside`: float, default 0.10
- `confluence_scale`: float, default 0.15 (15% bonus per extra agreeing kernel)
- `confluence_min`: int, default 2 (bonus kicks in at 3+ agreeing kernels)

**Weight rationale:**
- Sweep (0.25): Highest weight — stop-hunt reversal is the most reliable price action pattern in crypto.
- FVG (0.20): Strong institutional flow signal; deterministic; high fill rate.
- Pin/Engulf/BOS (0.15 each): Standard candle/structure signals; moderate reliability.
- Inside Bar (0.10): Lowest weight — compression signals are more frequent but lower conviction per occurrence.

### Conviction Calculation

```
conviction = min(1.0, abs(edge_score) * conviction_scale)
```

**Parameters:**
- `conviction_scale`: float, default 1.0

### Conflict Resolution

Conflicts (e.g., BOS says trend continuation, Sweep says reversal) are handled
naturally by the weighted sum: opposing kernels cancel out, reducing `abs(edge_score)`.
This is the correct behavior — conflicting signals = lower conviction, not forced choice.

---

## 6. Hyperparameter Schema (18 parameters)

```python
hyperparameter_schema = {
    # Swing detection
    "swing_lookback": ParamDef(type="int", default=5, low=3, high=10, step=1),

    # K1: FVG
    "fvg_atr_scale": ParamDef(type="float", default=1.0, low=0.3, high=3.0, step=0.1),
    "w_fvg": ParamDef(type="float", default=0.20, low=0.0, high=0.5, step=0.05),

    # K2: Liquidity Sweep
    "sweep_wick_scale": ParamDef(type="float", default=1.5, low=0.5, high=3.0, step=0.1),
    "w_sweep": ParamDef(type="float", default=0.25, low=0.0, high=0.5, step=0.05),

    # K3: Pin Bar
    "pin_wick_body_ratio": ParamDef(type="float", default=2.0, low=1.5, high=4.0, step=0.5),
    "pin_wick_dominance": ParamDef(type="float", default=1.5, low=1.0, high=3.0, step=0.5),
    "pin_min_range_atr": ParamDef(type="float", default=0.3, low=0.1, high=0.8, step=0.1),
    "pin_strength_scale": ParamDef(type="float", default=1.5, low=0.5, high=3.0, step=0.1),
    "w_pin": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),

    # K4: Engulfing
    "engulf_min_body_atr": ParamDef(type="float", default=0.5, low=0.2, high=1.5, step=0.1),
    "engulf_ratio_scale": ParamDef(type="float", default=0.5, low=0.2, high=1.0, step=0.1),
    "w_engulf": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),

    # K5: BOS
    "bos_displacement_scale": ParamDef(type="float", default=1.0, low=0.3, high=3.0, step=0.1),
    "w_bos": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),

    # K6: Inside Bar Breakout
    "ib_breakout_scale": ParamDef(type="float", default=0.5, low=0.2, high=1.5, step=0.1),
    "w_inside": ParamDef(type="float", default=0.10, low=0.0, high=0.3, step=0.05),

    # Ensemble
    "confluence_scale": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),
    "confluence_min": ParamDef(type="int", default=2, low=1, high=4, step=1),
    "conviction_scale": ParamDef(type="float", default=1.0, low=0.5, high=2.0, step=0.1),
}
```

**Optimizability:** 18 parameters (same order of magnitude as MR v2's 6). With Sobol sensitivity
analysis, expect to reduce to ~8–10 active parameters. Kernel weights (6 params) are the
primary tuning target; per-kernel normalization scales are secondary.

---

## 7. State Management

### Problem: Price Action Requires Lookback State

Unlike MR v2 (which is stateless per bar after indicator warmup), price action needs:
1. **Swing high/low positions** — requires confirmed swings from past bars.
2. **Inside bar detection** — needs prior bar's range.

### Approach: Stateless Batch + Minimal Live State

#### Batch Mode (`_batch_evaluate_impl`)

The entire 4345-bar series is processed in a single Numba `@njit` function.
Swing detection is computed as a forward pass within the same function. No
external state needed — the function scans bars sequentially and maintains
swing points as local variables.

```python
@njit(cache=True)
def _batch_price_action(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    atr: np.ndarray,
    # ... all params ...
) -> np.ndarray:
    n = len(close)
    edge = np.empty(n, dtype=np.float64)

    # Rolling swing state (local to function)
    last_sh_price = np.nan
    last_sh_idx = -1
    last_sl_price = np.nan
    last_sl_idx = -1

    for i in range(n):
        # 1. Update confirmed swings (confirmed at i if looking back N bars)
        if i >= 2 * swing_lookback:
            check_idx = i - swing_lookback  # the bar being confirmed
            is_sh = True
            is_sl = True
            for j in range(check_idx - swing_lookback, check_idx + swing_lookback + 1):
                if j != check_idx and j >= 0 and j < n:
                    if high[j] >= high[check_idx]:
                        is_sh = False
                    if low[j] <= low[check_idx]:
                        is_sl = False
            if is_sh:
                last_sh_price = high[check_idx]
                last_sh_idx = check_idx
            if is_sl:
                last_sl_price = low[check_idx]
                last_sl_idx = check_idx

        # 2. Compute each kernel score at bar i
        k1 = _fvg_score(high, low, close, atr, i, fvg_atr_scale)
        k2 = _sweep_score(high, low, close, i, last_sh_price, last_sl_price, sweep_wick_scale)
        k3 = _pin_score(open_, high, low, close, atr, i, ...)
        k4 = _engulf_score(open_, high, low, close, atr, i, ...)
        k5 = _bos_score(close, atr, i, last_sh_price, last_sl_price, bos_displacement_scale)
        k6 = _inside_bar_score(open_, high, low, close, atr, i, ib_breakout_scale)

        # 3. Weighted sum
        raw = (w_fvg * k1 + w_sweep * k2 + w_pin * k3
               + w_engulf * k4 + w_bos * k5 + w_inside * k6)

        # 4. Confluence bonus
        scores = (k1, k2, k3, k4, k5, k6)
        sign_raw = 1.0 if raw > 0 else (-1.0 if raw < 0 else 0.0)
        n_agree = 0
        for s in scores:
            if s * sign_raw > 0:
                n_agree += 1
        bonus = 1.0 + confluence_scale * max(0, n_agree - confluence_min)

        edge[i] = raw * bonus

    return edge
```

This is **fully deterministic** and **Numba-compatible** — no Python objects, no
dynamic allocation, no dicts. The function receives flat numpy arrays and scalar params.

#### Live Mode (`evaluate`)

For single-tick evaluation, the model maintains minimal state:

```python
class PriceActionModel(ScoringModel):
    def __init__(self, params):
        super().__init__(params)
        # Live state for swing tracking
        self._bar_buffer: list[tuple[float, float, float, float]] = []  # (O,H,L,C)
        self._last_swing_high = (float('nan'), -1)  # (price, idx)
        self._last_swing_low = (float('nan'), -1)   # (price, idx)
        self._bar_count = 0
```

On each `evaluate()` call:
1. Append current bar to `_bar_buffer` (ring buffer of `min_history_bars` bars).
2. Check if a swing is confirmed `swing_lookback` bars ago.
3. Update `_last_swing_high` / `_last_swing_low`.
4. Compute all 6 kernel scores using current bar + state.
5. Return `ScoringOutput`.

The ring buffer is bounded at `min_history_bars` (default 30). Memory: ~960 bytes.

### Lookback Requirements

| Component | Min Bars | Note |
|-----------|----------|------|
| Swing detection | `2 * swing_lookback` = 10 | Before first confirmed swing |
| FVG | 2 | Needs bars i-2, i-1, i |
| Inside Bar | 2 | Needs bars i-2, i-1, i |
| Sweep / BOS | swing_lookback + recency | Needs at least one confirmed swing |
| **Total min_history_bars** | **20** | Conservative: 2 × swing_lookback + padding |

Set `min_history_bars = 20` in `ModelMeta`.

---

## 8. Integration Plan

### 8.1 Module Structure

```
src/libs/models/price_action/
├── __init__.py         # Re-export PriceActionModel
├── model.py            # PriceActionModel class
├── kernels.py          # @njit kernel functions + _batch_price_action
└── (no other files)
```

### 8.2 Model Registration

```python
# model.py
@ModelRegistry.register("PriceAction")
class PriceActionModel(ScoringModel):
    meta = ModelMeta(
        name="PriceAction",
        model_type="scoring",
        required_indicators=["ATR"],          # only ATR for normalization
        required_fields=["ATR"],
        hyperparameter_schema={...},          # 18 params from section 6
        min_history_bars=20,
    )
```

### 8.3 Config Addition (models.yaml)

Add under each asset/timeframe where enabled. Start with BTC 1h only:

```yaml
models:
  assets:
    BTCUSDT:
      timeframes:
        1h:
          PriceAction:
            enabled: true
            migration_mode: scoring
            params:
              swing_lookback: 5
              # Kernel params use defaults from hyperparameter_schema
              # Override only after backtest validation
```

### 8.4 Model Loading

`ModelManager` already handles `migration_mode: scoring`. When it encounters
`PriceAction` in config, it will:
1. Look up `ModelRegistry._registry["PriceAction"]` → `PriceActionModel`
2. Instantiate with params from config
3. Call `evaluate()` or `batch_evaluate()` as needed

No changes to `ModelManager` needed — the existing `ScoringModel` path handles this.

### 8.5 Blender Integration

When `RegimeEnsembleBlender` is implemented (separate handoff), add `price_action`
weights per regime group:

```yaml
blender:
  weights:
    CLEAN_TREND:
      mean_reversion: 0.10
      momentum: 0.45
      squeeze_breakout: 0.25
      price_action: 0.20      # BOS kernel contributes in trends
    VOLATILE_TREND:
      mean_reversion: 0.40
      momentum: 0.15
      squeeze_breakout: 0.20
      price_action: 0.25      # Sweep/pin reversal signals at volatile extremes
    QUIET_RANGE:
      mean_reversion: 0.35
      momentum: 0.05
      squeeze_breakout: 0.15
      price_action: 0.45      # PA's sweet spot: sweeps, pins, FVGs, inside bars
    SQUEEZE:
      mean_reversion: 0.10
      momentum: 0.20
      squeeze_breakout: 0.45
      price_action: 0.25      # Inside bar breakout + FVG during compression
    CHOPPY:
      mean_reversion: 0.20
      momentum: 0.05
      squeeze_breakout: 0.40
      price_action: 0.35      # Sweep + pin reversal thrive in chop
    TRANSITION:
      mean_reversion: 0.25
      momentum: 0.25
      squeeze_breakout: 0.25
      price_action: 0.25      # Equal weights during uncertainty
```

**Weight rationale:**
- **QUIET_RANGE (0.45):** PA's primary design target. Sweep, pin, FVG, and inside
  bar are all range-reversal or range-breakout patterns. This is where PA should
  contribute most and where Momentum is anti-suited (Sharpe −1.03).
- **CHOPPY (0.35):** Similar logic — chop rewards reversal signals.
- **VOLATILE_TREND (0.25):** Sweep and pin at volatile extremes can catch reversals.
- **SQUEEZE (0.25):** Inside bar breakout naturally pairs with squeeze expansion.
- **CLEAN_TREND (0.20):** BOS kernel adds value in smooth trends, but Momentum
  already dominates here.
- **TRANSITION (0.25):** Equal uncertainty weights; decay handles risk reduction.

---

## 9. Scope Boundaries

### In Scope
- New module `src/libs/models/price_action/` with `model.py` and `kernels.py`
- `@ModelRegistry.register("PriceAction")` via decorator
- Config entry in `configs/models.yaml` for BTCUSDT 1h
- Unit tests for each kernel + ensemble + edge cases
- Integration test for model loading via `ModelManager`

### Explicit Non-Goals
- NO changes to `BaseModel`, `ScoringModel`, `ModelRegistry`, or `ModelManager`
- NO changes to any existing model (MR, Momentum, SB, TF, DE, RP)
- NO changes to `SelectionLayer`
- NO changes to `SignalWorker` or the feature pipeline
- NO changes to the regime pipeline
- NO new indicators in `features.yaml` (ATR already exists)
- NO blender weight changes in this handoff (separate task after blender is implemented)
- NO Optuna optimization (separate follow-up)
- NO ML or fuzzy matching — all kernels are deterministic
- NO CHoCH, MSS, Order Block, Wyckoff, or other v2 kernels

---

## 10. Affected Symbols, Modules, and Execution Flows

### New Files
| File | Purpose |
|------|---------|
| `src/libs/models/price_action/__init__.py` | Package init, re-export `PriceActionModel` |
| `src/libs/models/price_action/model.py` | `PriceActionModel` class |
| `src/libs/models/price_action/kernels.py` | Numba `@njit` kernel functions |
| `tests/unit/models/price_action/test_kernels.py` | Kernel-level unit tests |
| `tests/unit/models/price_action/test_model.py` | Model integration tests |

### Modified Files
| File | Change | Blast Radius |
|------|--------|-------------|
| `configs/models.yaml` | Add `PriceAction` entry under BTCUSDT 1h | LOW — additive key |

### Unchanged (Confirming Zero Blast Radius)
- `src/libs/models/base.py` — BaseModel ABC unchanged
- `src/libs/models/scoring_base.py` — ScoringModel unchanged
- `src/libs/models/registry.py` — ModelRegistry unchanged (decorator pattern)
- `src/libs/models/mean_reversion/` — unchanged
- `src/libs/models/momentum/` — unchanged
- `src/libs/models/squeeze_breakout/` — unchanged
- `src/libs/selection/` — unchanged
- `src/apps/signal_app/` — unchanged
- `src/apps/strategy_app/` — unchanged (PA is discovered via registry)
- `src/libs/regime/` — unchanged
- `configs/features.yaml` — unchanged (ATR already present)

---

## 11. Implementation Order

### Step 1: Kernel Functions (`kernels.py`)

Implement the 6 `@njit` kernel functions as module-level functions.
Each kernel takes numpy arrays + scalar params and returns a float.

Also implement `_detect_swing_points()` helper (called from within batch function).

Implement `_batch_price_action()` — the main `@njit` function that loops over bars
and calls all kernels.

### Step 2: Model Class (`model.py`)

Implement `PriceActionModel(ScoringModel)` with:
- `meta` class attribute with `ModelMeta`
- `evaluate()` for live single-tick mode (with ring buffer state)
- `_batch_evaluate_impl()` that calls `_batch_price_action()`
- Column extraction from `feature_df` (OHLCV + ATR)

### Step 3: Package Init (`__init__.py`)

```python
from libs.models.price_action.model import PriceActionModel

__all__ = ["PriceActionModel"]
```

### Step 4: Config (`models.yaml`)

Add `PriceAction` entry under BTCUSDT 1h with `enabled: true`,
`migration_mode: scoring`, and default params.

### Step 5: Auto-Registration Import

Ensure `src/libs/models/__init__.py` imports the `price_action` package
so that `@ModelRegistry.register("PriceAction")` fires on startup.
Check how existing models are imported — follow the same pattern.

### Step 6: Unit Tests

**Kernel tests** (`test_kernels.py`):
1. `test_fvg_bullish` — 3-candle bullish gap detected, score > 0
2. `test_fvg_bearish` — 3-candle bearish gap detected, score < 0
3. `test_fvg_no_gap` — overlapping candles, score = 0
4. `test_sweep_bullish` — wick below swing low + close above, score > 0
5. `test_sweep_no_rejection` — wick below but close also below, score = 0
6. `test_pin_bar_bullish` — long lower wick, small body, score > 0
7. `test_pin_bar_too_small` — candle range < min ATR threshold, score = 0
8. `test_engulfing_bullish` — full body engulf + close > open, score > 0
9. `test_engulfing_small_body` — body < min ATR threshold, score = 0
10. `test_bos_bullish_break` — close breaks above swing high, score > 0
11. `test_bos_no_break` — close below swing high, score = 0
12. `test_inside_bar_breakout_up` — inside bar on i-1, close > high[i-1], score > 0
13. `test_inside_bar_no_breakout` — inside bar but close within range, score = 0

**Model tests** (`test_model.py`):
14. `test_meta_attributes` — name, model_type, required_indicators correct
15. `test_batch_warmup` — first `min_history_bars` produce near-zero scores
16. `test_batch_deterministic` — same input → same output
17. `test_confluence_bonus` — 3+ agreeing kernels increase score
18. `test_opposing_kernels_cancel` — conflicting kernels reduce score
19. `test_evaluate_returns_scoring_output` — correct output type and fields
20. `test_model_registry_discovery` — `ModelRegistry.get("PriceAction")` returns class

### Step 7: Integration Test

Verify `PriceActionModel` can be loaded from `models.yaml` config via `ModelManager`,
and that `batch_evaluate` produces a valid `pd.Series` aligned with input DataFrame.

---

## 12. Acceptance Criteria

1. `PriceActionModel` extends `ScoringModel` and emits `ScoringOutput`.
2. `ModelRegistry.get("PriceAction")` returns the model class.
3. `ModelManager` can instantiate from `models.yaml` config with `migration_mode: scoring`.
4. `batch_evaluate()` on 4345-bar BTC 1h data completes in < 2 seconds.
5. Each kernel independently produces non-trivial signal density:
   - FVG: 50–200 non-zero bars per 4345
   - Sweep: 20–80 non-zero bars
   - Pin Bar: 150–400 non-zero bars (per prior research: hammer 10.6%)
   - Engulfing: 50–150 non-zero bars (per prior research: engulfing 3%)
   - BOS: 30–100 non-zero bars
   - Inside Bar: 100–300 non-zero bars
6. Ensemble `edge_score` is continuous and unbounded (not clipped to ±1).
7. Conviction is in [0.0, 1.0].
8. All kernel functions are `@njit(cache=True)`.
9. `min_history_bars = 20` — no signals in warmup period.
10. All 20+ unit tests pass.
11. All existing tests (908+) pass without modification.
12. No lookahead bias: swing detection uses only confirmed (past) pivots.

---

## 13. Validation Checklist

- [ ] `pytest tests/` passes with all existing + new tests
- [ ] `PriceAction` model loaded and evaluated in isolation
- [ ] `_batch_price_action` Numba compiles without errors
- [ ] Edge scores are non-trivial (not all zeros) on BTC 1h 4345-bar data
- [ ] Signal density per kernel matches acceptance criteria ranges
- [ ] No lookahead: swing detection confirmation delay = `swing_lookback` bars
- [ ] Batch and live mode produce identical results on the same input sequence
- [ ] `edge_score` distribution has reasonable spread (not degenerate)
- [ ] No changes to any existing model, contract, or pipeline component
- [ ] Config is additive — removing `PriceAction` entry returns system to pre-change state

---

## 14. Residual Risks and Follow-Ups

| Item | Priority | Notes |
|------|----------|-------|
| Backtest validation | P0 blocking | Must run walk-forward backtest on BTC 1h after implementation to measure Sharpe, signal density, regime-conditional performance |
| Kernel correlation analysis | P1 | Measure pairwise correlation between PA kernels and existing models (Momentum, MR) to confirm orthogonality |
| Blender weight calibration | P1 | Weights in section 8.5 are heuristic; must be validated with IC-based walk-forward after blender implementation |
| Optuna optimization | P2 | 18 params need sensitivity analysis (Sobol) → reduce active set → optimize |
| v2 kernels | P2 | CHoCH, MSS, Swing Reclaim, Momentum Exhaustion can be added as extensions |
| Multi-asset validation | P2 | BTC 1h is primary; validate on ETH 1h, SOL 1h before enabling |
| Live state persistence | P3 | Ring buffer state in `evaluate()` is lost on restart; acceptable for v1 (20 bar warmup) |

---

## 15. Architecture Tradeoffs and Rejected Options

### Option A: Standalone Kernel Models (Rejected)
Each kernel as a separate `ScoringModel` → 6 models × 6 regime groups = 36 blender weights.
**Rejected:** Explodes blender parameter space. Kernels individually have low signal-to-noise; the ensemble is the model.

### Option B: ML Stacking (Rejected)
Train a gradient-boosted model on kernel features.
**Rejected:** Explicit non-goal (deterministic only). Small sample size (4345 bars) guarantees overfit.

### Option C: Event-Driven Binary Signals (Rejected)
Kernels emit 0/1 events, model returns direction only when ≥ K kernels agree.
**Rejected:** Loses conviction magnitude. Hard threshold (K) is another overfit lever. Incompatible with continuous `ScoringOutput`.

### Option D: Weighted Sum + Confluence Bonus (Chosen)
Preserves continuous signal, rewards agreement, compatible with `ScoringOutput` and `RegimeEnsembleBlender`. Confluence bonus is bounded and adds minimal parameters (2: `confluence_scale`, `confluence_min`).

### Internal vs. External Regime Awareness (Decision)
**Decision: External (blender handles it).** The PA model is regime-agnostic internally.
**Rationale:** Adding regime gates inside the model would duplicate logic already in the blender, and would couple the PA model to the regime pipeline. The blender already has per-regime weights that can upweight PA in QUIET_RANGE and downweight in CLEAN_TREND. If regime-internal gating is needed, it's a v2 enhancement after validating blender weights.
