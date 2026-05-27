---
goal: Implement RegimePullbackScorer and DivergenceEdgeScorer — two concrete ScoringModel implementations
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, scoring-models, alpha-discovery, regime-pullback, divergence-edge, phase-2]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Concrete ScoringModel Implementations (Phase 2)

## 1. Objective

Implement two concrete `ScoringModel` subclasses that emit continuous `edge_score` values (not binary direction). These are the first models to leverage the engineered feature infrastructure built in Phase 1. They are designed to be **orthogonal** to each other and to the existing threshold models (SqueezeBreakout, MeanReversion).

| Model | Alpha Thesis | Primary Feature Group |
|-------|-------------|----------------------|
| `RegimePullbackScorer` | Mean-reversion edge conditional on confirmed regime | Regime + Price-Structure |
| `DivergenceEdgeScorer` | Price-indicator divergence magnitude as edge | Momentum + Volume |

---

## 2. Scope Boundaries

### In Scope
- `ScoringModelRegistry` in `src/libs/models/scoring_registry.py` — parallel to `ModelRegistry`
- `RegimePullbackScorer` in `src/libs/models/regime_pullback/model.py`
- `DivergenceEdgeScorer` in `src/libs/models/divergence_edge/model.py`
- `ScoringModelManager` in `src/apps/strategy_app/scoring_model_manager.py`
- Integration of scoring models into `StrategyWorker.process_features()` (pass `scoring_outputs` to `SelectionLayer.select()`)
- Registration imports in `src/libs/models/__init__.py`
- Config additions to `configs/models.yaml`
- Unit tests for both models + scoring registry + scoring model manager

### Out of Scope (Explicit Non-Goals)
- Modifying any existing threshold model (SqueezeBreakout, MeanReversion, TrendFollowing, Momentum)
- Modifying `ScoringModel` ABC, `ScoringOutput` contract, or `SelectionLayer`
- Modifying `ModelRegistry`, `ModelManager`, or `BaseModel`
- Adding new engineered features or indicators
- Optimization / backtest harness for scoring models
- Risk, execution, portfolio layers

---

## 3. Affected Symbols, Modules, and Execution Flows

### Files Modified (Minimal Changes Only)

| File | Change |
|------|--------|
| `src/apps/strategy_app/strategy_worker.py` | Add `ScoringModelManager`, call `evaluate()`, pass results as `scoring_outputs` to `SelectionLayer.select()` |
| `src/libs/models/__init__.py` | Add import for `libs.models.regime_pullback` and `libs.models.divergence_edge` |
| `configs/models.yaml` | Add `scoring_models` section with config for both models |

### New Files

| File | Purpose |
|------|---------|
| `src/libs/models/scoring_registry.py` | `ScoringModelRegistry` — decorator-based registry for `ScoringModel` subclasses |
| `src/libs/models/regime_pullback/__init__.py` | Package init |
| `src/libs/models/regime_pullback/model.py` | `RegimePullbackScorer` implementation |
| `src/libs/models/divergence_edge/__init__.py` | Package init |
| `src/libs/models/divergence_edge/model.py` | `DivergenceEdgeScorer` implementation |
| `src/apps/strategy_app/scoring_model_manager.py` | `ScoringModelManager` — config-driven loader + evaluator for scoring models |
| `tests/test_regime_pullback_scorer.py` | Unit tests |
| `tests/test_divergence_edge_scorer.py` | Unit tests |
| `tests/test_scoring_registry.py` | Unit tests |
| `tests/test_scoring_model_manager.py` | Unit tests |

### Unchanged Files (Do NOT Modify)

- `src/libs/models/scoring_base.py` — `ScoringModel` ABC
- `src/libs/models/base.py` — `BaseModel` ABC
- `src/libs/models/registry.py` — `ModelRegistry`
- `src/libs/contracts/signal.py` — `ScoringOutput`, `SelectionCandidate`, etc.
- `src/libs/selection/` — entire directory
- `src/libs/features/` — entire directory
- `src/apps/strategy_app/model_manager.py` — `ModelManager`
- All existing model directories (`squeeze_breakout/`, `mean_reversion/`, `trend_following/`, `momentum/`)

### Execution Flow (Before vs After)

**Before (current):**
```
StrategyWorker.process_features()
  → ModelManager.evaluate(FeatureVector) → list[ModelOutput]
  → SelectionLayer.select(outputs, scoring_outputs=None, feature_vec)
  → for each selected → TradeSignal → publish
```

