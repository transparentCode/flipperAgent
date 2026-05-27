---
goal: Build Optuna optimization infrastructure for RegimePullbackScorer (11 params) and DivergenceEdgeScorer (16 params)
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, optimization, scoring-models, optuna, walk-forward]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder: Scoring Model Optimization Infrastructure v1

## 1. Objective

Build Optuna-based hyperparameter optimization for the two scoring models:
- **RegimePullbackScorer**: 9 optimizable + 2 fixed = 11 total hyperparameters
- **DivergenceEdgeScorer**: 14 optimizable + 2 fixed = 16 total hyperparameters

These models emit **continuous `edge_score` floats** (not binary direction), which fundamentally changes the objective function design compared to the existing SqueezeBreakout/MeanReversion optimizers that use `compute_returns(directions, close)`.

Key deliverables:
1. Shared scoring-model feature pipeline (OHLCV → indicators → engineered features → feature DataFrame)
2. Purged k-fold CV utility
3. Signal-weighted-return objective function for continuous edge scores
4. Per-model `optimizer.py` + `optimize.py` CLI following the existing pattern
5. `batch_evaluate()` fidelity fix for DivergenceEdgeScorer

## 2. Scope Boundaries

### In Scope
- Shared feature pipeline for scoring model optimization (`libs/optim_utils/scoring_feature_pipeline.py`)
- Purged time-series CV utility (`libs/optim_utils/cv.py`)
- Per-model optimizer + CLI for RegimePullbackScorer and DivergenceEdgeScorer
- DivergenceEdgeScorer `batch_evaluate()` extension (VAM + residual adjustments)
- Optimization config entries in `configs/optimization.yaml`

### Out of Scope (Explicit Non-Goals)
- Cross-sectional / TradingView feature optimization (Phase 2 — requires TV data pipeline)
- Per-asset parameter specialization (Phase 2 — start with universal params)
- Changes to the ScoringModel ABC or ScoringModelRegistry
- Changes to EngineeredFeatureManager or any engineered feature implementations
- Selection layer optimization
- Production deployment (cron, write-back promotion)

## 3. Affected Symbols, Modules, and Execution Flows

### New Files
| File | Purpose |
|------|---------|
| `src/libs/optim_utils/scoring_feature_pipeline.py` | Batch: OHLCV → indicators → engineered features → DataFrame |
| `src/libs/optim_utils/cv.py` | Purged k-fold time-series CV with embargo |
| `src/libs/models/regime_pullback/optimization/__init__.py` | Package init |
| `src/libs/models/regime_pullback/optimization/optimizer.py` | Objective function, `STUDY_DEFAULTS`, `FIXED_PARAMS`, `post_process_params()` |
| `src/libs/models/regime_pullback/optimization/optimize.py` | CLI entry point |
| `src/libs/models/divergence_edge/optimization/__init__.py` | Package init |
| `src/libs/models/divergence_edge/optimization/optimizer.py` | Objective function, `STUDY_DEFAULTS`, `FIXED_PARAMS`, `post_process_params()` |
| `src/libs/models/divergence_edge/optimization/optimize.py` | CLI entry point |
| `tests/libs/optim_utils/test_scoring_feature_pipeline.py` | Pipeline tests |
| `tests/libs/optim_utils/test_cv.py` | CV tests |
| `tests/libs/models/regime_pullback/optimization/test_optimizer.py` | Optimizer tests |
| `tests/libs/models/divergence_edge/optimization/test_optimizer.py` | Optimizer tests |

### Modified Files
| File | Change |
|------|--------|
| `src/libs/models/divergence_edge/model.py` | Extend `batch_evaluate()` with VAM + residual adjustments |
| `configs/optimization.yaml` | Add schedule entries for scoring models |

### Existing Files Referenced (Read-Only)
| File | Role |
|------|------|
| `src/libs/models/scoring_base.py` | ScoringModel ABC with `batch_evaluate() → pd.Series` |
| `src/libs/models/regime_pullback/model.py` | RegimePullbackScorer (11 params, meta, batch_evaluate) |
| `src/libs/models/divergence_edge/model.py` | DivergenceEdgeScorer (16 params, meta, batch_evaluate) |
| `src/libs/optim_utils/data_fetcher.py` | `fetch_historical_ohlcv()` — paginated Binance REST |
| `src/libs/optim_utils/scoring.py` | `compute_sharpe()`, `compute_max_drawdown()`, `BARS_PER_YEAR` |
| `src/libs/optim_utils/objective.py` | `build_suggest()` for Optuna trial → param mapping |
| `src/libs/optim_utils/runner.py` | `OptunaRunner` wrapper |
| `src/libs/optim_utils/param_writeback.py` | `write_best_params()`, `read_current_params()` |
| `src/libs/optim_utils/param_auditor.py` | `ParamAuditor` for current vs proposed comparison |
| `src/apps/signal_app/feature_manager.py` | `FeatureManager` — tick-by-tick indicator computation |
| `src/libs/features/engineered/manager.py` | `EngineeredFeatureManager` — tick-by-tick engineered features |
| `src/libs/models/mean_reversion/optimization/optimize.py` | Reference CLI pattern |
| `src/libs/models/squeeze_breakout/optimization/optimizer.py` | Reference optimizer pattern |

