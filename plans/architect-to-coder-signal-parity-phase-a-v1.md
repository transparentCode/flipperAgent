---
goal: Align production SqueezeBreakout model with v4 research (strategy_ms_beta) signal logic — fix three divergences in trend filter, momentum computation, and signal strength voters
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, squeeze-breakout, signal-parity, phase-a, indicators, model]
source_agent: Quant Orchestrator / Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: SqueezeBreakout Signal Parity — Phase A

## 1. Objective

Fix the three divergences between the production `SqueezeBreakoutModel` and the v4 research `strategy_ms_beta` that was validated at Sharpe 1.17–1.62 on BTC 1h. The production model currently uses simplified signal logic that was never validated in research. Aligning these is the prerequisite to any meaningful optimization (Phase B) or deployment (Phase C).

### Why This Matters
- v6 optimization was run against the **wrong signal logic** — its params are meaningless.
- The research alpha (Sharpe 1.17–1.62, SS≥3 filter raising it 38%) was proven with specific entry conditions and SS voters that the production code does not implement.
- Until parity is established, any optimization or live deployment is on an unvalidated strategy.

## 2. Scope Boundaries

### In Scope (Phase A)
1. **Divergence 1 — Trend Filter:** Replace single-KAMA `close > kama` with dual-KAMA crossover (`kama_fast > kama_slow`).
2. **Divergence 2 — Momentum:** Replace `linreg(close)` with TTM-style delta-linreg momentum.
3. **Divergence 3 — Signal Strength Voters:** Replace all 5 current SS voters with the 5 v4-research SS voters (CCI, ADX+DI, A/D, MFI, Momentum-LR).
4. **New indicators:** CCI, ADX (with DI±), MFI, ADLine, Momentum.
5. **Config updates:** `features.yaml`, `models.yaml` for new indicators and hyperparameters.
6. **Test updates:** All affected tests in `test_squeeze_breakout_model.py`.

### Explicit Non-Goals (Deferred)
- **Phase B:** Re-running Optuna optimization with corrected signal logic.
- **Phase B:** Multi-TP execution layer changes.
- **Phase B:** Cross-asset parameter sweeps.
- **NOT in scope:** Changing squeeze detection logic (BB inside KC → squeeze ON; release → signal). This is already correct and matches v4.
- **NOT in scope:** Changing conviction computation (linreg magnitude / ATR). Kept as-is.
- **NOT in scope:** Any changes to other models (MeanReversion, TrendFollowing, Momentum).

---

## 3. Design Decisions

### Decision 1: Dual-KAMA Crossover (Trend Filter)

**Chosen approach:** Add a second KAMA indicator instance in `features.yaml` and consume both in the model.

**Rationale:**
- v4 research explicitly uses `kama_fast = _kama(c, 5)` and `kama_slow = _kama(c, 30)` with crossover — this is the signal logic that produced the validated alpha.
- The existing `KAMA` indicator class already supports configurable `period` param — we just need two instances.
- The `features.yaml` `type:` alias pattern (already used for `EMA_fast` / `EMA_slow`) supports this cleanly.

**Implementation:**
- `features.yaml` gets `KAMA_fast: { type: KAMA, period: 5, fast_period: 2, slow_period: 10 }` and `KAMA_slow: { type: KAMA, period: 30, fast_period: 2, slow_period: 10 }`
- Note: v4 uses `fast_len=2, slow_len=10` for KAMA's internal smoothing constants on BOTH lines — not `slow_period=30` which is the production default.
- Model reads `KAMA_fast` and `KAMA_slow` from features dict. Entry condition becomes `kama_fast > kama_slow` (long) / `kama_fast < kama_slow` (short).

**Rejected alternative:** Keeping single KAMA with `close > kama`. This diverges from validated research and loses the adaptive crossover signal.

### Decision 2: TTM Delta-LinReg Momentum (Inline in Model)

**Chosen approach:** Compute the TTM delta inline in the model's batch path, using a new `Momentum` indicator for the single-tick path's subcomponent needs.

**Rationale:**
- The TTM delta is model-specific composite logic: `delta = close - ((HH+LL)/2 + SMA(close))/2`, then `linreg(delta, period)`.
- Creating a standalone "TTMDelta" indicator would be a one-off class used only by SqueezeBreakout — poor abstraction.
- However, the constituent parts (HH, LL, SMA, linreg) are generic enough. For **batch mode**, these are trivial vectorized pandas operations computed inline. For **live single-tick mode**, the model needs to maintain rolling state (HH/LL window, SMA accumulator, linreg buffer) internally.
- The existing `LinReg` indicator can be reused to compute linreg of the delta series in batch mode.