**After:**
```
StrategyWorker.process_features()
  → ModelManager.evaluate(FeatureVector) → list[ModelOutput]
  → ScoringModelManager.evaluate(FeatureVector) → list[ScoringOutput]  ← NEW
  → SelectionLayer.select(outputs, scoring_outputs=scoring_outputs, feature_vec)
  → for each selected → TradeSignal → publish
```

---

## 4. ScoringModelRegistry

### File: `src/libs/models/scoring_registry.py`

Mirror the existing `ModelRegistry` pattern but for `ScoringModel` subclasses.

```python
"""Decorator-based registry for ScoringModel subclasses."""

from __future__ import annotations
from typing import Type
from libs.models.scoring_base import ScoringModel


class ScoringModelRegistry:
    _registry: dict[str, Type[ScoringModel]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: @ScoringModelRegistry.register("RegimePullbackScorer")."""
        def wrapper(model_class: Type[ScoringModel]):
            cls._registry[name] = model_class
            return model_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[ScoringModel]:
        if name not in cls._registry:
            raise KeyError(f"Scoring model '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
```

---

## 5. ScoringModelManager

### File: `src/apps/strategy_app/scoring_model_manager.py`

Mirrors `ModelManager` but loads from `scoring_models` config key and instantiates `ScoringModel` subclasses.

```python
"""Config-driven loader and evaluator for ScoringModel subclasses."""

class ScoringModelManager:
    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.models: list[ScoringModel] = []
        self._load_models()

    def _load_models(self) -> None:
        """Load from configs/models.yaml under scoring_models key."""
        # Same fallback chain as ModelManager:
        # scoring_models.assets.{ASSET}.timeframes.{TF}
        # → scoring_models.assets.{ASSET}.timeframes.default
        # → scoring_models.assets.default.timeframes.{TF}
        # → scoring_models.assets.default.timeframes.default
        ...

    def evaluate(self, feature_vec: FeatureVector) -> list[ScoringOutput]:
        """Run all scoring models, return non-trivial outputs."""
        results = []
        for model in self.models:
            try:
                output = model.evaluate(feature_vec)
                results.append(output)
            except Exception:
                logger.error(...)
        return results

    def validate_feature_coverage(self, available_features: set[str] | None = None) -> None:
        """Same pattern as ModelManager.validate_feature_coverage()."""
        ...
```

**Key decisions:**
- Reuse the same `ConfigManager` + fallback chain pattern from `ModelManager`.
- Config root key: `scoring_models` (parallel to `models`).
- Call `validate_feature_coverage()` at boot in `StrategyWorker.start()`.

---

## 6. Model 1: RegimePullbackScorer

### 6.1. Purpose & Alpha Thesis

Captures mean-reversion edge **conditional on confirmed regime**. The thesis:

> In a confirmed ranging regime (low ADX), pullbacks from adaptive moving average (KAMA) offer a statistically significant reversion opportunity. The edge magnitude scales with (a) the depth of the pullback in ATR units, (b) the strength of the ranging confirmation, and (c) supportive cross-sectional breadth.

This is orthogonal to the existing MeanReversion model because:
1. It emits a **continuous edge_score** (not binary direction).
2. It uses the **engineered `eng_regime_score`** and **`eng_mean_reversion_z`** features instead of raw RSI/BB thresholds.
3. It incorporates **cross-sectional confirmation** via `eng_btc_dominance_regime` and `eng_market_cap_breadth`.

### 6.2. Required Indicators

| Indicator | Purpose |
|-----------|---------|
| `KAMA_slow` | Adaptive moving average — pullback anchor |
| `ATR` | Normalizing distance and setting volatility context |
| `ADX` | Regime classification (consumed via `eng_regime_score`) |
| `RSI` | Oversold/overbought confirmation |
| `BollingerBands` | Bandwidth for volatility compression detection |

### 6.3. Required Engineered Features

| Feature | Key | Purpose |
|---------|-----|---------|
| Regime Score | `eng_regime_score` | Continuous regime: tanh((ADX-25)/10). Negative = ranging, positive = trending |
| Mean Reversion Z | `eng_mean_reversion_z` | Z-score of price vs KAMA_slow, normalized by ATR. Core pullback depth signal |
| Squeeze Intensity | `eng_squeeze_intensity` | BB/KC bandwidth ratio. Values < 1.0 = squeeze (volatility compression) |

### 6.4. Required Cross-Sectional Features

| Feature | Key | Purpose |
|---------|-----|---------|
| BTC Dominance Regime | `eng_btc_dominance_regime` | Market-wide regime gate: positive = BTC-dominant (less favorable for alts MR) |
| Market Cap Breadth | `eng_market_cap_breadth` | Rate of change of TOTAL2/TOTAL3 — positive = broadening participation (supportive for MR) |

