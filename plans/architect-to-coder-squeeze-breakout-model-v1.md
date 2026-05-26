---
goal: Implement merged Squeeze Breakout model with KAMA, Keltner Channel, LinReg indicators and Signal Strength meta-filter
stage: architect-to-coder
date_created: 2026-05-26
last_updated: 2026-05-26
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, squeeze-breakout, indicators, model, phase-3b]
source_agent: Quant Orchestrator / Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Squeeze Breakout Model

## 1. Objective

Implement the **SqueezeBreakout** model — a merged strategy combining v2 BB-width expansion and v3 PineScript BB/KC (Bollinger Bands inside Keltner Channel) squeeze detection with KAMA trend filtering, linear regression momentum, and a Signal Strength confluence meta-filter.

This is the only strategy across 4 research iterations that showed consistent positive alpha:
- BTC 1h: Sharpe 1.53 (SS≥3), 66 trades, +28.3%
- XRP 1h: Sharpe 1.84, 88 trades, +39.8%
- SOL 1h: Sharpe 1.56, 105 trades, +37.0%
- BNB 30m: Sharpe 1.87, 100 trades, +42.7%

## 2. Scope

### 2.1 New Indicators (P0)

Create 3 new indicators in the IndicatorRegistry:

#### A. KAMA (Kaufman Adaptive Moving Average)
- **File:** `src/libs/features/indicators/trend/kama.py`
- **Registry key:** `KAMA`
- **Input type:** `float` (close price)
- **Output type:** `float`
- **Constructor params:** `period: int = 10`, `fast_period: int = 2`, `slow_period: int = 30`
- **Logic:**
  ```
  direction = abs(close - close[period ago])
  volatility = sum(abs(close[i] - close[i-1]) for last period bars)
  ER = direction / volatility  (efficiency ratio, 0-1)
  fast_sc = 2 / (fast_period + 1)
  slow_sc = 2 / (slow_period + 1)
  sc = (ER * (fast_sc - slow_sc) + slow_sc) ** 2
  kama = prev_kama + sc * (close - prev_kama)
  ```
- **Must implement:** `batch()`, `prime()`, `update()` per `Indicator` ABC
- **Numba:** Use `@njit(cache=True)` for batch computation

#### B. KeltnerChannel
- **File:** `src/libs/features/indicators/volatility/keltner.py`
- **Registry key:** `KeltnerChannel`
- **Input type:** `Tuple[float, float, float]` (high, low, close) — same as ATR
- **Output type:** `Tuple[float, float, float]` (middle, upper, lower) — same shape as BollingerBands
- **Constructor params:** `period: int = 20`, `multiplier: float = 1.5`, `atr_period: int = 14`
- **Logic:**
  ```
  middle = EMA(close, period)
  atr = ATR(high, low, close, atr_period)
  upper = middle + multiplier * atr
  lower = middle - multiplier * atr
  ```
- **Reuse:** Import `_compute_atr_batch` from `volatility/atr.py` for ATR. Compute EMA inline (simple EMA).
- **Numba:** `@njit(cache=True)` for batch

#### C. LinReg (Linear Regression Value)
- **File:** `src/libs/features/indicators/momentum/linreg.py`
- **Registry key:** `LinReg`
- **Input type:** `float` (close price)
- **Output type:** `float` (regression value at current bar)
- **Constructor params:** `period: int = 12`
- **Logic:** Standard least-squares regression over rolling window, output the predicted value at the end of the window
  ```
  For window of last `period` values:
  x = 0, 1, ..., period-1
  slope = (N*sum(x*y) - sum(x)*sum(y)) / (N*sum(x^2) - sum(x)^2)
  intercept = (sum(y) - slope*sum(x)) / N
  linreg_value = intercept + slope * (period - 1)
  ```
- **Numba:** `@njit(cache=True)` for batch

### 2.2 New Model (P1)

#### SqueezeBreakout Model
- **Directory:** `src/libs/models/squeeze_breakout/`
- **Files:**
  - `__init__.py` (import model to trigger registration)
  - `model.py` (main model implementation)
  - `optimization/` directory with `__init__.py` and `optimizer.py`
- **Registry key:** `SqueezeBreakout`

**ModelMeta:**
```python
meta = ModelMeta(
    name="SqueezeBreakout",
    required_indicators=["KAMA", "BollingerBands", "KeltnerChannel", "LinReg"],
    required_fields=[
        "KAMA",
        "BollingerBands_upper", "BollingerBands_lower",
        "KeltnerChannel_upper", "KeltnerChannel_lower",
        "LinReg",
    ],
    hyperparameter_schema={
        "kama_period": ParamDef(type="int", default=10, low=5, high=30, step=1),
        "kama_fast": ParamDef(type="int", default=2, low=2, high=5, step=1),
        "kama_slow": ParamDef(type="int", default=30, low=15, high=50, step=1),
        "mom_period": ParamDef(type="int", default=12, low=6, high=24, step=1),
        "squeeze_lookback": ParamDef(type="int", default=1, low=1, high=5, step=1),
    },
    min_history_bars=30,
)
```