**Implementation:**
- **Batch path (`_batch_evaluate_impl`):** Compute inline:
  ```python
  hh = high.rolling(mom_period).max()
  ll = low.rolling(mom_period).min()
  sma_c = close.rolling(mom_period).mean()
  midline = (hh + ll) / 2.0
  delta = close - (midline + sma_c) / 2.0
  lr_mom = linreg_series(delta, mom_period)  # rolling linreg of delta
  ```
- **Live path (`evaluate`):** Model maintains internal deques for HH/LL/SMA window + a LinReg instance for delta. This requires the model to track `close`, `high`, `low` history in a bounded deque of size `mom_period`.
- The model no longer reads the `LinReg` feature from the pipeline for its entry decision — it computes its own `lr_mom` from the delta. The pipeline `LinReg` indicator is **removed from `required_indicators`** for SqueezeBreakout.

**Rejected alternative:** New standalone TTMDelta indicator class — overengineered for a model-specific composite. Also rejected: splitting into Momentum + LinReg pipeline indicators, because the delta is not `close - close[period]` but rather a TTM-specific deviation formula.

### Decision 3: New SS Voters via 4 New Indicators + 1 New Indicator

**Chosen approach:** Create 5 new indicator classes (CCI, ADX, MFI, ADLine, Momentum), add them to `features.yaml`, and rewrite SS voters in the model.

**Rationale:**
- The Phase 3B decision (2026-05-26) already approved 7 new indicators including CCI, ADX, MFI, A/D — this is a continuation.
- These are standard technical indicators reusable beyond SqueezeBreakout (TrendFollowing could use ADX, MeanReversion could use MFI/CCI).
- Computing them inline in the model would violate the architectural constraint that indicators compute features and models evaluate them.
- The `Momentum` indicator (`close - close[period]`) is also a generally useful building block.

**The old SS voters are fully replaced, not kept as an option.** The old voters (LinReg direction, RSI range, KAMA slope, squeeze tightness, volume > avg) are not validated by research. There is no reason to maintain two SS scoring systems.

### Decision 4: Hyperparameter Schema Changes

**Old hyperparams removed:** `kama_period`, `kama_fast`, `kama_slow` (these were single-KAMA params)
**New hyperparams:**
| Param | Type | Default | Range | Notes |
|---|---|---|---|---|
| `kama_fast_period` | int | 5 | 3–15 | KAMA fast line lookback |
| `kama_slow_period` | int | 30 | 15–50 | KAMA slow line lookback |
| `mom_period` | int | 20 | 10–30 | TTM delta + linreg period |
| `squeeze_lookback` | int | 1 | 1–5 | Unchanged |
| `ss_threshold` | int | 3 | 0–5 | Unchanged |
| `cci_period` | int | 5 | 3–14 | CCI lookback for SS voter 1 |
| `adx_period` | int | 14 | 7–21 | ADX/DI lookback for SS voter 2 |
| `adx_threshold` | float | 18.0 | 10–30 | ADX minimum for SS voter 2 |
| `ad_sma_period` | int | 21 | 10–30 | SMA period for A/D comparison (SS voter 3) |
| `mfi_period` | int | 14 | 7–21 | MFI lookback for SS voter 4 |
| `mfi_sma_period` | int | 9 | 5–14 | SMA period for MFI comparison (SS voter 4) |
| `mom_lr_period` | int | 14 | 7–21 | LinReg period applied to momentum(10) for SS voter 5 |
| `mom_lr_mom_period` | int | 10 | 5–20 | Momentum lookback for SS voter 5 |

**Note:** In Phase A, use the v4 research defaults verbatim. Phase B will sweep these.

---

## 4. Affected Symbols, Modules, and Execution Flows

### Files to Create (7 new files)

| # | File | Description |
|---|---|---|
| 1 | `src/libs/features/indicators/momentum/cci.py` | CCI indicator |
| 2 | `src/libs/features/indicators/momentum/adx.py` | ADX + Plus DI + Minus DI indicator |
| 3 | `src/libs/features/indicators/momentum/mfi.py` | MFI indicator |
| 4 | `src/libs/features/indicators/momentum/momentum.py` | Simple Momentum (close - close[n]) |
| 5 | `src/libs/features/indicators/volume/ad_line.py` | Accumulation/Distribution Line |
| 6 | `tests/test_cci.py` | CCI unit + parity tests |
| 7 | `tests/test_adx.py` | ADX unit + parity tests |
| 8 | `tests/test_mfi.py` | MFI unit + parity tests |
| 9 | `tests/test_ad_line.py` | A/D Line unit + parity tests |
| 10 | `tests/test_momentum.py` | Momentum unit + parity tests |

