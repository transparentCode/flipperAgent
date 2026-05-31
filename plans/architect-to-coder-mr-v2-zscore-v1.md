---
goal: Replace binary-threshold MeanReversionModel with continuous z-score scoring model
stage: architect-to-coder
date_created: 2026-05-31
last_updated: 2026-05-31
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, mean-reversion, scoring-model, z-score, regime-ensemble]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: MeanReversion v2 — Continuous Z-Score Model

## 1. Objective

Replace the structurally broken binary-threshold `MeanReversionModel` with a
continuous z-score scoring model that:

- Emits a **continuous `edge_score`** (float, unbounded) on every bar, not binary
  direction
- Uses **z-score normalization** to avoid hard thresholds that overfit
- Produces **50–200 meaningful signals** (|edge_score| > 0.2) per 6 months BTC 1h
- Applies **ADX soft scaling** via sigmoid to attenuate edge in trending markets
- Integrates natively with the `RegimeEnsembleBlender` via `ScoringOutput`

### Why the Current Model Is Broken

| Metric | Value | Problem |
|--------|-------|---------|
| Signals in 4345 bars (6mo) | 3 | RSI thresholds at 15/76 = below 1st / above 99th percentile |
| Relaxed to 33/67 density | ~101 signals | Edge drops to ~0% (no structural alpha) |
| Optimizer result | Sharpe +1.14, 13 trades | Overfit to 3 extreme events |
| QUIET_RANGE weight available | 0.71–0.86 design target | Nothing to weight — model is silent |
| Momentum in QUIET_RANGE | Sharpe −1.03 | Anti-suited but fills the vacuum |

Root cause: binary AND-gates (RSI threshold × BB threshold × ADX gate) create a
triple-filter trap where each condition independently kills density. Optuna finds
the intersection of extreme events and overfits to them.

---

## 2. Scope Boundaries

### In Scope

- Complete rewrite of `src/libs/models/mean_reversion/model.py`
- Minimal extension to `src/libs/models/scoring_base.py` (type annotation)
- Add `"scoring"` migration mode to `src/apps/strategy_app/model_manager.py`
- Merge path in `src/apps/strategy_app/strategy_worker.py` for scoring model outputs
- Config update in `configs/models.yaml`
- Unit tests for the new model

### Explicit Non-Goals

- **NO re-addition of CCI / MFI / 5-voter complexity** — the enhanced MR with 5
  SS voters already failed OOS and was reverted
- NO changes to `RegimeEnsembleBlender` (it already handles `ScoringOutput`)
- NO changes to `ScoringOutput` schema
- NO changes to `configs/features.yaml` (all required indicators already exist)
- NO Optuna optimization in this handoff (separate follow-up)
- NO changes to other models (Momentum, SqueezeBreakout)
- NO blender weight changes in this handoff (separate notebook validation)

---

## 3. Model Architecture

```
                 ┌────────────────────────────────────────────────┐
                 │            MeanReversionModel v2               │
                 │         (extends ScoringModel)                 │
                 │         model_type = "scoring"                 │
                 └────────────────────┬───────────────────────────┘
                                      │
               ┌──────────────────────┼──────────────────────┐
               │                      │                      │
        ┌──────▼──────┐       ┌───────▼──────┐      ┌───────▼──────┐
        │  RSI Z-Score │       │ BB Position  │      │ KAMA Dev /   │
        │              │       │   Z-Score    │      │    ATR       │
        │ -(RSI−50)    │       │ -(pct−0.5)×2 │      │ -(Δ / ATR)  │
        │  / rsi_scale │       │              │      │              │
        └──────┬───────┘       └──────┬───────┘      └──────┬───────┘
               │ × w_rsi              │ × w_bb              │ × w_kama
               └──────────────────────┼──────────────────────┘
                                      │ Σ (weighted sum)
                                      ▼
                             ┌────────────────┐
                             │   raw_edge     │
                             └───────┬────────┘
                                     │
                                     │ × α_ADX
                                     │
                             ┌───────▼────────┐
                             │  ADX Sigmoid   │
                             │ 1/(1+exp(      │
                             │ (ADX−c)/s))    │
                             └───────┬────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │  edge_score = raw_edge × α_ADX │
                    │  conviction = |tanh(raw_edge)| │
                    │           ↓                    │
                    │      ScoringOutput             │
                    └────────────────────────────────┘
```