### 6.5. Edge Score Calculation

```
Gate conditions (ALL must pass for non-zero edge):
  1. eng_regime_score < regime_threshold  (default -0.1, i.e. ADX < ~24)
  2. |eng_mean_reversion_z| > min_z_depth  (default 1.0)
  3. RSI confirms direction:
     - LONG:  RSI < rsi_oversold_gate  (default 40)
     - SHORT: RSI > rsi_overbought_gate (default 60)

If gates pass:

  direction = -sign(eng_mean_reversion_z)
    // Negative z → price below KAMA → LONG reversion expected
    // Positive z → price above KAMA → SHORT reversion expected

  raw_edge = |eng_mean_reversion_z| - min_z_depth
    // How much deeper than the minimum threshold

  regime_multiplier = clamp((-eng_regime_score + 1.0) / 2.0, 0.0, 1.0)
    // Stronger ranging regime → higher multiplier (0.5 to 1.0)

  squeeze_bonus = max(0, 1.0 - eng_squeeze_intensity) * squeeze_weight
    // Volatility compression bonus (0 when no squeeze, up to squeeze_weight when tight)

  breadth_adjustment = 1.0 + eng_market_cap_breadth * breadth_weight
    // Broadening participation adds to edge (clamped between 0.5 and 1.5)
    breadth_adjustment = clamp(breadth_adjustment, 0.5, 1.5)

  btc_dom_penalty = 1.0
  if direction == 1 and asset is not BTC:
    btc_dom_penalty = clamp(1.0 - eng_btc_dominance_regime * btc_dom_weight, 0.5, 1.0)
    // High BTC dominance penalizes altcoin LONG MR trades

  edge_score = direction * raw_edge * regime_multiplier * (1.0 + squeeze_bonus) * breadth_adjustment * btc_dom_penalty
```

### 6.6. Conviction Calculation

```
conviction = clamp(
    base_conviction
    + depth_bonus * min(|eng_mean_reversion_z| / max_z_for_full_conviction, 1.0)
    + regime_bonus * max(0, -eng_regime_score),
    0.0, 1.0
)

Where:
  base_conviction = 0.3 (default)
  depth_bonus = 0.4 (default) — scales with pullback depth
  max_z_for_full_conviction = 3.0 (default) — z beyond this caps depth_bonus
  regime_bonus = 0.3 (default) — scales with regime ranging strength
```

### 6.7. Hyperparameters

| Name | Type | Default | Low | High | Step | Description |
|------|------|---------|-----|------|------|-------------|
| `regime_threshold` | float | -0.1 | -0.5 | 0.3 | 0.05 | `eng_regime_score` must be below this for ranging regime |
| `min_z_depth` | float | 1.0 | 0.5 | 2.5 | 0.1 | Minimum `|eng_mean_reversion_z|` to produce edge |
| `rsi_oversold_gate` | int | 40 | 25 | 50 | 1 | RSI must be below this for LONG |
| `rsi_overbought_gate` | int | 60 | 50 | 75 | 1 | RSI must be above this for SHORT |
| `squeeze_weight` | float | 0.3 | 0.0 | 0.8 | 0.05 | Squeeze bonus scaling factor |
| `breadth_weight` | float | 0.2 | 0.0 | 0.5 | 0.05 | Market breadth adjustment factor |
| `btc_dom_weight` | float | 0.3 | 0.0 | 0.6 | 0.05 | BTC dominance penalty factor for altcoin longs |
| `base_conviction` | float | 0.3 | 0.1 | 0.5 | 0.05 | Floor conviction |
| `depth_bonus` | float | 0.4 | 0.1 | 0.6 | 0.05 | Conviction bonus from pullback depth |
| `max_z_for_full_conviction` | float | 3.0 | 1.5 | 5.0 | 0.5 | Z-score where depth_bonus saturates |
| `regime_bonus` | float | 0.3 | 0.0 | 0.5 | 0.05 | Conviction bonus from strong ranging regime |

### 6.8. Entry Conditions

All must be true for `edge_score != 0`:
1. `eng_regime_score` is available and `< regime_threshold`
2. `eng_mean_reversion_z` is available and `|z| > min_z_depth`
3. `RSI` is available and confirms direction (< oversold_gate for LONG, > overbought_gate for SHORT)

If any condition fails, return `edge_score = 0.0`, `conviction = 0.0`.

### 6.9. Direction Logic

- `eng_mean_reversion_z < 0` → price below KAMA → expect reversion UP → **LONG** (positive `edge_score`)
- `eng_mean_reversion_z > 0` → price above KAMA → expect reversion DOWN → **SHORT** (negative `edge_score`)