### Execution Flows Affected
- **Optimization flow only** — no changes to live signal processing, strategy evaluation, or selection layer.
- Scoring models' `batch_evaluate()` is used in optimization AND ParamAuditor. The DivergenceEdgeScorer fix improves audit accuracy too.

## 4. Data Contracts and Interfaces

### 4.1 Scoring Feature Pipeline

```python
# src/libs/optim_utils/scoring_feature_pipeline.py

def build_scoring_feature_df(
    ohlcv_df: pd.DataFrame,
    asset: str,
    timeframe: str,
) -> pd.DataFrame:
    """Build a feature DataFrame suitable for ScoringModel.batch_evaluate().

    Pipeline:
    1. Create FeatureManager(asset, timeframe) and prime with full history
    2. Process each bar to get raw indicator outputs
    3. Create EngineeredFeatureManager(asset, timeframe)
    4. Compute engineered features per bar (stateful, sequential)
    5. Flatten into DataFrame with columns matching FeatureVector.features keys

    Parameters
    ----------
    ohlcv_df : pd.DataFrame
        Must have columns: timestamp, open, high, low, close, volume
        Sorted by timestamp ascending.
    asset : str
        Trading pair (e.g. "BTCUSDT").
    timeframe : str
        Kline interval (e.g. "1h").

    Returns
    -------
    pd.DataFrame
        Columns include: all raw indicator outputs (RSI, MACD, ATR, ...),
        all engineered features (eng_regime_score, eng_mean_reversion_z, ...),
        plus OHLCV columns (open, high, low, close, volume).
        Rows with insufficient indicator warm-up are NaN.
        Index matches ohlcv_df index.

    Notes
    -----
    - Cross-sectional engineered features (btc_dominance_regime, market_cap_breadth,
      altcoin_market_momentum, altcoin_beta) will return 0.0 because index_data=None.
    - This is by design — the corresponding weight params are FIXED at defaults
      during Phase 1 optimization.
    """
```

**Implementation approach**: FeatureManager and EngineeredFeatureManager are stateful (tick-by-tick). The pipeline must:
1. Prime FeatureManager with first N bars (where N = max indicator lookback)
2. Then process remaining bars sequentially via `process_tick()`
3. For each bar, feed raw indicator outputs + bar data into `EngineeredFeatureManager.compute()`
4. Collect results into a list of dicts, then pd.DataFrame

**MACD column handling**: MACD indicator returns a dict `{"macd": float, "signal": float, "histogram": float}`. The pipeline must flatten this into separate columns: `MACD_macd`, `MACD_signal`, `MACD_histogram`. DivergenceEdgeScorer batch_evaluate expects `MACD_histogram` as a column name.

**BollingerBands / KeltnerChannel**: Return tuples `(middle, upper, lower)`. Flatten to `BollingerBands_middle`, `BollingerBands_upper`, `BollingerBands_lower` (and similarly for KC). SqueezeIntensity engineered feature handles the raw tuple via `features.get("BollingerBands")`, so keep the un-flattened version too.

### 4.2 Purged K-Fold CV

```python
# src/libs/optim_utils/cv.py

@dataclass
class CVFold:
    """A single cross-validation fold."""
    fold_idx: int
    train_df: pd.DataFrame
    test_df: pd.DataFrame


def purged_kfold_cv(
    df: pd.DataFrame,
    n_splits: int = 5,
    embargo_bars: int = 50,
) -> list[CVFold]:
    """Purged walk-forward k-fold cross-validation for time series.

    Splits data into n_splits contiguous blocks. For each fold i:
    - Train = blocks[0:i] (all blocks before test)
    - Gap = embargo_bars removed from end of train
    - Test = blocks[i]

    This is expanding-window, not sliding-window, so earlier folds have
    less training data. This mirrors real deployment (you always train
    on all available history).

    Parameters
    ----------
    df : pd.DataFrame
        Time-sorted feature DataFrame.
    n_splits : int
        Number of folds (default 5).
    embargo_bars : int
        Number of bars to remove from end of training set before test
        set begins. Prevents look-ahead from stateful indicator
        computation. Default 50 (max of min_history_bars across both
        scoring models).

    Returns
    -------
    list[CVFold]
        Folds 1 through n_splits-1 (fold 0 has no training data, skipped).
    """
```