### Files to Modify (5 files)

| # | File | Change |
|---|---|---|
| 1 | `src/libs/features/indicators/__init__.py` | Add imports for CCI, ADX, MFI, ADLine, Momentum |
| 2 | `src/libs/models/squeeze_breakout/model.py` | Rewrite entry logic, SS voters, hyperparameter schema, ModelMeta |
| 3 | `configs/features.yaml` | Add KAMA_fast, KAMA_slow (replace single KAMA), add CCI, ADX, MFI, ADLine, Momentum |
| 4 | `configs/models.yaml` | Update SqueezeBreakout params across all asset/timeframe entries |
| 5 | `tests/test_squeeze_breakout_model.py` | Rewrite tests for new entry logic, SS voters, hyperparams |

### Execution Flows Affected
- **Signal pipeline:** `FeatureManager._initialize_indicators()` → new indicators instantiated from `features.yaml`.
- **Feature computation:** `FeatureManager.process_tick()` → new indicator `.update()` calls, new keys in feature dict.
- **Model evaluation:** `SqueezeBreakoutModel.evaluate()` and `_batch_evaluate_impl()` — entry logic and SS scoring rewritten.
- **Optimization:** `Optuna` hyperparameter schema changes — any existing trials are invalidated (expected, Phase B will re-run).

### No Impact To
- Other models (MeanReversion, TrendFollowing, Momentum model).
- Ingestion app, risk app, execution app, portfolio app.
- Signal worker stream mechanics.
- `FeatureManager` class itself (no code changes — config-driven indicator loading).

---

## 5. New Indicator Specifications

### 5A. CCI (Commodity Channel Index)

| Property | Value |
|---|---|
| **File** | `src/libs/features/indicators/momentum/cci.py` |
| **Registry key** | `CCI` |
| **Input type** | `Tuple[float, float, float]` (high, low, close) |
| **Output type** | `float` |
| **Constructor params** | `period: int = 5` |
| **Math** | `TP = (H+L+C)/3; mean_TP = SMA(TP, period); MAD = mean(|TP - mean_TP|); CCI = (TP - mean_TP) / (0.015 * MAD)` |
| **Lookback** | `period` |
| **Batch** | `@njit(cache=True)` vectorized over numpy arrays |
| **Live state** | `deque(maxlen=period)` of TP values, O(1) update via running sum + MAD recomputation (MAD requires full window scan — O(period) per tick, acceptable for small periods like 5) |

### 5B. ADX (Average Directional Index) with DI±

| Property | Value |
|---|---|
| **File** | `src/libs/features/indicators/momentum/adx.py` |
| **Registry key** | `ADX` |
| **Input type** | `Tuple[float, float, float]` (high, low, close) |
| **Output type** | `dict` with keys `{"adx": float, "plus_di": float, "minus_di": float}` |
| **Constructor params** | `period: int = 14` |
| **Math** | Wilder's smoothed TR, +DM, -DM → +DI, -DI → DX → ADX (see v4 `_adx_di`) |
| **Lookback** | `2 * period + 1` |
| **Batch** | `@njit(cache=True)` |
| **Live state** | Running smoothed ATR, +DM, -DM accumulators + ADX accumulator. O(1) per tick via Wilder's smoothing: `smoothed = smoothed - smoothed/period + new_value`. |

**Important:** This indicator returns a dict (multi-line output like BollingerBands/KeltnerChannel). The feature dict will contain `ADX: { "adx": float, "plus_di": float, "minus_di": float }`.

### 5C. MFI (Money Flow Index)

| Property | Value |
|---|---|
| **File** | `src/libs/features/indicators/momentum/mfi.py` |
| **Registry key** | `MFI` |
| **Input type** | `Tuple[float, float, float, float]` (high, low, close, volume) — **4 values** |
| **Output type** | `float` |
| **Constructor params** | `period: int = 14` |
| **Math** | `TP = (H+L+C)/3; raw_MF = TP * volume; if TP > prev_TP: pos_flow += raw_MF else neg_flow += raw_MF; MFR = pos/neg; MFI = 100 - 100/(1+MFR)` |
| **Lookback** | `period + 1` |
| **Batch** | `@njit(cache=True)` |
| **Live state** | `deque(maxlen=period+1)` of (TP, raw_MF) pairs. O(period) update to recompute pos/neg flow over window. |