Direction is embedded in the sign of `edge_score`. The `SelectionLayer.normalize_scoring_output()` extracts direction from `sign(edge_score)`.

### 6.10. Minimum History Bars

**50** — driven by `eng_residual_momentum` (50-bar rolling OLS window for regime_score warmup) and `eng_mean_reversion_z` (requires KAMA_slow warmup ≈30 bars + ATR ≈14 bars).

### 6.11. ModelMeta

```python
meta = ModelMeta(
    name="RegimePullbackScorer",
    required_indicators=["KAMA_slow", "ATR", "ADX", "RSI", "BollingerBands", "KeltnerChannel"],
    required_fields=[
        "KAMA_slow", "ATR", "RSI",
        "eng_regime_score", "eng_mean_reversion_z", "eng_squeeze_intensity",
        "eng_btc_dominance_regime", "eng_market_cap_breadth",
    ],
    hyperparameter_schema={...},  # as defined in §6.7
    min_history_bars=50,
)
```

---

## 7. Model 2: DivergenceEdgeScorer

### 7.1. Purpose & Alpha Thesis

Captures edge from **price-indicator divergence** — when price makes new highs/lows but momentum indicators do not confirm. The thesis:

> Divergences between price action and momentum indicators (RSI, MACD, MFI) signal exhaustion in the current move. The magnitude of the divergence (measured as the gap between price trend and indicator trend) provides a continuous estimate of reversal probability and expected move size. Volume-adjusted momentum weighting increases signal quality.

This is orthogonal to RegimePullbackScorer because:
1. It measures **momentum exhaustion** (rate-of-change divergence) rather than **static displacement from mean**.
2. It works in **both trending and ranging regimes** — divergences can form during trends.
3. It uses **Volume + Momentum** feature groups instead of Regime + Price-Structure.

### 7.2. Required Indicators

| Indicator | Purpose |
|-----------|---------|
| `RSI` | Primary momentum oscillator for divergence detection |
| `MACD` | Trend momentum — histogram divergence from price |
| `MFI` | Volume-weighted momentum — captures smart money divergence |
| `Momentum` | Raw momentum for delta-rate measurement |
| `LinReg` | Linear regression of price — slope for price trend direction |
| `ATR` | Normalizing divergence magnitude |

### 7.3. Required Engineered Features

| Feature | Key | Purpose |
|---------|-----|---------|
| Volume Adjusted Momentum | `eng_volume_adjusted_momentum` | Momentum × volume ratio — volume confirmation of momentum |
| ATR Normalized Return | `eng_atr_normalized_return` | Volatility-normalized price change — comparable across assets |
| Residual Momentum | `eng_residual_momentum` | Momentum unexplained by RSI — orthogonal momentum signal |

### 7.4. Required Cross-Sectional Features

| Feature | Key | Purpose |
|---------|-----|---------|
| Altcoin Market Momentum | `eng_altcoin_market_momentum` | Market-wide momentum context — divergence more meaningful when asset diverges from market |
| Altcoin Beta | `eng_altcoin_beta` | Asset sensitivity to market — high-beta assets have noisier divergences |

### 7.5. Edge Score Calculation

The model detects divergences using a rolling lookback window, comparing price trend vs indicator trend using linear regression slopes.