**CV configuration**:
- `n_splits = 5`
- `embargo_bars = 50` (max of both models' `min_history_bars`)
- Fold 0 is skipped (no training data)
- Yields 4 usable folds

### 4.3 Scoring-Model Objective Function

The fundamental difference from binary models: scoring models emit **continuous `edge_score`** values, not direction integers. The objective must translate edge_score → PnL.

**Chosen approach: signal-weighted returns (option a)**

```python
def compute_signal_weighted_returns(
    edge_scores: np.ndarray,
    close_prices: np.ndarray,
    cost_bps: float = 10.0,
    max_position: float = 1.0,
) -> np.ndarray:
    """Compute per-bar strategy returns from continuous edge scores.

    position[t] = clip(edge_score[t], -max_position, max_position)
    bar_return[t] = (close[t+1] - close[t]) / close[t]
    strategy_return[t] = position[t] * bar_return[t]
    cost[t] = |position[t] - position[t-1]| * cost_bps / 10000

    Parameters
    ----------
    edge_scores : np.ndarray
        Continuous signed edge scores from batch_evaluate().
    close_prices : np.ndarray
        Close prices aligned with edge_scores.
    cost_bps : float
        Transaction cost in basis points per unit of position change.
    max_position : float
        Maximum absolute position size (clips edge_score). Default 1.0.

    Returns
    -------
    np.ndarray
        Per-bar strategy returns (length = len(close) - 1).
    """
```

Place this in `libs/optim_utils/scoring.py` alongside the existing `compute_returns()`.

**Why signal-weighted over threshold-based**: 
- Threshold-based introduces an extra hyperparameter (the threshold) that interacts with all other params
- Signal-weighted naturally rewards models that produce larger edge_scores on bars with larger returns
- Simpler, fewer degrees of freedom, captures alpha directly
- The position-sizing interpretation (edge_score ≈ position fraction) is economically natural

**Complete objective function formula per optimizer**:

```python
def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    n_splits: int = 5,
    embargo_bars: int = 50,
    regularization_lambda: float = 0.5,
) -> Callable[[optuna.Trial], float]:
    """Return Optuna objective with purged k-fold CV.

    For each trial:
    1. Suggest params (excluding FIXED_PARAMS)
    2. Merge with FIXED_PARAMS defaults
    3. For each CV fold:
        a. Instantiate model with suggested params
        b. batch_evaluate(train_df) — discard (warm-up only if needed)
        c. batch_evaluate(test_df) → edge_scores
        d. compute_signal_weighted_returns(edge_scores, close) → returns
        e. compute_sharpe(returns, timeframe) → sharpe_i
    4. Objective = mean(sharpe_folds) - λ * std(sharpe_folds)

    Regularization penalizes inconsistent performance across folds.
    λ = 0.5 balances exploitation vs robustness.
    """
```

## 5. Parameter Classification

### 5.1 RegimePullbackScorer (11 params)

| Param | Type | Default | Range | Step | Status | Rationale |
|-------|------|---------|-------|------|--------|-----------|
| `regime_threshold` | float | -0.1 | [-0.5, 0.3] | 0.05 | **OPTIMIZE** | Core gate threshold |
| `min_z_depth` | float | 1.0 | [0.5, 2.5] | 0.1 | **OPTIMIZE** | Core gate threshold |
| `rsi_oversold_gate` | int | 40 | [25, 50] | 1 | **OPTIMIZE** | Core gate threshold |
| `rsi_overbought_gate` | int | 60 | [50, 75] | 1 | **OPTIMIZE** | Core gate threshold |
| `squeeze_weight` | float | 0.3 | [0.0, 0.8] | 0.05 | **OPTIMIZE** | Weights non-TV feature (squeeze_intensity uses BB/KC) |
| `breadth_weight` | float | 0.2 | — | — | **FIXED** | Weights `eng_market_cap_breadth` (needs TOTAL2/TOTAL3 from TV) |
| `btc_dom_weight` | float | 0.3 | — | — | **FIXED** | Weights `eng_btc_dominance_regime` (needs BTC.D from TV) |
| `base_conviction` | float | 0.3 | [0.1, 0.5] | 0.05 | **OPTIMIZE** | Conviction scaling |
| `depth_bonus` | float | 0.4 | [0.1, 0.6] | 0.05 | **OPTIMIZE** | Conviction scaling |
| `max_z_for_full_conviction` | float | 3.0 | [1.5, 5.0] | 0.5 | **OPTIMIZE** | Conviction normalization |
| `regime_bonus` | float | 0.3 | [0.0, 0.5] | 0.05 | **OPTIMIZE** | Conviction scaling |

**Optimizable: 9 params. Fixed: 2 params.**

### 5.2 DivergenceEdgeScorer (16 params)

| Param | Type | Default | Range | Step | Status | Rationale |
|-------|------|---------|-------|------|--------|-----------|
| `divergence_lookback` | int | 14 | [8, 30] | 1 | **OPTIMIZE** | Rolling slope window |
| `weight_rsi` | float | 0.4 | [0.1, 0.6] | 0.05 | **OPTIMIZE** | Divergence component weight |
| `weight_macd` | float | 0.35 | [0.1, 0.6] | 0.05 | **OPTIMIZE** | Divergence component weight |
| `weight_mfi` | float | 0.25 | [0.1, 0.5] | 0.05 | **OPTIMIZE** | Divergence component weight |
| `min_confirming_indicators` | int | 2 | [1, 3] | 1 | **OPTIMIZE** | Gate threshold |
| `min_divergence_magnitude` | float | 0.1 | [0.01, 0.5] | 0.01 | **OPTIMIZE** | Gate threshold |
| `vam_confirm_boost` | float | 0.2 | [0.0, 0.5] | 0.05 | **OPTIMIZE** | Weights non-TV feature (VAM uses Momentum + volume) |
| `vam_contradict_penalty` | float | 0.15 | [0.0, 0.4] | 0.05 | **OPTIMIZE** | Weights non-TV feature |
| `norm_scale` | float | 100.0 | [50.0, 200.0] | 10.0 | **OPTIMIZE** | ATR normalization scaling |
| `residual_weight` | float | 0.15 | [0.0, 0.4] | 0.05 | **OPTIMIZE** | Weights non-TV feature (residual_momentum uses Momentum + RSI) |
| `market_divergence_weight` | float | 0.2 | — | — | **FIXED** | Weights `eng_altcoin_market_momentum` (needs TOTAL3 from TV) |
| `beta_penalty_weight` | float | 0.3 | — | — | **FIXED** | Weights `eng_altcoin_beta` (needs TOTAL2 from TV) |
| `base_conviction` | float | 0.3 | [0.1, 0.5] | 0.05 | **OPTIMIZE** | Conviction scaling |
| `agreement_bonus` | float | 0.35 | [0.1, 0.5] | 0.05 | **OPTIMIZE** | Conviction scaling |
| `magnitude_bonus` | float | 0.35 | [0.1, 0.5] | 0.05 | **OPTIMIZE** | Conviction scaling |
| `divergence_saturation` | float | 2.0 | [0.5, 5.0] | 0.5 | **OPTIMIZE** | Conviction normalization |

**Optimizable: 14 params. Fixed: 2 params.**

### 5.3 How Fixed Params Work in Code

```python
# In each optimizer.py:

FIXED_PARAMS = {
    "breadth_weight": 0.2,
    "btc_dom_weight": 0.3,
}
# (or for DivergenceEdge):
FIXED_PARAMS = {
    "market_divergence_weight": 0.2,
    "beta_penalty_weight": 0.3,
}

def make_objective(...):
    def objective(trial):
        params = {}
        for pname, pdef in schema.items():
            if pname in FIXED_PARAMS:
                params[pname] = FIXED_PARAMS[pname]
            else:
                params[pname] = build_suggest(trial, pname, pdef)
        ...
```

## 6. Feature Pipeline Design

### 6.1 Architecture

```
OHLCV (Binance REST)
  └─ data_fetcher.fetch_historical_ohlcv()
      └─ scoring_feature_pipeline.build_scoring_feature_df()
          ├─ FeatureManager(asset, tf)
          │    ├─ prime(historical_data[:warmup_bars])
          │    └─ process_tick(bar) → {RSI: 55.3, ATR: 120.5, ...}
          │         for each bar
          ├─ EngineeredFeatureManager(asset, tf)
          │    └─ compute(raw_indicators, bar_data, index_data=None)
          │         → {eng_regime_score: -0.3, eng_mean_reversion_z: 1.2, ...}
          └─ Flatten → DataFrame
               columns: [open, high, low, close, volume,
                         RSI, ATR, ADX, MACD_histogram, MFI, Momentum,
                         KAMA_slow, BollingerBands, KeltnerChannel, LinReg,
                         eng_regime_score, eng_mean_reversion_z,
                         eng_squeeze_intensity, eng_volume_adjusted_momentum,
                         eng_atr_normalized_return, eng_residual_momentum,
                         eng_btc_dominance_regime,       # → 0.0 (no TV data)
                         eng_altcoin_market_momentum,     # → 0.0
                         eng_market_cap_breadth,          # → 0.0
                         eng_altcoin_beta]                # → 0.0
```

### 6.2 Indicator Output Flattening Rules

| Indicator | Raw Output | DataFrame Columns |
|-----------|-----------|-------------------|
| RSI | `float` | `RSI` |
| ATR | `float` | `ATR` |
| ADX | `float` | `ADX` |
| MFI | `float` | `MFI` |
| Momentum | `float` | `Momentum` |
| KAMA_slow | `float` | `KAMA_slow` |
| LinReg | `float` or `dict` | `LinReg` (scalar) |
| MACD | `dict {"macd", "signal", "histogram"}` | `MACD_macd`, `MACD_signal`, `MACD_histogram` |
| BollingerBands | `tuple (mid, upper, lower)` | Keep as tuple in features dict (SqueezeIntensity needs it); also flatten to `BollingerBands_middle`, `BollingerBands_upper`, `BollingerBands_lower` |
| KeltnerChannel | `tuple (mid, upper, lower)` | Same as BollingerBands |

**Important**: The engineered features (SqueezeIntensity, MeanReversionZ) consume the raw dict/tuple format via `features.get("BollingerBands")`. The pipeline must pass the un-flattened format to `EngineeredFeatureManager.compute()`, then flatten for the final DataFrame.

### 6.3 Warm-Up Strategy

The indicators are stateful and need warm-up bars before they produce valid outputs:
- RSI(14): ~14 bars
- KAMA(30): ~30 bars
- BB(20): ~20 bars
- ADX(14): ~28 bars (internally computes DI first)
- Engineered features add their own warm-up (e.g. ResidualMomentum: 50 bars)

**Approach**: Use FeatureManager's `prime()` method which handles all indicator warm-up in one call. Then process remaining bars via `process_tick()`.

Since `prime()` takes `list[(open, high, low, close, volume, timestamp)]` tuples:
```python
# Convert DataFrame rows to tuples for prime/process_tick
bar_tuples = list(ohlcv_df[["open","high","low","close","volume","timestamp"]].itertuples(index=False, name=None))
fm.prime(bar_tuples)
# Then process_tick for each bar to get per-bar outputs
```

Wait — `prime()` pre-warms state but doesn't return per-bar outputs. For the feature DataFrame, we need outputs at every bar. The correct approach:

1. Create FeatureManager and prime with all data (this sets internal indicator state)
2. Reset indicators and replay from the beginning, capturing outputs at each bar
3. OR: Don't prime; process each bar sequentially via `process_tick()` and capture outputs

**Recommended**: Process all bars sequentially via `process_tick()`. The first ~50 bars will have NaN/None outputs (indicators not yet warmed up). This is fine — CV will naturally skip them because embargo_bars = 50.

Actually, the cleaner approach:
1. Prime indicators with the full history (this warms them up AND processes)
2. Then we need the intermediate outputs, but `prime()` doesn't save them

So the correct approach is: **Do NOT use prime(). Process each bar via `process_tick()` and capture outputs into a list of dicts.** This is less efficient but gives us per-bar indicator values.

```python
def build_scoring_feature_df(ohlcv_df, asset, timeframe):
    fm = FeatureManager(asset, timeframe)
    efm = EngineeredFeatureManager(asset, timeframe)

    rows = []
    for _, bar in ohlcv_df.iterrows():
        tick = (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.timestamp)
        raw_indicators = fm.process_tick(tick)  # updates state, returns current values
        eng_features = efm.compute(raw_indicators, dict(bar), index_data=None)

        row = {**dict(bar), **flatten_indicators(raw_indicators), **eng_features}
        rows.append(row)

    return pd.DataFrame(rows, index=ohlcv_df.index)
```

**Problem**: `process_tick()` skips un-primed indicators and returns empty dict. We need indicators to be primed first. But `prime()` consumes the data without returning outputs.

**Solution**: Two-pass approach:
1. Pass 1 — `prime(all_bar_tuples)` to warm up all indicators
2. Then we need to replay to get outputs. BUT prime already consumed the data and indicators are now at the latest state.

Looking at the indicator code more carefully: `prime()` calls `ind.prime(mapped_data)` which processes historical data and marks the indicator as primed. Then `process_tick()` calls `ind.update(new_value)` which updates state and returns the value.

So actually: the standard live flow is prime → then update tick by tick. But for optimization we need values at every historical bar.

**Revised solution**: Don't use FeatureManager at all. Create indicators directly, and call their `update()` method for each bar, collecting outputs. But that loses the config-driven indicator selection.

**Simplest correct solution**: Re-instantiate FeatureManager and process ALL bars through `process_tick()`, but first prime it with the first N bars to ensure `is_primed` becomes True. The indicator's `prime()` method processes historical data to warm up state, then subsequent `update()` calls continue from there.

```python
def build_scoring_feature_df(ohlcv_df, asset, timeframe):
    fm = FeatureManager(asset, timeframe)
    efm = EngineeredFeatureManager(asset, timeframe)

    bar_tuples = [
        (r.open, r.high, r.low, r.close, r.volume, r.timestamp)
        for r in ohlcv_df.itertuples(index=False)
    ]

    # Prime indicators so they start producing values
    # Use minimum lookback bars for priming
    warmup = min(100, len(bar_tuples))
    fm.prime(bar_tuples[:warmup])

    # Now process_tick the remaining bars and capture outputs
    rows = []
    # First warmup bars: indicators were primed but we don't have per-bar outputs
    # Fill with NaN
    for i in range(warmup):
        rows.append({})

    for i in range(warmup, len(bar_tuples)):
        tick = bar_tuples[i]
        raw = fm.process_tick(tick)
        bar_dict = {"open": tick[0], "high": tick[1], "low": tick[2],
                     "close": tick[3], "volume": tick[4]}
        eng = efm.compute(raw, bar_dict, index_data=None)
        rows.append({**flatten_indicators(raw), **eng})

    df = pd.DataFrame(rows, index=ohlcv_df.index)
    # Merge OHLCV columns
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = ohlcv_df[col].values
    return df
```

This has a gap: bars 0..warmup-1 have no indicator values (NaN). This is acceptable because CV embargo_bars = 50 will skip the first fold anyway, and we fetch enough data (180+ days = 4320+ 1h bars) that losing 100 bars is negligible.

## 7. Batch Evaluate Fidelity Fix: DivergenceEdgeScorer

### Current Gap

`DivergenceEdgeScorer.batch_evaluate()` currently computes only the ATR-normalized divergence. It skips:
- VAM confirmation boost/penalty (`vam_confirm_boost`, `vam_contradict_penalty`)
- Residual momentum boost (`residual_weight`)
- Market divergence bonus (`market_divergence_weight`) — cross-sectional, will be 0.0 anyway
- Beta dampener (`beta_penalty_weight`) — cross-sectional, will be 0.0 anyway

The first two (VAM, residual) use non-TV engineered features that ARE available in the optimization feature DataFrame. Skipping them means the optimization objective doesn't see the effect of `vam_confirm_boost`, `vam_contradict_penalty`, and `residual_weight` — making those 3 params unoptimizable.

### Required Fix

Extend `batch_evaluate()` to include VAM and residual adjustments. The cross-sectional adjustments can remain skipped (they'll be 0.0 in Phase 1 anyway, and the weight params are FIXED).

```python
# After computing normalized divergence (existing code), add:

# VAM confirmation
vam_col = feature_df.get("eng_volume_adjusted_momentum")
if vam_col is not None:
    vam_same_sign = np.sign(vam_col.values) == np.sign(result.values)
    vam_diff_sign = (np.sign(vam_col.values) != np.sign(result.values)) & (vam_col.values != 0)
    vam_multiplier = np.ones(n)
    vam_multiplier[vam_same_sign & (result.values != 0)] = 1.0 + p["vam_confirm_boost"]
    vam_multiplier[vam_diff_sign & (result.values != 0)] = 1.0 - p["vam_contradict_penalty"]
    result *= vam_multiplier

# Residual momentum boost
res_col = feature_df.get("eng_residual_momentum")
if res_col is not None:
    res_same_sign = np.sign(res_col.values) == np.sign(result.values)
    res_multiplier = np.ones(n)
    res_multiplier[res_same_sign & (result.values != 0)] = 1.0 + p["residual_weight"]
    result *= res_multiplier
```

## 8. Assets × Timeframes

### Phase 1 Strategy: Universal Params

Optimize on a single representative asset/timeframe, then validate cross-asset:

| Stage | Asset | Timeframe | Purpose |
|-------|-------|-----------|---------|
| **Optimization** | BTCUSDT | 1h | Primary training data (most liquid, most data) |
| **Cross-validation** | ETHUSDT | 1h | Out-of-sample robustness check |
| **Secondary** | BTCUSDT | 4h | Timeframe robustness check |

**Data volume**: 180 days × 24 bars/day = 4,320 bars for 1h. Sufficient for 5-fold CV with 50-bar embargo.

**Universal params**: Same optimized params for all assets on a given timeframe. Per-asset specialization deferred to Phase 2 (requires significantly more data and overfitting controls).

### Optimization Config Addition

```yaml
# configs/optimization.yaml — add:
  schedules:
    RegimePullbackScorer:
      cron: "0 4 1 * *"           # monthly 1st 4am UTC
      assets: ["BTCUSDT"]
      timeframes: ["1h"]
      write_back: false           # manual review first
    DivergenceEdgeScorer:
      cron: "0 5 1 * *"           # monthly 1st 5am UTC
      assets: ["BTCUSDT"]
      timeframes: ["1h"]
      write_back: false
```

## 9. Implementation Order

### Step 0: DivergenceEdgeScorer batch_evaluate fix
- **File**: `src/libs/models/divergence_edge/model.py`
- **Change**: Add VAM + residual adjustments to `batch_evaluate()`
- **Test**: Verify `batch_evaluate()` output changes when `vam_confirm_boost > 0` and `eng_volume_adjusted_momentum` column is present
- **Prerequisite for**: Steps 2-4 (optimizer accuracy depends on this)

### Step 1: Shared utilities
1. `src/libs/optim_utils/scoring_feature_pipeline.py` — batch feature computation
2. `src/libs/optim_utils/cv.py` — purged k-fold CV
3. Add `compute_signal_weighted_returns()` to `src/libs/optim_utils/scoring.py`
4. Tests for all three

### Step 2: RegimePullbackScorer optimizer
1. `src/libs/models/regime_pullback/optimization/__init__.py`
2. `src/libs/models/regime_pullback/optimization/optimizer.py`
3. `src/libs/models/regime_pullback/optimization/optimize.py`
4. Tests

### Step 3: DivergenceEdgeScorer optimizer
1. `src/libs/models/divergence_edge/optimization/__init__.py`
2. `src/libs/models/divergence_edge/optimization/optimizer.py`
3. `src/libs/models/divergence_edge/optimization/optimize.py`
4. Tests

### Step 4: Config and integration
1. Update `configs/optimization.yaml`
2. Integration test: full pipeline smoke test (fetch → features → optimize → audit)

## 10. Acceptance Criteria

### Functional
- [ ] `build_scoring_feature_df()` produces a DataFrame with all required columns for both scoring models (RSI, ATR, ADX, MFI, Momentum, KAMA_slow, LinReg, MACD_histogram, eng_regime_score, eng_mean_reversion_z, eng_squeeze_intensity, eng_volume_adjusted_momentum, eng_atr_normalized_return, eng_residual_momentum)
- [ ] `purged_kfold_cv()` produces 4 folds with no temporal overlap and embargo gap between each train/test boundary
- [ ] `compute_signal_weighted_returns()` produces per-bar returns with transaction costs that match manual calculation on a toy example
- [ ] Each model's `optimizer.py` produces an Optuna objective that:
  - Excludes FIXED_PARAMS from the search space
  - Merges FIXED_PARAMS defaults into params before model construction
  - Evaluates across all CV folds
  - Returns `mean(sharpe) - 0.5 * std(sharpe)`
- [ ] Each model's `optimize.py` CLI accepts `--asset`, `--timeframe`, `--n-trials`, `--days`, `--cost-bps`, `--audit`, `--write-back`
- [ ] DivergenceEdgeScorer `batch_evaluate()` now applies VAM and residual adjustments when those columns are present in feature_df
- [ ] Running the full optimization loop for 10 trials on 30 days of data completes without error

### Non-Functional
- [ ] Feature pipeline can process 4,320 bars (180d × 24 1h) in < 60 seconds
- [ ] No look-ahead bias: verify by asserting that feature_df[t] uses only data from bars ≤ t
- [ ] No cross-contamination between CV folds: train and test indices have no overlap, embargo bars are excluded

### Test Requirements
- [ ] `test_scoring_feature_pipeline.py`: build_scoring_feature_df produces expected columns, handles empty OHLCV, handles missing indicators gracefully
- [ ] `test_cv.py`: purged_kfold_cv fold count, no overlap, embargo gap, expanding window property
- [ ] `test_optimizer.py` (per model): objective returns float, fixed params are excluded from trial, 3-trial smoke test completes
- [ ] `test_batch_evaluate_extended.py`: DivergenceEdgeScorer batch_evaluate with/without VAM and residual columns

## 11. Validation Checklist

### Bias Controls
- [x] **Look-ahead bias**: Purged k-fold CV with embargo prevents future data leakage
- [x] **Survivorship bias**: N/A — using raw OHLCV from Binance, not filtered universe
- [x] **Data leakage**: FIXED_PARAMS for TV-dependent features (no TV data in optimization = no false signal)
- [x] **Overfitting controls**: Regularized objective `mean(sharpe) - λ*std(sharpe)` penalizes fold-inconsistent params
- [x] **Transaction costs**: 10 bps default, configurable via `--cost-bps`

### Reproducibility
- [x] Optuna study uses in-memory storage (no DB dependency)
- [x] TPE sampler with fixed seed can be added for reproducibility
- [x] Feature pipeline deterministic given same OHLCV input

### Quant Architecture Checklist
- [x] Point-in-time data correctness: indicators process bars sequentially, no future data access
- [x] Missing data behavior: NaN rows from indicator warm-up are handled (skipped in scoring)
- [x] Backtest-live parity: batch_evaluate() mirrors evaluate() logic (with DivergenceEdge fix)
- [x] Transaction cost modeling: proportional to position change
- [x] Regime sensitivity: addressed by CV fold variance penalty
- [x] Compute efficiency: feature pipeline is O(n × indicators), acceptable for offline optimization

## 12. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| Feature pipeline too slow for large datasets | Medium | Profile and optimize; consider caching feature_df to disk |
| edge_score range varies across models | Medium | `clip(-1, 1)` in `compute_signal_weighted_returns()` prevents unbounded leverage |
| DivergenceEdgeScorer batch_evaluate loop (Python, not vectorized) | Low | Acceptable for offline optimization; vectorize later if needed |
| Cross-sectional features all 0.0 may distort other param values | Low | Fixed params at defaults ensure no cross-interaction; post-Phase 2 re-optimization with TV data will calibrate |
| Optuna convergence with 9-14 params in 200 trials | Medium | TPE handles 10-20 params well; can increase to 500 trials if needed |

## 13. CLI Usage Examples

```bash
# RegimePullbackScorer: 200 trials, 180 days, BTCUSDT 1h
PYTHONPATH=src python -m libs.models.regime_pullback.optimization.optimize \
    --asset BTCUSDT --timeframe 1h --n-trials 200 --days 180 --audit

# DivergenceEdgeScorer: 300 trials (more params), BTCUSDT 1h
PYTHONPATH=src python -m libs.models.divergence_edge.optimization.optimize \
    --asset BTCUSDT --timeframe 1h --n-trials 300 --days 180 --audit

# Cross-asset validation
PYTHONPATH=src python -m libs.models.regime_pullback.optimization.optimize \
    --asset ETHUSDT --timeframe 1h --n-trials 200 --days 180 --audit

# Write back best params
PYTHONPATH=src python -m libs.models.regime_pullback.optimization.optimize \
    --asset BTCUSDT --timeframe 1h --n-trials 200 --days 180 --audit --write-back
```

## 14. Blast Radius

- **Live pipeline**: Zero impact. Optimization is offline-only; no changes to signal_app, strategy_app, or selection_layer execution flows.
- **DivergenceEdgeScorer.batch_evaluate()**: Used in `ParamAuditor._score()`. The fix improves audit accuracy — positive change, no breakage.
- **configs/optimization.yaml**: Additive only (new schedule entries).
- **Existing optimizer code**: Untouched. New scoring model optimizers are independent.

## 15. Open Questions for Coder

1. **FeatureManager prime vs sequential process_tick**: Confirm that calling `process_tick()` on a non-primed FeatureManager returns empty dict (as observed in code). If so, the pipeline must prime first, then re-process bars after warm-up. This wastes ~100 bars of computation but is the simplest correct approach.

2. **MACD column naming**: Verify DivergenceEdgeScorer.batch_evaluate() looks for `MACD_histogram` (not `MACD.histogram` or `MACD["histogram"]`). The current code uses `feature_df.get("MACD_histogram")` — confirm this matches the pipeline's flattening.

3. **LinReg output format**: In single-tick evaluate, DivergenceEdgeScorer handles LinReg as either dict or scalar. In batch, the feature pipeline should normalize to scalar. Verify which format the LinReg indicator actually returns.