**Important:** MFI needs volume. The `FeatureManager._get_mapped_input` heuristic will need to map 4-float tuples (HLCV) correctly. Check the existing `TYPE_HINT_FULL_CANDLE` path — it passes 5 values `(O,H,L,C,V)`. MFI should accept `Tuple[float,float,float,float]` = `(H,L,C,V)`. Add a 4-comma type hint check in `_get_mapped_input` OR accept the full 5-tuple and ignore open.

### 5D. ADLine (Accumulation/Distribution Line)

| Property | Value |
|---|---|
| **File** | `src/libs/features/indicators/volume/ad_line.py` |
| **Registry key** | `ADLine` |
| **Input type** | `Tuple[float, float, float, float]` (high, low, close, volume) |
| **Output type** | `float` (cumulative A/D value) |
| **Constructor params** | None (no period) |
| **Math** | `CLV = ((C-L) - (H-C)) / (H-L); AD[i] = AD[i-1] + CLV * volume` |
| **Lookback** | `0` (cumulative, no lookback needed) |
| **Batch** | `@njit(cache=True)` |
| **Live state** | Single `float` accumulator. O(1) per tick. |

**Note:** The SS voter compares `AD > SMA(AD, 21)`. The SMA of AD must be computed by the model (inline) or as a separate feature. **Recommendation:** Compute inline in the model — `SMA(AD, ad_sma_period)` is a trivial rolling mean that the model can maintain in a deque. This avoids a custom "SMA-of-ADLine" indicator.

### 5E. Momentum

| Property | Value |
|---|---|
| **File** | `src/libs/features/indicators/momentum/momentum.py` |
| **Registry key** | `Momentum` |
| **Input type** | `float` (close) |
| **Output type** | `float` |
| **Constructor params** | `period: int = 10` |
| **Math** | `momentum = close - close[period ago]` |
| **Lookback** | `period` |
| **Batch** | `@njit(cache=True)` |
| **Live state** | `deque(maxlen=period+1)`. O(1) per tick. |

---

## 6. Model Changes — `model.py`

### 6.1 ModelMeta Update

```python
meta = ModelMeta(
    name="SqueezeBreakout",
    required_indicators=[
        "KAMA_fast", "KAMA_slow",
        "BollingerBands", "KeltnerChannel",
        "CCI", "ADX", "ADLine", "MFI", "Momentum",
    ],
    required_fields=[
        "KAMA_fast", "KAMA_slow",
        "BollingerBands_upper", "BollingerBands_lower",
        "KeltnerChannel_upper", "KeltnerChannel_lower",
        "CCI", "ADX", "ADLine", "MFI", "Momentum",
    ],
    hyperparameter_schema={
        "kama_fast_period": ParamDef(type="int", default=5, low=3, high=15, step=1),
        "kama_slow_period": ParamDef(type="int", default=30, low=15, high=50, step=1),
        "mom_period": ParamDef(type="int", default=20, low=10, high=30, step=1),
        "squeeze_lookback": ParamDef(type="int", default=1, low=1, high=5, step=1),
        "ss_threshold": ParamDef(type="int", default=3, low=0, high=5, step=1),
        "cci_period": ParamDef(type="int", default=5, low=3, high=14, step=1),
        "adx_period": ParamDef(type="int", default=14, low=7, high=21, step=1),
        "adx_threshold": ParamDef(type="float", default=18.0, low=10.0, high=30.0, step=1.0),
        "ad_sma_period": ParamDef(type="int", default=21, low=10, high=30, step=1),
        "mfi_period": ParamDef(type="int", default=14, low=7, high=21, step=1),
        "mfi_sma_period": ParamDef(type="int", default=9, low=5, high=14, step=1),
        "mom_lr_period": ParamDef(type="int", default=14, low=7, high=21, step=1),
        "mom_lr_mom_period": ParamDef(type="int", default=10, low=5, high=20, step=1),
    },
    min_history_bars=50,  # increased: ADX needs 2*14+1=29, plus linreg warmup
)
```

### 6.2 Entry Logic Changes

**Before (production):**
```python
if squeeze_release and linreg is not None and kama is not None:
    if linreg > 0 and close > kama:
        direction = 1
    elif linreg < 0 and close < kama:
        direction = -1
```

**After (v4-aligned):**
```python
if squeeze_release and kama_fast is not None and kama_slow is not None and lr_mom is not None:
    if kama_fast > kama_slow and lr_mom > 0:
        direction = 1
    elif kama_fast < kama_slow and lr_mom < 0:
        direction = -1
```

Where `lr_mom` is the TTM delta-linreg value computed internally by the model (not read from the feature pipeline).