```
Step 1: Compute rolling slopes (over divergence_lookback bars, default 14)
  price_slope = LinReg slope (already available from LinReg indicator)
  rsi_slope = linear_regression_slope(RSI, over last divergence_lookback bars)
  macd_hist_slope = linear_regression_slope(MACD_histogram, over last divergence_lookback bars)
  mfi_slope = linear_regression_slope(MFI, over last divergence_lookback bars)

Step 2: Detect divergence direction and magnitude per indicator
  For each indicator_slope ∈ {rsi_slope, macd_hist_slope, mfi_slope}:
    divergence_i = 0.0
    if price_slope > 0 and indicator_slope < 0:
      // Bearish divergence: price rising, indicator falling
      divergence_i = -(|price_slope| + |indicator_slope|) * weight_i
    elif price_slope < 0 and indicator_slope > 0:
      // Bullish divergence: price falling, indicator rising
      divergence_i = +(|price_slope| + |indicator_slope|) * weight_i

  Weights (hyperparameters):
    weight_rsi (default 0.4) — RSI is most reliable divergence signal
    weight_macd (default 0.35) — MACD histogram adds trend context
    weight_mfi (default 0.25) — MFI adds volume-weighted confirmation

Step 3: Aggregate divergence score
  raw_divergence = divergence_rsi + divergence_macd + divergence_mfi

Step 4: Volume-momentum confirmation
  // Volume-adjusted momentum confirms or dampens the divergence
  vam = eng_volume_adjusted_momentum
  if vam is not None and sign(vam) == sign(raw_divergence):
    // VAM confirms divergence direction → boost
    vam_multiplier = 1.0 + vam_confirm_boost  (default boost = 0.2)
  elif vam is not None and sign(vam) != sign(raw_divergence):
    // VAM contradicts divergence → dampen
    vam_multiplier = 1.0 - vam_contradict_penalty  (default penalty = 0.15)
  else:
    vam_multiplier = 1.0

Step 5: ATR normalization
  // Normalize to make edge comparable across different volatility regimes
  atr = features["ATR"]
  close = bar_data["close"]
  if atr > 0 and close > 0:
    volatility_scalar = atr / close  // fractional ATR
    normalized_divergence = raw_divergence / (volatility_scalar * norm_scale)
      // norm_scale (default 100) controls sensitivity
  else:
    normalized_divergence = raw_divergence

Step 6: Residual momentum filter
  // Use residual momentum as a quality gate — divergence is stronger
  // when residual (unexplained) momentum supports it
  res_mom = eng_residual_momentum
  if res_mom is not None:
    if sign(res_mom) == sign(raw_divergence):
      residual_boost = 1.0 + residual_weight  (default 0.15)
    else:
      residual_boost = 1.0
  else:
    residual_boost = 1.0

Step 7: Cross-sectional context
  // Asset diverging from market momentum is more meaningful
  altcoin_mom = eng_altcoin_market_momentum
  if altcoin_mom is not None and abs(altcoin_mom) > 0.5:
    if sign(raw_divergence) != sign(altcoin_mom):
      // Asset diverges opposite to market → stronger signal
      market_divergence_bonus = 1.0 + market_divergence_weight  (default 0.2)
    else:
      market_divergence_bonus = 1.0
  else:
    market_divergence_bonus = 1.0

  // High-beta assets have noisier divergences → dampen
  beta = eng_altcoin_beta
  if beta is not None and beta > 1.5:
    beta_dampener = 1.0 / (1.0 + (beta - 1.5) * beta_penalty_weight)  (default 0.3)
  else:
    beta_dampener = 1.0

Step 8: Final edge score
  edge_score = normalized_divergence * vam_multiplier * residual_boost
               * market_divergence_bonus * beta_dampener
```

### 7.6. Gate Conditions

For `edge_score != 0`, ALL must pass:
1. At least `min_confirming_indicators` (default 2) out of {RSI, MACD, MFI} show divergence in the same direction.
2. `|raw_divergence| > min_divergence_magnitude` (default 0.1) — filter out noise.
3. Rolling slope data is available (requires `divergence_lookback` bars of history for all slope calculations).

If gates fail, return `edge_score = 0.0`, `conviction = 0.0`.

### 7.7. Conviction Calculation

```
// Count confirming indicators (0-3)
n_confirming = count of {RSI, MACD, MFI} that show divergence in same direction

conviction = clamp(
    base_conviction
    + agreement_bonus * (n_confirming - min_confirming_indicators) / (3 - min_confirming_indicators)
    + magnitude_bonus * min(|raw_divergence| / divergence_saturation, 1.0),
    0.0, 1.0
)

Where:
  base_conviction = 0.3 (default)
  agreement_bonus = 0.35 (default) — full bonus when all 3 indicators confirm
  magnitude_bonus = 0.35 (default) — scales with divergence depth
  divergence_saturation = 2.0 (default) — divergence magnitude beyond this caps bonus
```

### 7.8. Hyperparameters