**Signal Logic (evaluate + _batch_evaluate_impl):**
```
1. Squeeze detection: squeeze_on = BB_upper < KC_upper AND BB_lower > KC_lower
2. Squeeze release: squeeze_off = NOT squeeze_on AND squeeze_was_on(any of last squeeze_lookback bars)
3. Momentum direction: mom = LinReg value
   - mom > 0 → bullish momentum
   - mom < 0 → bearish momentum
4. KAMA trend filter:
   - close > KAMA → uptrend confirmed
   - close < KAMA → downtrend confirmed
5. Entry signals:
   - LONG:  squeeze_off AND mom > 0 AND close > KAMA
   - SHORT: squeeze_off AND mom < 0 AND close < KAMA
6. Conviction: min(1.0, abs(mom) / ATR) if ATR available, else 0.5
```

**evaluate() single-tick:** Follow same pattern as MeanReversion — extract features from FeatureVector, compute direction/conviction, return ModelOutput.

**_batch_evaluate_impl():** Vectorized pandas — compute squeeze state, detect releases, apply KAMA filter, return directions Series.

### 2.3 Signal Strength Meta-Filter (P2)

Add a **SignalStrength** scoring system that filters SqueezeBreakout signals based on confluence of 5 auxiliary indicators.

**Implementation approach:** Add signal strength computation as part of the SqueezeBreakout model itself (not a separate model). Add optional `ss_threshold` hyperparameter.

**Additional required_indicators:** `RSI`, `ATR` (already in default features.yaml)

**Signal Strength Logic (5 voters, 0-5 score):**
```python
ss = 0
# 1. Momentum LinReg confirms direction
if (direction == 1 and linreg > 0) or (direction == -1 and linreg < 0):
    ss += 1
# 2. RSI confirms (not overbought for longs, not oversold for shorts)
if (direction == 1 and 40 < rsi < 70) or (direction == -1 and 30 < rsi < 60):
    ss += 1
# 3. KAMA slope confirms (KAMA rising for longs, falling for shorts)
kama_slope = kama - kama_prev
if (direction == 1 and kama_slope > 0) or (direction == -1 and kama_slope < 0):
    ss += 1
# 4. Squeeze was tight (BB width / KC width < 0.8 → strong squeeze)
bb_width = bb_upper - bb_lower
kc_width = kc_upper - kc_lower
if kc_width > 0 and bb_width / kc_width < 0.8:
    ss += 1
# 5. Volume above average (if volume available)
# For batch: vol > SMA(vol, 20)
if volume > avg_volume:
    ss += 1
```

**Hyperparameter:**
```python
"ss_threshold": ParamDef(type="int", default=3, low=0, high=5, step=1),
```

When `ss_threshold > 0`, suppress signals where `ss < ss_threshold` (set direction=0).

### 2.4 Config Updates (P1)

#### features.yaml additions

Add KAMA, KeltnerChannel, and LinReg to the default features block:

```yaml
# Under features.assets.default.timeframes.default:
  KAMA:
    period: 10
    fast_period: 2
    slow_period: 30
  KeltnerChannel:
    period: 20
    multiplier: 1.5
    atr_period: 14
  LinReg:
    period: 12
```

#### models.yaml additions

Add SqueezeBreakout to the asset-specific configs:

```yaml
# BTCUSDT 1h
SqueezeBreakout:
  enabled: true
  params:
    kama_period: 10
    kama_fast: 2
    kama_slow: 30
    mom_period: 12
    squeeze_lookback: 1
    ss_threshold: 3

# BTCUSDT 4h — disabled (Sharpe 0.38 on 4h, not tradeable)
SqueezeBreakout:
  enabled: false

# Add new asset sections for:
# XRPUSDT 1h — Sharpe 1.84
# SOLUSDT 1h — Sharpe 1.56
# BNBUSDT 30m — Sharpe 1.87
# DOGEUSDT 4h — Sharpe 1.25
```

New asset-timeframe entries in models.yaml:
```yaml
XRPUSDT:
  timeframes:
    1h:
      SqueezeBreakout:
        enabled: true
        params:
          ss_threshold: 3
SOLUSDT:
  timeframes:
    1h:
      SqueezeBreakout:
        enabled: true
        params:
          ss_threshold: 3
BNBUSDT:
  timeframes:
    30m:
      SqueezeBreakout:
        enabled: true
        params:
          ss_threshold: 3
DOGEUSDT:
  timeframes:
    4h:
      SqueezeBreakout:
        enabled: true
        params:
          ss_threshold: 3
```