### 6.3 TTM Delta-LinReg (Momentum) — Internal Computation

#### Batch path (`_batch_evaluate_impl`):
```python
# TTM delta-linreg momentum
high = feature_df.get("high")  # from bar_data columns
low = feature_df.get("low")
mom_period = self.params["mom_period"]
hh = high.rolling(mom_period, min_periods=mom_period).max()
ll = low.rolling(mom_period, min_periods=mom_period).min()
sma_c = close.rolling(mom_period, min_periods=mom_period).mean()
midline = (hh + ll) / 2.0
delta = close - (midline + sma_c) / 2.0
lr_mom = self._rolling_linreg(delta.values, mom_period)  # helper using _compute_linreg_batch
```

The model needs a static helper `_rolling_linreg` that wraps the existing `_compute_linreg_batch` from the LinReg module. Import and reuse the numba kernel:
```python
from libs.features.indicators.momentum.linreg import _compute_linreg_batch
```

#### Live path (`evaluate`):
The model must maintain internal state:
- `deque(maxlen=mom_period)` for close, high, low values
- Compute HH, LL, SMA_close, midline, delta on each tick
- Feed delta into an internal LinReg instance (period=`mom_period`)

```python
def __init__(self, params):
    ...
    mom_p = self.params["mom_period"]
    self._close_buf = deque(maxlen=mom_p)
    self._high_buf = deque(maxlen=mom_p)
    self._low_buf = deque(maxlen=mom_p)
    self._delta_linreg = LinReg(period=mom_p)
    self._delta_linreg_primed = False
```

On each `evaluate()` call, after extracting `close`, `high`, `low` from `bar_data`:
```python
self._close_buf.append(close)
self._high_buf.append(high)
self._low_buf.append(low)
if len(self._close_buf) == mom_p:
    hh = max(self._high_buf)
    ll = min(self._low_buf)
    sma_c = sum(self._close_buf) / mom_p
    midline = (hh + ll) / 2.0
    delta = close - (midline + sma_c) / 2.0
    if not self._delta_linreg_primed:
        # accumulate deltas until LinReg can be primed
        ...
    else:
        lr_mom = self._delta_linreg.update(delta)
```

**Note:** The LinReg indicator needs `period` values to prime. So the first `mom_period` ticks populate the delta buffer, then LinReg primes on those deltas, and subsequent ticks produce lr_mom via `update()`. During warmup, `lr_mom = None` and the model produces no signal — this is correct behavior.

### 6.4 Signal Strength Voters — Complete Replacement

**New `_compute_signal_strength` (live path):**

```python
def _compute_signal_strength(self, direction, features, bar_data) -> int:
    ss = 0

    # 1. CCI rising/falling (direction-dependent)
    cci = self._extract_scalar(features, "CCI")
    prev_cci = bar_data.get("prev_CCI")  # or maintained internally
    if cci is not None and prev_cci is not None:
        if (direction == 1 and cci > prev_cci) or (direction == -1 and cci < prev_cci):
            ss += 1

    # 2. ADX > threshold + DI direction
    adx_data = features.get("ADX")
    if isinstance(adx_data, dict):
        adx_val = adx_data.get("adx")
        pdi = adx_data.get("plus_di")
        mdi = adx_data.get("minus_di")
        if adx_val is not None and adx_val > self.params["adx_threshold"]:
            if (direction == 1 and pdi is not None and mdi is not None and pdi > mdi):
                ss += 1
            elif (direction == -1 and pdi is not None and mdi is not None and mdi > pdi):
                ss += 1

    # 3. A/D line > SMA(ad_sma_period) of A/D (direction-dependent)
    ad_val = self._extract_scalar(features, "ADLine")
    ad_sma = self._ad_sma_value  # maintained internally via deque
    if ad_val is not None and ad_sma is not None:
        if (direction == 1 and ad_val > ad_sma) or (direction == -1 and ad_val < ad_sma):
            ss += 1

    # 4. MFI > SMA(mfi_sma_period) of MFI (direction-dependent)
    mfi_val = self._extract_scalar(features, "MFI")
    mfi_sma = self._mfi_sma_value  # maintained internally via deque
    if mfi_val is not None and mfi_sma is not None:
        if (direction == 1 and mfi_val > mfi_sma) or (direction == -1 and mfi_val < mfi_sma):
            ss += 1

    # 5. Momentum-LR rising/falling: linreg(momentum, mom_lr_period)
    mom_lr = self._mom_lr_value  # maintained internally
    prev_mom_lr = self._prev_mom_lr_value
    if mom_lr is not None and prev_mom_lr is not None:
        if (direction == 1 and mom_lr > prev_mom_lr) or (direction == -1 and mom_lr < prev_mom_lr):
            ss += 1

    return ss
```