| Name | Type | Default | Low | High | Step | Description |
|------|------|---------|-----|------|------|-------------|
| `divergence_lookback` | int | 14 | 8 | 30 | 1 | Bars for rolling slope calculation |
| `weight_rsi` | float | 0.4 | 0.1 | 0.6 | 0.05 | RSI divergence weight |
| `weight_macd` | float | 0.35 | 0.1 | 0.6 | 0.05 | MACD histogram divergence weight |
| `weight_mfi` | float | 0.25 | 0.1 | 0.5 | 0.05 | MFI divergence weight |
| `min_confirming_indicators` | int | 2 | 1 | 3 | 1 | Minimum indicators showing divergence |
| `min_divergence_magnitude` | float | 0.1 | 0.01 | 0.5 | 0.01 | Noise floor for raw divergence |
| `vam_confirm_boost` | float | 0.2 | 0.0 | 0.5 | 0.05 | Edge boost when VAM confirms |
| `vam_contradict_penalty` | float | 0.15 | 0.0 | 0.4 | 0.05 | Edge dampening when VAM contradicts |
| `norm_scale` | float | 100.0 | 50.0 | 200.0 | 10.0 | ATR normalization sensitivity |
| `residual_weight` | float | 0.15 | 0.0 | 0.4 | 0.05 | Boost when residual momentum confirms |
| `market_divergence_weight` | float | 0.2 | 0.0 | 0.5 | 0.05 | Boost when asset diverges from market |
| `beta_penalty_weight` | float | 0.3 | 0.0 | 0.6 | 0.05 | High-beta noise dampener |
| `base_conviction` | float | 0.3 | 0.1 | 0.5 | 0.05 | Floor conviction |
| `agreement_bonus` | float | 0.35 | 0.1 | 0.5 | 0.05 | Conviction bonus from indicator agreement |
| `magnitude_bonus` | float | 0.35 | 0.1 | 0.5 | 0.05 | Conviction bonus from divergence magnitude |
| `divergence_saturation` | float | 2.0 | 0.5 | 5.0 | 0.5 | Divergence magnitude where bonus saturates |

### 7.9. Entry Conditions

All must pass:
1. Sufficient history for slope calculation (`divergence_lookback` bars of RSI, MACD histogram, MFI available).
2. At least `min_confirming_indicators` indicators show divergence in the same direction.
3. `|raw_divergence| > min_divergence_magnitude`.

### 7.10. Direction Logic

- Bullish divergence (price falling, indicators rising) → positive `edge_score` → **LONG**
- Bearish divergence (price rising, indicators falling) → negative `edge_score` → **SHORT**

Direction is embedded in the sign of `edge_score`.

### 7.11. Minimum History Bars

**50** — `divergence_lookback` (up to 30) + rolling slope warmup + `eng_residual_momentum` (50-bar OLS window). Use 50 as safe minimum.

### 7.12. ModelMeta

```python
meta = ModelMeta(
    name="DivergenceEdgeScorer",
    required_indicators=["RSI", "MACD", "MFI", "Momentum", "LinReg", "ATR"],
    required_fields=[
        "RSI", "MACD", "MFI", "Momentum", "LinReg", "ATR",
        "eng_volume_adjusted_momentum", "eng_atr_normalized_return",
        "eng_residual_momentum",
        "eng_altcoin_market_momentum", "eng_altcoin_beta",
    ],
    hyperparameter_schema={...},  # as defined in §7.8
    min_history_bars=50,
)
```

### 7.13. Internal State Requirements

The `DivergenceEdgeScorer` needs rolling buffers to compute linear regression slopes. These should be stored as instance variables in `__init__`:

```python
def __init__(self, params):
    super().__init__(params)
    lookback = self.params["divergence_lookback"]
    self._rsi_buf: deque = deque(maxlen=lookback)
    self._macd_hist_buf: deque = deque(maxlen=lookback)
    self._mfi_buf: deque = deque(maxlen=lookback)
    self._price_slope_buf: deque = deque(maxlen=lookback)
```

For `batch_evaluate()`, compute slopes vectorized using `numpy` rolling windows (not deques).

---

## 8. Implementation Details

### 8.1. Linear Regression Slope Helper

Both models need a simple OLS slope computation. Reuse the existing `_compute_linreg_batch` from `src/libs/features/indicators/momentum/linreg.py` for batch mode.

For single-tick mode, implement a lightweight helper in a shared location or inline:

```python
def _ols_slope(values: deque) -> float | None:
    """Compute OLS slope over a deque of float values."""
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if abs(den) < 1e-12:
        return 0.0
    return num / den
```

### 8.2. Feature Extraction Pattern

Follow the same pattern as existing models for extracting indicator values from `FeatureVector.features`:

```python
# Scalar indicators
rsi = features.features.get("RSI")

# Dict-output indicators (ADX, MACD)
macd_data = features.features.get("MACD")
macd_hist = macd_data.get("histogram") if isinstance(macd_data, dict) else None

# Engineered features (already floats, prefixed with eng_)
regime_score = features.features.get("eng_regime_score")
mr_z = features.features.get("eng_mean_reversion_z")
```

### 8.3. Batch Evaluate

Both models must implement `batch_evaluate(feature_df: pd.DataFrame) -> pd.Series`:

- Return a `pd.Series` of `float` edge_scores (not directions!).
- The `ScoringModel.batch_evaluate()` is the raw ABC method — no template-method wrapper like `BaseModel`.
- Use vectorized numpy/pandas operations for slope calculations over rolling windows.
- For batch column naming, follow the convention: `eng_regime_score`, `eng_mean_reversion_z`, etc. for engineered features, and `MACD_histogram`, `ADX_adx` for flattened indicator sub-fields.