### 2.5 Registration Wiring

- Add import to `src/libs/features/indicators/__init__.py`:
  ```python
  from .trend.kama import KAMA
  from .volatility.keltner import KeltnerChannel
  from .momentum.linreg import LinReg
  ```
- Add import to `src/libs/models/__init__.py`:
  ```python
  import libs.models.squeeze_breakout  # noqa: F401
  ```

## 3. Files Touched

| Action | File | Why |
|--------|------|-----|
| CREATE | `src/libs/features/indicators/trend/kama.py` | KAMA indicator |
| CREATE | `src/libs/features/indicators/volatility/keltner.py` | Keltner Channel indicator |
| CREATE | `src/libs/features/indicators/momentum/linreg.py` | LinReg indicator |
| CREATE | `src/libs/models/squeeze_breakout/__init__.py` | Model package init |
| CREATE | `src/libs/models/squeeze_breakout/model.py` | SqueezeBreakout model |
| CREATE | `src/libs/models/squeeze_breakout/optimization/__init__.py` | Optimizer package |
| CREATE | `src/libs/models/squeeze_breakout/optimization/optimizer.py` | Optuna objective |
| EDIT | `src/libs/features/indicators/__init__.py` | Register new indicators |
| EDIT | `src/libs/models/__init__.py` | Register SqueezeBreakout |
| EDIT | `configs/features.yaml` | Add KAMA, KC, LinReg configs |
| EDIT | `configs/models.yaml` | Add SqueezeBreakout + new assets |

## 4. Files NOT Touched

- `src/libs/models/base.py` — no changes to BaseModel ABC
- `src/libs/contracts/` — no schema changes
- `src/apps/` — no app-layer changes
- Existing indicators (RSI, EMA, MACD, BB, ATR, Supertrend, VWAP) — untouched
- Existing models (MeanReversion, TrendFollowing, Momentum) — untouched

## 5. Blast Radius

- **Low risk.** All changes are additive — new files only, plus config additions.
- The only edits to existing files are import additions in `__init__.py` files and config additions in YAML.
- Existing models and indicators are not modified.
- New config entries use the established fallback chain in `FeatureManager` and `ModelManager`.

## 6. Validation Requirements

### Unit Tests (create under `tests/`)

1. **KAMA indicator tests** (`tests/test_kama_indicator.py`):
   - Batch output shape matches input
   - Known value check (constant input → KAMA = input)
   - Prime + update consistency with batch
   - Edge: period > data length returns NaN

2. **KeltnerChannel indicator tests** (`tests/test_keltner_indicator.py`):
   - Output shape (middle, upper, lower) matches BollingerBands contract
   - upper > middle > lower for all valid outputs
   - Prime + update consistency with batch

3. **LinReg indicator tests** (`tests/test_linreg_indicator.py`):
   - Linear input → LinReg matches last value exactly
   - Batch output shape matches input
   - Prime + update consistency

4. **SqueezeBreakout model tests** (`tests/test_squeeze_breakout_model.py`):
   - Registration: `ModelRegistry.get("SqueezeBreakout")` works
   - evaluate() returns valid ModelOutput with direction in {-1, 0, 1}
   - batch_evaluate() output aligns with input DataFrame
   - Squeeze detection: when BB inside KC → squeeze_on
   - Signal generation: squeeze_off + momentum + KAMA filter → correct direction
   - SS filtering: signals below ss_threshold are suppressed

5. **Config validation tests**:
   - ModelManager can load SqueezeBreakout for configured assets
   - Feature coverage validation passes for all configured asset/timeframe pairs

### Run existing tests
```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -x -q
```
All 403+ existing tests must still pass.

## 7. Residual Risk / Follow-ups

- **Multi-TP trade management** is NOT in this handoff. The current system uses single direction signals. Multi-TP requires changes to the execution layer (risk_app, execution_app) which is a separate handoff.
- **Optuna optimization** is deferred. Deploy with unoptimized defaults first. The optimizer stub is included but not a blocking requirement.
- **30m timeframe support** may require adding `30m` to the ingestion pipeline config if not already supported. Check `base.yaml` for interval support.
- **New assets** (XRP, SOL, BNB, DOGE) need corresponding entries in `base.yaml` stream subscriptions if not already present. This is a config-only change but is outside this handoff's scope.

## 8. Implementation Order

1. P0: Create KAMA, KeltnerChannel, LinReg indicators + tests
2. P1: Create SqueezeBreakout model + tests + config updates
3. P2: Add Signal Strength meta-filter to SqueezeBreakout
4. Run full test suite