**New `_batch_signal_strength_filter`:**

The batch path computes all SS indicators over the full DataFrame:
```python
def _batch_signal_strength_filter(self, directions, feature_df, ss_threshold):
    ss = pd.Series(0, index=directions.index)
    signal_mask = directions != 0
    h, l, c, v = feature_df["high"], feature_df["low"], feature_df["close"], feature_df["volume"]

    # 1. CCI rising/falling
    cci = feature_df.get("CCI")
    if cci is not None:
        cci_prev = cci.shift(1)
        cci_long = (directions == 1) & (cci > cci_prev)
        cci_short = (directions == -1) & (cci < cci_prev)
        ss[cci_long | cci_short] += 1

    # 2. ADX > threshold + DI direction
    adx = feature_df.get("ADX_adx")      # flattened column name
    pdi = feature_df.get("ADX_plus_di")
    mdi = feature_df.get("ADX_minus_di")
    if adx is not None and pdi is not None and mdi is not None:
        adx_thresh = self.params["adx_threshold"]
        adx_long = (directions == 1) & (adx > adx_thresh) & (pdi > mdi)
        adx_short = (directions == -1) & (adx > adx_thresh) & (mdi > pdi)
        ss[adx_long | adx_short] += 1

    # 3. A/D > SMA(A/D, ad_sma_period)
    ad = feature_df.get("ADLine")
    if ad is not None:
        ad_sma = ad.rolling(self.params["ad_sma_period"], min_periods=1).mean()
        ad_long = (directions == 1) & (ad > ad_sma)
        ad_short = (directions == -1) & (ad < ad_sma)
        ss[ad_long | ad_short] += 1

    # 4. MFI > SMA(MFI, mfi_sma_period)
    mfi = feature_df.get("MFI")
    if mfi is not None:
        mfi_sma = mfi.rolling(self.params["mfi_sma_period"], min_periods=1).mean()
        mfi_long = (directions == 1) & (mfi > mfi_sma)
        mfi_short = (directions == -1) & (mfi < mfi_sma)
        ss[mfi_long | mfi_short] += 1

    # 5. Momentum-LR rising/falling
    mom = feature_df.get("Momentum")
    if mom is not None:
        lr_mom_ss = self._rolling_linreg(mom.values, self.params["mom_lr_period"])
        lr_mom_series = pd.Series(lr_mom_ss, index=directions.index)
        lr_prev = lr_mom_series.shift(1)
        lr_long = (directions == 1) & (lr_mom_series > lr_prev)
        lr_short = (directions == -1) & (lr_mom_series < lr_prev)
        ss[lr_long | lr_short] += 1

    suppress = signal_mask & (ss < ss_threshold)
    directions = directions.copy()
    directions[suppress] = 0
    return directions
```

### 6.5 Internal State for Live SS Voters

The model needs additional internal state for SS voters that require "previous value" or "SMA of indicator":

```python
def __init__(self, params):
    ...
    # SS voter state
    self._prev_cci: float | None = None
    self._ad_buf: deque = deque(maxlen=self.params.get("ad_sma_period", 21))
    self._mfi_buf: deque = deque(maxlen=self.params.get("mfi_sma_period", 9))
    self._mom_linreg: LinReg | None = None  # primed when enough Momentum values seen
    self._prev_mom_lr: float | None = None
    self._mom_buf: deque = deque(maxlen=self.params.get("mom_lr_period", 14))
```

On each `evaluate()`, after computing direction:
1. Update `_prev_cci` with current CCI.
2. Append ADLine value to `_ad_buf`, compute mean → `_ad_sma_value`.
3. Append MFI value to `_mfi_buf`, compute mean → `_mfi_sma_value`.
4. Append Momentum to `_mom_buf`. When full, prime/update a LinReg instance → `_mom_lr_value`. Track `_prev_mom_lr`.

---

## 7. Config Changes

### 7.1 `features.yaml` — Default Section

Replace the single `KAMA` entry with `KAMA_fast` and `KAMA_slow`. Add new indicator entries.