---

## 9. Config Additions

### `configs/models.yaml` — add `scoring_models` section

```yaml
scoring_models:
  assets:
    default:
      timeframes:
        default:
          RegimePullbackScorer:
            enabled: true
            params:
              regime_threshold: -0.1
              min_z_depth: 1.0
              rsi_oversold_gate: 40
              rsi_overbought_gate: 60
              squeeze_weight: 0.3
              breadth_weight: 0.2
              btc_dom_weight: 0.3
          DivergenceEdgeScorer:
            enabled: true
            params:
              divergence_lookback: 14
              weight_rsi: 0.4
              weight_macd: 0.35
              weight_mfi: 0.25
              min_confirming_indicators: 2
              min_divergence_magnitude: 0.1
    BTCUSDT:
      timeframes:
        1h:
          RegimePullbackScorer:
            enabled: true
            params:
              btc_dom_weight: 0.0  # BTC itself is not affected by BTC dominance
          DivergenceEdgeScorer:
            enabled: true
```

---

## 10. StrategyWorker Integration

### Changes to `src/apps/strategy_app/strategy_worker.py`

```python
# Add import
from apps.strategy_app.scoring_model_manager import ScoringModelManager

# In __init__:
self.scoring_model_manager = ScoringModelManager(asset, timeframe)

# In start():
self.scoring_model_manager.validate_feature_coverage()

# In process_features():
outputs = self.model_manager.evaluate(feature_vec)
scoring_outputs = self.scoring_model_manager.evaluate(feature_vec)  # NEW

selected = self.selection_layer.select(
    model_outputs=outputs,
    scoring_outputs=scoring_outputs,  # was None
    feature_vec=feature_vec,
)
```

---

## 11. Registration

### `src/libs/models/__init__.py`

```python
# Add at the end:
import libs.models.regime_pullback  # noqa: F401
import libs.models.divergence_edge  # noqa: F401
```

This triggers `@ScoringModelRegistry.register(...)` decorators on import.

---

## 12. Test Requirements

### 12.1. `tests/test_scoring_registry.py`
- Register a mock scoring model, retrieve it, list all.
- Verify `KeyError` for unknown model name.
- Verify decorator returns class unchanged.

### 12.2. `tests/test_scoring_model_manager.py`
- Load scoring models from mock config.
- Verify fallback chain (asset/tf → asset/default → default/tf → default/default).
- Verify `enabled: false` skips model.
- Verify `validate_feature_coverage()` raises on missing features.
- Verify `evaluate()` returns `list[ScoringOutput]`.

### 12.3. `tests/test_regime_pullback_scorer.py`

| Test Case | Assertion |
|-----------|-----------|
| Gate: ranging regime + deep pullback + RSI confirms | `edge_score != 0`, correct sign |
| Gate: trending regime (ADX high) | `edge_score == 0` |
| Gate: shallow pullback (z < min_z_depth) | `edge_score == 0` |
| Gate: RSI does not confirm direction | `edge_score == 0` |
| LONG: price below KAMA (negative z) | `edge_score > 0` |
| SHORT: price above KAMA (positive z) | `edge_score < 0` |
| Squeeze bonus increases edge | deeper squeeze → larger `|edge_score|` |
| BTC dominance penalty (alt LONG) | high BTC.D → lower positive edge |
| BTC dominance no penalty (BTCUSDT) | `btc_dom_weight=0` → no penalty |
| Breadth supportive | positive breadth → larger edge |
| Conviction scales with depth | deeper z → higher conviction |
| Conviction caps at 1.0 | extreme z → conviction ≤ 1.0 |
| Missing eng features → graceful | `edge_score == 0` when missing |
| batch_evaluate returns correct length | Series length matches DataFrame |
| batch_evaluate temporal ordering | Non-monotonic index raises ValueError |

### 12.4. `tests/test_divergence_edge_scorer.py`