### Design Rationale

| Component | Why | Alternative Rejected |
|-----------|-----|---------------------|
| RSI z-score | Continuous oscillator deviation; already available in pipeline | Binary RSI thresholds (current model — overfit) |
| BB percentile | Continuous price-envelope position; naturally bounded but extends beyond bands for extremes | BB touch/cross binary (same problem as RSI) |
| KAMA deviation / ATR | Adaptive MA deviation adds a distinct signal from a different lookback; ATR normalization makes it asset-agnostic | CCI (rejected per constraint #8 — was part of failed 5-voter) |
| ADX sigmoid | Soft regime filter avoids the hard-gate density kill | ADX < threshold binary (current model — kills 50%+ of bars) |
| Weighted sum (not voting) | Continuous composition preserves magnitude information | Majority voting (failed in enhanced MR) |

---

## 4. Scoring Formula — Mathematical Specification

### Inputs (per bar)

| Symbol | Source | Column (batch) | Live access |
|--------|--------|----------------|-------------|
| $RSI_t$ | RSI indicator (14-period) | `RSI` | `features.features["RSI"]` |
| $BB_{upper,t}$ | BollingerBands (20, 2σ) | `BollingerBands_upper` | `features.features["BollingerBands"]["upper"]` |
| $BB_{lower,t}$ | BollingerBands (20, 2σ) | `BollingerBands_lower` | `features.features["BollingerBands"]["lower"]` |
| $close_t$ | Bar data | `close` | `features.bar_data["close"]` |
| $KAMA_t$ | KAMA\_fast (period 5) | `KAMA_fast` (verify) | `features.features["KAMA_fast"]` |
| $ATR_t$ | ATR (14-period) | `ATR` (verify) | `features.features["ATR"]` |
| $ADX_t$ | ADX (14-period) | `ADX_adx` | `features.features["ADX"]["adx"]` |

> **Coder note**: Verify the exact batch DataFrame column names for KAMA_fast and
> ATR by inspecting the feature pipeline output. They may be `KAMA_fast_kama` and
> `ATR_atr` or similar depending on indicator flattening convention.

### Step 1: Component Z-Scores

**RSI z-score** (contrarian — low RSI → positive edge):

$$z_{RSI} = -\frac{RSI_t - 50}{s_{RSI}}$$

where $s_{RSI}$ is the `rsi_scale` hyperparameter (~15, approximating the
population std of RSI). Typical range: $z_{RSI} \in [-3.3, +3.3]$.

**Bollinger Band position** (contrarian — below midband → positive edge):

$$bb_{pct} = \frac{close_t - BB_{lower,t}}{BB_{upper,t} - BB_{lower,t}}$$

$$z_{BB} = -(bb_{pct} - 0.5) \times 2$$

When price is within bands: $z_{BB} \in [-1, +1]$. When price is beyond bands
(e.g. close < BB_lower), $z_{BB} > 1$ — extra signal for extremes. Guard:
if $BB_{upper} = BB_{lower}$ (degenerate bands), set $z_{BB} = 0$.

**KAMA deviation** (contrarian, ATR-normalized):

$$z_{KAMA} = -\frac{close_t - KAMA_t}{ATR_t}$$

ATR normalization makes the deviation comparable across assets and volatility
regimes. Typical range: $z_{KAMA} \in [-3, +3]$. Guard: if $ATR_t = 0$, set
$z_{KAMA} = 0$.

### Step 2: Composite Raw Edge

$$edge_{raw} = w_{RSI} \cdot z_{RSI} + w_{BB} \cdot z_{BB} + w_{KAMA} \cdot z_{KAMA}$$

The weights are **not** normalized to sum to 1 — the blender's per-model weight
controls the overall MR contribution. The absolute scale of `edge_score` is
irrelevant for ranking; what matters is relative magnitude and sign.

With defaults $(0.4, 0.4, 0.2)$ and typical inputs:
- Mild MR condition (RSI=40, bb_pct=0.3, kama_dev=0.5): raw ≈ 0.27 + 0.16 + 0.10 = 0.53
- Strong MR condition (RSI=25, bb_pct=0.05, kama_dev=2.0): raw ≈ 0.67 + 0.36 + 0.40 = 1.43
- Anti-MR (RSI=70, bb_pct=0.9, kama_dev=−1.5): raw ≈ −0.53 − 0.32 − 0.30 = −1.15

### Step 3: ADX Soft Scaling

$$\alpha_{ADX} = \frac{1}{1 + \exp\left(\frac{ADX_t - c_{ADX}}{s_{ADX}}\right)}$$

| ADX value | α (defaults c=25, s=5) | Interpretation |
|-----------|------------------------|----------------|
| 10 | 0.95 | Strong ranging → preserve edge |
| 20 | 0.73 | Mild ranging → slight attenuation |
| 25 | 0.50 | Midpoint |
| 30 | 0.27 | Mild trending → significant attenuation |
| 40 | 0.05 | Strong trending → near-zero edge |

### Step 4: Final Edge Score

$$edge\_score = edge_{raw} \times \alpha_{ADX}$$

### Step 5: Conviction

$$conviction = |\tanh(edge_{raw})|$$

This maps any raw edge magnitude to $[0, 1)$ with natural saturation. Note:
uses $edge_{raw}$ (before ADX scaling) so that conviction reflects the MR
signal strength independent of trend suppression.

### Graceful Degradation

When any input is missing (`None` / `NaN`):

| Missing Input | Behavior |
|---------------|----------|
| RSI | Set $z_{RSI} = 0$ |
| BB_upper or BB_lower | Set $z_{BB} = 0$ |
| KAMA_fast | Set $z_{KAMA} = 0$ |
| ATR | Set $z_{KAMA} = 0$ (can't normalize) |
| ADX | Set $\alpha_{ADX} = 0.5$ (neutral) |
| close | Return edge_score = 0.0, conviction = 0.0 |

---

## 5. Hyperparameter Schema

| Name | Type | Default | Low | High | Step | Purpose |
|------|------|---------|-----|------|------|---------|
| `rsi_scale` | float | 15.0 | 5.0 | 30.0 | 1.0 | RSI z-score denominator (≈ population std of RSI) |
| `w_rsi` | float | 0.4 | 0.1 | 0.8 | 0.05 | Weight for RSI z-score component |
| `w_bb` | float | 0.4 | 0.1 | 0.8 | 0.05 | Weight for BB position component |
| `w_kama` | float | 0.2 | 0.0 | 0.5 | 0.05 | Weight for KAMA deviation component |
| `adx_center` | float | 25.0 | 15.0 | 40.0 | 1.0 | ADX sigmoid midpoint |
| `adx_steepness` | float | 5.0 | 2.0 | 15.0 | 1.0 | ADX sigmoid steepness |

**6 parameters** (vs 5 in the old model). All are pointwise (no lookback /
rolling window), making live single-tick evaluation trivial and batch evaluation
Numba-friendly.

**Why these ranges:**
- `rsi_scale 5–30`: RSI population std is ~12–18 on BTC 1h; range covers
  aggressive to conservative normalization
- `w_rsi + w_bb + w_kama` is unconstrained (not normalized to 1) — the
  blender's per-model weight controls overall MR contribution
- `adx_center 15–40`: covers the standard ADX interpretation range
  (< 20 = weak trend, > 25 = strong trend)
- `adx_steepness 2–15`: 2 = very sharp transition (nearly binary),
  15 = very gradual (nearly flat scaling)

---

## 6. Pseudocode

### `evaluate(features: FeatureVector) -> ScoringOutput`

```python
def evaluate(self, features: FeatureVector) -> ScoringOutput:
    # 1. Extract inputs
    rsi = extract_rsi(features.features)
    bb_upper = self._extract_bb(features.features, "upper")
    bb_lower = self._extract_bb(features.features, "lower")
    close = features.bar_data.get("close")
    kama = self._extract_scalar(features.features, "KAMA_fast")
    atr = self._extract_scalar(features.features, "ATR")
    adx = self._extract_adx(features.features)

    # 2. Bail-out if close is missing
    if close is None or close == 0.0:
        return ScoringOutput(
            model_name=self.meta.name, asset=..., timeframe=...,
            timestamp=..., edge_score=0.0, conviction=0.0,
            metadata={"trigger": "missing_close"},
        )

    # 3. Component z-scores (graceful degradation)
    z_rsi = -(rsi - 50.0) / self.params["rsi_scale"] if rsi is not None else 0.0

    if bb_upper is not None and bb_lower is not None:
        bb_range = bb_upper - bb_lower
        if bb_range > 0:
            bb_pct = (close - bb_lower) / bb_range
            z_bb = -(bb_pct - 0.5) * 2.0
        else:
            z_bb = 0.0
    else:
        z_bb = 0.0

    if kama is not None and atr is not None and atr > 0:
        z_kama = -(close - kama) / atr
    else:
        z_kama = 0.0

    # 4. Raw composite edge
    raw_edge = (
        self.params["w_rsi"] * z_rsi
        + self.params["w_bb"] * z_bb
        + self.params["w_kama"] * z_kama
    )

    # 5. ADX soft scaling
    if adx is not None:
        adx_scale = 1.0 / (1.0 + math.exp(
            (adx - self.params["adx_center"]) / self.params["adx_steepness"]
        ))
    else:
        adx_scale = 0.5  # neutral if ADX missing

    edge_score = raw_edge * adx_scale

    # 6. Conviction
    conviction = abs(math.tanh(raw_edge))

    return ScoringOutput(
        model_name=self.meta.name,
        asset=features.asset,
        timeframe=features.timeframe,
        timestamp=features.timestamp,
        edge_score=edge_score,
        conviction=conviction,
        metadata={
            "z_rsi": z_rsi, "z_bb": z_bb, "z_kama": z_kama,
            "raw_edge": raw_edge, "adx_scale": adx_scale,
            "rsi": rsi, "adx": adx, "close": close,
        },
    )
```

### `_batch_evaluate_impl(feature_df: pd.DataFrame) -> pd.Series`

```python
@njit(cache=True)
def _batch_mr_zscore(
    rsi: np.ndarray, bb_upper: np.ndarray, bb_lower: np.ndarray,
    close: np.ndarray, kama: np.ndarray, atr: np.ndarray, adx: np.ndarray,
    rsi_scale: float, w_rsi: float, w_bb: float, w_kama: float,
    adx_center: float, adx_steepness: float,
) -> np.ndarray:
    """Numba-accelerated batch z-score computation."""
    n = len(rsi)
    edge = np.empty(n, dtype=np.float64)

    for i in range(n):
        # RSI z-score
        z_rsi = -(rsi[i] - 50.0) / rsi_scale if not np.isnan(rsi[i]) else 0.0

        # BB position z-score
        bb_range = bb_upper[i] - bb_lower[i]
        if bb_range > 0 and not np.isnan(close[i]):
            bb_pct = (close[i] - bb_lower[i]) / bb_range
            z_bb = -(bb_pct - 0.5) * 2.0
        else:
            z_bb = 0.0

        # KAMA deviation
        if not np.isnan(kama[i]) and atr[i] > 0:
            z_kama = -(close[i] - kama[i]) / atr[i]
        else:
            z_kama = 0.0

        # Raw composite
        raw = w_rsi * z_rsi + w_bb * z_bb + w_kama * z_kama

        # ADX soft scaling
        if not np.isnan(adx[i]):
            adx_scale = 1.0 / (1.0 + np.exp((adx[i] - adx_center) / adx_steepness))
        else:
            adx_scale = 0.5

        edge[i] = raw * adx_scale

    return edge


def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
    """Vectorized batch evaluation returning continuous float edge_scores."""
    # Extract arrays (fill NaN for missing columns)
    rsi = feature_df["RSI"].values if "RSI" in feature_df else np.full(len(feature_df), np.nan)
    bb_upper = feature_df["BollingerBands_upper"].values if "BollingerBands_upper" in feature_df else np.full(len(feature_df), np.nan)
    bb_lower = feature_df["BollingerBands_lower"].values if "BollingerBands_lower" in feature_df else np.full(len(feature_df), np.nan)
    close = feature_df["close"].values if "close" in feature_df else np.full(len(feature_df), np.nan)
    kama = ...  # verify column name: "KAMA_fast" or "KAMA_fast_kama"
    atr = ...   # verify column name: "ATR" or "ATR_atr"
    adx = feature_df["ADX_adx"].values if "ADX_adx" in feature_df else np.full(len(feature_df), np.nan)

    edge_arr = _batch_mr_zscore(
        rsi, bb_upper, bb_lower, close, kama, atr, adx,
        self.params["rsi_scale"], self.params["w_rsi"],
        self.params["w_bb"], self.params["w_kama"],
        self.params["adx_center"], self.params["adx_steepness"],
    )

    return pd.Series(edge_arr, index=feature_df.index)
```

**Key differences from old model:**
1. Returns `float Series` (continuous), not `int Series` (-1, 0, 1)
2. No cooldown / holding_period — every bar gets a score
3. No binary thresholds — all scoring is continuous
4. Numba kernel for performance

---

## 7. Affected Symbols, Modules, and Execution Flows

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `src/libs/models/mean_reversion/model.py` | Complete rewrite — same class name `MeanReversionModel`, same registry key `"MeanReversion"` | LOW — no external API change for class name or registry |
| `src/libs/models/scoring_base.py` | Add abstract method type annotations for `evaluate() -> ScoringOutput` and `_batch_evaluate_impl()` | LOW — 4 lines, marker class |
| `src/apps/strategy_app/model_manager.py` | Add `"scoring"` to `_VALID_MIGRATION_MODES`, add scoring model loading path, add `evaluate_scoring()` method | MEDIUM — touches model loading pipeline |
| `src/apps/strategy_app/strategy_worker.py` | Merge `evaluate_scoring()` results into blender input alongside `evaluate_adapted()` | LOW — additive, ~5 lines |
| `configs/models.yaml` | Change MR entry: `migration_mode: scoring`, update params | LOW — config only |

### Unchanged (Verify No Impact)

| File | Reason |
|------|--------|
| `src/libs/contracts/signal.py` | `ScoringOutput` schema unchanged |
| `src/libs/models/registry.py` | Decorator pattern unchanged |
| `src/libs/models/blender/ensemble.py` | Already handles `ScoringOutput` objects; no API change |
| `src/libs/models/legacy_adapter.py` | Still used by Momentum and SqueezeBreakout |
| `configs/features.yaml` | All required indicators (RSI, BB, ADX, KAMA_fast, ATR) already configured |
| `src/libs/models/momentum/model.py` | No changes |

### Blender Weight Key Convention

**Potential issue**: The blender config uses lowercase keys (`mean_reversion`,
`momentum`) but `ScoringOutput.model_name` is set from `ModelMeta.name` which
is CamelCase (`MeanReversion`, `Momentum`). The blender does
`weights.get(so.model_name, 0.0)` — case mismatch would yield default 0.0.

**Coder action**: Verify how the StrategyWorker or blender resolves this. Either:
- (a) The StrategyWorker lowercases model_name before passing to blender, or
- (b) The config keys should be CamelCase, or
- (c) The blender should normalize the lookup key

This affects all models, not just MR v2. Investigate and fix if needed.

---

## 8. Data Contracts and Interfaces

### ModelMeta (new)

```python
ModelMeta(
    name="MeanReversion",
    model_type="scoring",                    # was "direction"
    required_indicators=["RSI", "BollingerBands", "ADX", "KAMA_fast", "ATR"],
    required_fields=[
        "RSI",
        "BollingerBands_upper", "BollingerBands_lower",
        "ADX",
        "KAMA_fast",   # verify column name
        "ATR",         # verify column name
    ],
    hyperparameter_schema={...},             # see §5
    min_history_bars=30,                     # KAMA needs ~30 bars warm-up
)
```

### ScoringModel Base (updated)

```python
# src/libs/models/scoring_base.py — add type annotation
class ScoringModel(BaseModel):
    """Marker subclass for models that emit ScoringOutput."""

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ScoringOutput:  # type: ignore[override]
        ...

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        ...
```

### ModelManager Extension

```python
# Add to _VALID_MIGRATION_MODES
_VALID_MIGRATION_MODES = {"legacy", "adapted", "scoring", "native_scoring"}

# In __init__
self.scoring_models: list[ScoringModel] = []

# In _load_models, add elif branch:
elif migration_mode == "scoring":
    from libs.models.scoring_base import ScoringModel as ScoringModelType
    instance = model_cls(params)
    if not isinstance(instance, ScoringModelType):
        logger.warning(f"Model '{model_name}' has migration_mode='scoring' but "
                       f"does not extend ScoringModel. Falling back to adapted.")
        adapter = LegacyScoringAdapter(instance)
        self.adapted_models.append(adapter)
    else:
        self.scoring_models.append(instance)
        logger.info(f"Loaded scoring model {model_name} for {self.asset}/{self.timeframe}")

# New method
def evaluate_scoring(self, features: FeatureVector) -> list[ScoringOutput]:
    """Run native scoring models, returning ScoringOutput."""
    outputs: list[ScoringOutput] = []
    for model in self.scoring_models:
        try:
            output = model.evaluate(features)
            outputs.append(output)
        except Exception as e:
            logger.error(f"Scoring model {model.meta.name} failed: {e}", exc_info=True)
    return outputs
```

### StrategyWorker Merge Point

```python
# In strategy_worker.py, wherever blender.blend() is called:
adapted_outputs = self.model_manager.evaluate_adapted(features)
scoring_outputs = self.model_manager.evaluate_scoring(features)
all_scoring_outputs = adapted_outputs + scoring_outputs
blended = self.blender.blend(all_scoring_outputs, regime_features, mtf_agreement)
```

---

## 9. Config Changes (`configs/models.yaml`)

```yaml
MeanReversion:
  enabled: true
  migration_mode: scoring       # was: implicitly "legacy" / no migration_mode
  params:
    rsi_scale: 15.0
    w_rsi: 0.4
    w_bb: 0.4
    w_kama: 0.2
    adx_center: 25.0
    adx_steepness: 5.0
```

Apply this change under every asset/timeframe where MeanReversion is configured
(currently: BTCUSDT 1h, BTCUSDT 4h). Remove the old params (`rsi_oversold`,
`rsi_overbought`, `bb_entry_std`, `adx_regime_threshold`, `holding_period`).

Blender weights: **do not change yet** — keep MR at 0.00 in all groups until
notebook validation confirms the new model produces edge. The weights are a
separate follow-up.

---

## 10. Implementation Order

1. **`scoring_base.py`** — Add abstract method type annotations (4 lines)
2. **`mean_reversion/model.py`** — Complete rewrite with new class
3. **`model_manager.py`** — Add `"scoring"` migration mode (~25 lines)
4. **`strategy_worker.py`** — Merge scoring outputs into blender input (~5 lines)
5. **`configs/models.yaml`** — Update MR config for all asset/timeframes
6. **Unit tests** — `tests/models/mean_reversion/test_mr_v2.py`
7. **Integration verification** — Run existing model/blender tests, verify no regressions

Steps 1–2 can be done first and tested in isolation (the model can be
instantiated and evaluated standalone without ModelManager changes).

---

## 11. Acceptance Criteria

### Structural (must pass before any backtest)

| # | Criterion | How to verify |
|---|-----------|---------------|
| S1 | `MeanReversionModel` extends `ScoringModel` | `isinstance(model, ScoringModel)` |
| S2 | `evaluate()` returns `ScoringOutput` (not `ModelOutput`) | Type check in test |
| S3 | `edge_score` is continuous float (not {-1, 0, 1}) | Feed 100 random bars, assert >10 distinct values |
| S4 | `_batch_evaluate_impl()` returns float Series | `assert result.dtype == np.float64` |
| S5 | Batch/live parity | For same bar, `abs(batch_edge[i] - live_edge) < 1e-10` |
| S6 | ADX scaling works | Same inputs, ADX=15 → |edge| > ADX=40 → |edge| |
| S7 | Graceful degradation | Missing RSI/BB/KAMA → no crash, edge uses available components |
| S8 | Registry key unchanged | `ModelRegistry.get("MeanReversion")` returns new class |
| S9 | ModelManager loads with `migration_mode: scoring` | Integration test |
| S10 | No Numba compilation error on first call | Test with `cache=True` |

### Quantitative (notebook validation, post-implementation)

| # | Criterion | Target |
|---|-----------|--------|
| Q1 | Signal density (|edge_score| > 0.2) on BTC 1h 4345 bars | 50–300 bars |
| Q2 | Regime specificity: mean |edge| in QUIET_RANGE / mean |edge| in CLEAN_TREND | > 1.5× |
| Q3 | Standalone Sharpe in QUIET_RANGE (signal-weighted returns) | > 0.0 |
| Q4 | Walk-forward degradation (train vs OOS Sharpe) | < 50% drop |
| Q5 | Cross-asset: ETHUSDT 1h signals (|edge| > 0.2) | > 20 bars |

---

## 12. Validation Checklist

- [ ] All S1–S10 structural criteria pass
- [ ] Existing tests in `tests/models/` pass without modification
- [ ] Existing tests in `tests/models/blender/` pass without modification
- [ ] Model loads correctly in ModelManager with `migration_mode: scoring`
- [ ] No import errors or circular dependencies
- [ ] Numba `@njit` compiles without error on first batch call
- [ ] Blender receives `ScoringOutput` from the scoring model path
- [ ] The old `_apply_cooldown` Numba function is removed (not needed)
- [ ] KAMA_fast and ATR column names verified against actual feature pipeline output

---

## 13. Migration Path

### Phase 1 (This Handoff): `migration_mode: scoring`

- Add `"scoring"` as a valid migration mode in ModelManager
- MR v2 extends `ScoringModel`, returns `ScoringOutput` natively
- ModelManager loads it directly into `scoring_models` list (no adapter wrapping)
- StrategyWorker merges scoring outputs with adapted outputs before blending
- **Minimal blast radius**: Momentum and SqueezeBreakout remain `adapted`, untouched

### Phase 2 (Future): Momentum / SqueezeBreakout Migration

Once the `"scoring"` path is proven, other models can migrate from
`adapted` → `scoring` one at a time. This removes the `LegacyScoringAdapter`
dependency incrementally.

### Why Not Stay on `adapted` Mode

The `LegacyScoringAdapter` converts `ModelOutput(direction, conviction)` →
`ScoringOutput(edge_score = direction × conviction)`. This requires:
- `direction ∈ {-1, 0, 1}` — loses continuous magnitude
- `conviction ∈ [0, 1]` — clips edge information
- The reconstructed `edge_score ∈ [-1, 1]` — bounded, lossy

The entire point of MR v2 is continuous unbounded edge scores. The adapter
would destroy that information.

---

## 14. Blender Weight Recommendations (Post-Validation)

Proposed initial weights for notebook validation (DO NOT deploy before
backtest confirmation):

| Group | MR v2 | Momentum | SqueezeBreakout |
|-------|-------|----------|-----------------|
| CLEAN_TREND | 0.10 | 0.90 | 0.00 |
| VOLATILE_TREND | 0.05 | 0.95 | 0.00 |
| QUIET_RANGE | 0.60 | 0.40 | 0.00 |
| SQUEEZE | 0.30 | 0.70 | 0.00 |
| CHOPPY | 0.30 | 0.70 | 0.00 |
| TRANSITION | 0.10 | 0.90 | 0.00 |

Rationale:
- QUIET_RANGE: MR's primary regime; Momentum is −1.03 Sharpe here
- CLEAN_TREND / VOLATILE_TREND: ADX soft scaling already suppresses MR
  internally, but the blender also down-weights it
- SB stays zeroed per existing decision (Sharpe −16.66)

These weights should be optimized via walk-forward IC-based learning after
MR v2 is validated standalone.

---

## 15. Risks and Tradeoffs

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Z-score components are redundant (RSI ≈ BB position) | Medium | Low edge contribution from diversification | KAMA deviation is structurally distinct; Optuna will zero out redundant weights |
| Unconstrained weights allow one component to dominate | Low | Optuna finds w_rsi=0.8, w_bb=0.1, w_kama=0.0 — effectively single-indicator | Accept — if one component dominates, it's because it has more alpha. Better than forced diversification |
| ADX sigmoid steepness overfit | Medium | Sharp steepness ≈ hard threshold → same overfitting as v1 | Range floor at 2.0 prevents binary behavior; Optuna regularization helps |
| KAMA_fast column name mismatch | Medium | Batch evaluation produces all-zero z_kama | Coder must verify; graceful degradation means model still works (just loses one component) |
| Model_name vs blender weight key case mismatch | Medium | MR weight always 0.0 regardless of config | Investigate and fix (see §7 note). Affects all models. |
| 6 params still overfit on 4345 bars | Low | With 6 smooth params and purged k-fold, overfitting risk is low | Walk-forward validation (Q4 criterion) |

---

## 16. Completeness Statement

This handoff is **complete** for the coder agent to implement MR v2 without
guessing. The mathematical formula, all pseudocode, config changes, migration
strategy, affected files, acceptance criteria, and test specifications are
provided. The only thing the coder must verify empirically is the exact column
names for KAMA_fast and ATR in the batch DataFrame.

Quantitative validation (acceptance criteria Q1–Q5) will be performed in a
separate notebook session after implementation.