```yaml
# REPLACE existing KAMA entry:
KAMA_fast:
  type: KAMA
  period: 5
  fast_period: 2
  slow_period: 10
KAMA_slow:
  type: KAMA
  period: 30
  fast_period: 2
  slow_period: 10

# ADD new indicators:
CCI:
  period: 5
ADX:
  period: 14
MFI:
  period: 14
ADLine: {}
Momentum:
  period: 10

# KEEP existing: LinReg, BollingerBands, KeltnerChannel, ATR, RSI, EMA_fast, EMA_slow, MACD
# NOTE: LinReg is still needed by other models. SqueezeBreakout no longer uses pipeline LinReg,
# but it remains in features.yaml for MeanReversion/TrendFollowing/Momentum models.
```

**Critical detail on KAMA smoothing constants:** The v4 research uses `fast_len=2, slow_len=10` for KAMA's internal smoothing on both fast and slow lines. The current production KAMA uses `fast_period=2, slow_period=30` (slow smoothing constant = 30). The `slow_period` param in the KAMA constructor controls the slow smoothing constant SC = 2/(slow_period+1). v4 uses SC = 2/11 ≈ 0.182 while production uses SC = 2/31 ≈ 0.065. **This is a meaningful difference — use v4's values (`slow_period=10`) for both KAMA lines.**

### 7.2 `models.yaml` — SqueezeBreakout Entries

Update all SqueezeBreakout entries (BTCUSDT/1h, XRPUSDT/1h, SOLUSDT/1h, BNBUSDT/30m, DOGEUSDT/4h):

```yaml
SqueezeBreakout:
  enabled: true
  params:
    kama_fast_period: 5
    kama_slow_period: 30
    mom_period: 20
    squeeze_lookback: 1
    ss_threshold: 3
    cci_period: 5
    adx_period: 14
    adx_threshold: 18.0
    ad_sma_period: 21
    mfi_period: 14
    mfi_sma_period: 9
    mom_lr_period: 14
    mom_lr_mom_period: 10
```

---

## 8. `FeatureManager` Input Mapping

The `FeatureManager._get_mapped_input()` currently uses type hint heuristics:
- `float` → close (index 3)
- 5+ floats → full candle (O,H,L,C,V)
- 3 floats → HLC

New indicators CCI, ADX need HLC (3 floats) — this already works.
MFI and ADLine need HLCV (4 floats). **The current heuristic has no 4-float path.**

**Required change in `feature_manager.py`:** Add a 4-comma (HLCV) path:
```python
elif comma_count >= 3:  # 4 floats = HLCV candle (high, low, close, volume)
    return (data[1], data[2], data[3], data[4])  # H, L, C, V
```

This must be inserted **before** the existing 3-float check. Adjust the cascade:
```python
if comma_count >= 4:  # 5+ floats = full candle
    return data[:5]
elif comma_count >= 3:  # 4 floats = HLCV  (NEW)
    return (data[1], data[2], data[3], data[4])
elif comma_count >= 2:  # 3 floats = HLC
    return (data[1], data[2], data[3])
```

---

## 9. Implementation Order

| Step | Task | Depends On | Tests |
|---|---|---|---|
| 1 | Create `Momentum` indicator | — | `test_momentum.py` |
| 2 | Create `CCI` indicator | — | `test_cci.py` |
| 3 | Create `ADX` indicator | — | `test_adx.py` |
| 4 | Create `MFI` indicator | — | `test_mfi.py` |
| 5 | Create `ADLine` indicator | — | `test_ad_line.py` |
| 6 | Update `indicators/__init__.py` | Steps 1–5 | Import check |
| 7 | Update `feature_manager.py` input mapping | — | Existing tests + new mapping test |
| 8 | Update `features.yaml` | Steps 1–6 | Config loading test |
| 9 | Rewrite `model.py` entry logic + SS voters + hyperparams | Steps 1–8 | `test_squeeze_breakout_model.py` |
| 10 | Update `models.yaml` | Step 9 | Config validation |
| 11 | Rewrite `test_squeeze_breakout_model.py` | Step 9 | All tests pass |

Steps 1–5 are parallelizable. Steps 6–8 are parallelizable after 1–5. Steps 9–11 are sequential.

---

## 10. Acceptance Criteria

1. **All 5 new indicators** pass batch/live parity tests with `abs_tol=1e-9`.
2. **All 5 new indicators** have `@njit(cache=True)` batch kernels.
3. **All 5 new indicators** have O(1) or O(period) `update()` methods — no full-array recomputation.
4. **SqueezeBreakout entry logic** uses dual-KAMA crossover + TTM delta-linreg.
5. **SqueezeBreakout SS voters** match v4 research exactly: CCI rising, ADX+DI, A/D vs SMA, MFI vs SMA, Momentum-LR rising.
6. **Live-batch parity:** `evaluate()` on sequential ticks produces identical directions as `batch_evaluate()` on the same data (existing parity test pattern).
7. **No regressions** in other model tests (MeanReversion, TrendFollowing, Momentum).
8. **`features.yaml`** loads correctly with `KAMA_fast` and `KAMA_slow` as aliased KAMA instances.
9. **`models.yaml`** validates with new hyperparameter names.
10. **Minimum 15 model tests** covering: squeeze release + direction, KAMA crossover polarity, TTM momentum polarity, each SS voter individually, SS threshold gating, batch parity, warmup period behavior.