| Test Case | Assertion |
|-----------|-----------|
| Bullish divergence: price down + RSI+MACD up | `edge_score > 0` |
| Bearish divergence: price up + RSI+MACD down | `edge_score < 0` |
| No divergence: price and indicators agree | `edge_score == 0` |
| Gate: only 1 indicator diverges (min=2) | `edge_score == 0` |
| Gate: divergence below min magnitude | `edge_score == 0` |
| VAM confirms → boosted edge | with vs without VAM confirmation |
| VAM contradicts → dampened edge | VAM opposite → smaller |edge| |
| High beta dampens edge | beta > 1.5 → smaller |edge| |
| Market divergence bonus | asset vs market divergence → boost |
| Residual momentum boost | confirming res_mom → larger edge |
| Conviction scales with agreement | 3 indicators > 2 indicators |
| Conviction scales with magnitude | larger divergence → higher conviction |
| Missing cross-sectional → degrades gracefully | edge still computed, just without bonuses |
| Insufficient lookback history | `edge_score == 0` |
| batch_evaluate vectorized | Matches single-tick for same data |
| batch_evaluate returns correct length | Series length matches DataFrame |

---

## 13. Validation Checklist

- [ ] Both models return `ScoringOutput` (not `ModelOutput`)
- [ ] Both models registered via `@ScoringModelRegistry.register()`
- [ ] Edge scores are continuous floats (not binary -1/0/1)
- [ ] Direction is embedded in sign of edge_score, NOT as a separate field
- [ ] No look-ahead bias: all rolling computations use only past/current bar data
- [ ] Point-in-time correctness: engineered features are computed before model evaluation
- [ ] No modification to existing models, registries, or contracts
- [ ] Config fallback chain works correctly for scoring_models
- [ ] `StrategyWorker` passes scoring_outputs to SelectionLayer
- [ ] `SelectionLayer.normalize_scoring_output()` correctly handles new model outputs
- [ ] All engineered features degrade gracefully (return 0.0 or None when index data unavailable)
- [ ] batch_evaluate() and evaluate() produce consistent results for same input
- [ ] All existing tests still pass (zero regressions)
- [ ] New tests cover gate conditions, direction logic, edge magnitude, conviction bounds, graceful degradation

---

## 14. Implementation Order

1. **`ScoringModelRegistry`** — 1 file, trivial, unblocks everything else
2. **`RegimePullbackScorer`** — model.py + `__init__.py`
3. **`DivergenceEdgeScorer`** — model.py + `__init__.py`
4. **`ScoringModelManager`** — mirrors ModelManager pattern
5. **Registration imports** in `src/libs/models/__init__.py`
6. **StrategyWorker integration** — 3 lines changed
7. **Config additions** to `configs/models.yaml`
8. **Tests** — all 4 test files
9. **Smoke test** — run full test suite, verify zero regressions

---

## 15. Architecture Tradeoffs

### Decision: Separate ScoringModelRegistry vs extending ModelRegistry

**Chosen:** Separate `ScoringModelRegistry`.

**Rationale:** `ModelRegistry` stores `Type[BaseModel]` and `ModelManager` calls `.evaluate() → ModelOutput`. Scoring models extend `ScoringModel` (different ABC) and return `ScoringOutput`. Mixing them in one registry would require type unions and runtime isinstance checks throughout `ModelManager`. A parallel registry keeps the type system clean and follows the existing pattern of separate concerns.

**Rejected alternative:** Single unified registry with a `model_type` discriminator. This would complicate `ModelManager` and require it to handle two different return types, violating single-responsibility.

### Decision: ScoringModelManager vs extending ModelManager

**Chosen:** Separate `ScoringModelManager`.

**Rationale:** Same as above — different ABC, different output types. `ModelManager.evaluate()` returns `list[ModelOutput]` while `ScoringModelManager.evaluate()` returns `list[ScoringOutput]`. Config is also separate (`scoring_models` vs `models` root key) to keep asset-level configuration clean.

### Decision: Config root key `scoring_models` vs nesting under `models`

**Chosen:** Separate top-level `scoring_models` key.

**Rationale:** Keeps the config flat and explicit. An operator can enable/disable scoring models independently from threshold models. Nesting would create a deeper YAML structure and complicate the fallback chain resolution.

---

## 16. Risks

| Risk | Mitigation |
|------|------------|
| Divergence slope calculation sensitive to lookback period | `divergence_lookback` is a tunable hyperparameter (8-30) |
| High-frequency noise in short-timeframe slopes | `min_divergence_magnitude` gate filters noise; ATR normalization adjusts |
| Cross-sectional features unavailable (no TV data yet) | All cross-sectional terms degrade gracefully to neutral (1.0 multiplier or 0.0 addend) |
| Edge scores not comparable across models | SelectionLayer already normalizes — both models feed into the same pipeline |
| Overfitting on hyperparameter count (11 + 16 params) | Defaults are conservative; Optuna optimization deferred to Phase 3 |
| Weight hyperparameters (weight_rsi + weight_macd + weight_mfi) don't sum to 1.0 | Not required — they are relative weights, not probabilities. Normalization happens via ATR scaling. |