---

## 11. Validation Checklist

### Quant Correctness
- [ ] Dual-KAMA crossover matches v4: `_kama(c, 5, 2, 10)` vs `_kama(c, 30, 2, 10)`.
- [ ] TTM delta formula matches v4: `delta = close - ((HH+LL)/2 + SMA(close))/2`, then `linreg(delta, mom_period)`.
- [ ] CCI formula: `(TP - mean_TP) / (0.015 * MAD)`.
- [ ] ADX formula: Wilder's smoothed TR/DM → DI → DX → ADX.
- [ ] MFI formula: pos/neg money flow ratio → `100 - 100/(1+MFR)`.
- [ ] ADLine formula: CLV * volume, cumulative.
- [ ] Momentum: `close - close[period]`.
- [ ] SS voter 1: CCI rising (long) / falling (short).
- [ ] SS voter 2: ADX > threshold AND pdi > mdi (long) / mdi > pdi (short).
- [ ] SS voter 3: AD > SMA(AD) (long) / AD < SMA(AD) (short).
- [ ] SS voter 4: MFI > SMA(MFI) (long) / MFI < SMA(MFI) (short).
- [ ] SS voter 5: linreg(momentum, period) rising (long) / falling (short).

### Engineering
- [ ] All indicators registered in `IndicatorRegistry`.
- [ ] All indicators importable from `libs.features.indicators`.
- [ ] `FeatureManager` correctly maps HLCV inputs for MFI and ADLine.
- [ ] No point-in-time violations (all indicators use only past data).
- [ ] No look-ahead bias in batch signal strength computation (shift(1) used correctly for "previous" values).
- [ ] Model warmup period (`min_history_bars`) sufficient for all indicator lookbacks.

### Backward Compatibility
- [ ] Old `kama_period`, `kama_fast`, `kama_slow` hyperparam names removed from schema.
- [ ] All `models.yaml` SqueezeBreakout entries updated with new param names.
- [ ] Other models unaffected (their required indicators are still computed).
- [ ] `LinReg` indicator remains in `features.yaml` for other model consumers.

---

## 12. Risks and Mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| ADX warmup period (29 bars) creates NaN pocket in batch | Medium | `min_history_bars=50` ensures enough warmup; batch SS voters already guard against NaN |
| MFI/ADLine need volume in live path — some FeatureVector.bar_data may not include volume | Medium | Validate `bar_data` includes `volume` at model boot; gracefully skip SS voter if volume missing |
| `_get_mapped_input` 4-float heuristic may collide with future indicators | Low | Document the convention; type hint `Tuple[float,float,float,float]` is explicit |
| KAMA `slow_period=10` (v4 value) vs production's `slow_period=30` — ensure this is intentional | High | **Confirmed:** v4 research uses `fast_len=2, slow_len=10` for KAMA smoothing on both lines. This is the KAMA constructor's `fast_period`/`slow_period` params. The KAMA `period` param (lookback window) is what differs between the two lines (5 vs 30). |
| 15 existing tests will break | Expected | All tests must be rewritten as part of this handoff — not a risk, a known cost |
| Existing optimization trials in TimescaleDB reference old hyperparams | Low | Old trials should be ignored — Phase B will re-run from scratch |

---

## 13. Phase A vs Phase B Boundary

| Phase A (This Handoff) | Phase B (Deferred) |
|---|---|
| Align signal logic to v4 research | Re-run Optuna with corrected signals |
| Create 5 new indicators | Sweep SS voter indicator periods |
| Rewrite SS voters to match v4 | Sweep KAMA fast/slow periods |
| Update configs with v4 default params | Cross-asset optimization |
| Rewrite model tests | Multi-TP execution layer |
| Validate parity live ↔ batch | Walk-forward / regime analysis |
| | Deploy to paper trading |

---

## 14. Completeness Statement

This handoff is **complete and self-contained** for the coder agent to execute without guessing. All design decisions are resolved. All formulas are specified. The implementation order is sequenced with dependencies. No external context or further architect input is needed for Phase A execution.
