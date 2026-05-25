---
goal: Implement three approved follow-ups from model-strategy layer v1 review — two new models, bb_entry_std/holding_period wiring, and temporal guard
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, strategy, model-layer, follow-up, temporal-guard, trend-following, momentum]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Model-Strategy Follow-ups v1

## 1. Objective

Implement three non-blocking follow-ups identified during the model-strategy layer v1 review:

| # | Follow-up | Priority |
|---|-----------|----------|
| A | `TrendFollowingModel` and `MomentumModel` concrete classes | Medium |
| B | Wire `bb_entry_std` / `holding_period` into `MeanReversionModel.evaluate()` | Low |
| C | Temporal guard in `BaseModel` ABC for look-ahead bias prevention | High |

All three are additive changes within `src/libs/models/` and `configs/models.yaml`. No changes to `signal_app`, `strategy_app` workers, contracts, optimization harness, or indicator code.

---

## 2. Scope Boundaries

### In Scope

- New file `src/libs/models/trend_following.py` — `TrendFollowingModel`.
- New file `src/libs/models/momentum.py` — `MomentumModel`.
- Edit `src/libs/models/mean_reversion.py` — integrate `bb_entry_std` and `holding_period`.
- Edit `src/libs/models/base.py` — add temporal guard to `batch_evaluate` contract.
- Edit `src/libs/models/__init__.py` — import new models for registry auto-registration.
- Edit `configs/models.yaml` — add `TrendFollowing` and `Momentum` entries.
- Edit `configs/features.yaml` — ensure EMA (two periods) and MACD are present in default config.
- New tests in `tests/models/test_models.py` — cover all three follow-ups.

### Explicit Non-Goals

- Modifying `StrategyWorker`, `ModelManager`, `SignalWorker`, or any `apps/` code.
- Modifying `FeatureVector`, `ModelOutput`, `ParamDef`, or any contract in `schemas.py`.
- Modifying existing indicator implementations.
- Adding new indicators.
- Optimization harness changes.
- Backtesting engine changes.
- Order management or portfolio-level logic.

---

## 3. Affected Symbols, Modules, and Execution Flows

| Symbol / Module | Change Type | Blast Radius |
|---|---|---|
| `src/libs/models/base.py` → `BaseModel.batch_evaluate` | Edit (add temporal guard) | All models that subclass `BaseModel`. Currently only `MeanReversionModel`. New models will inherit the guard. |
| `src/libs/models/mean_reversion.py` → `MeanReversionModel.evaluate()` | Edit (use `bb_entry_std`, `holding_period`) | Isolated — only `MeanReversionModel` changes. Downstream consumers (`ModelManager`, `StrategyWorker`) receive same `ModelOutput` contract. |
| `src/libs/models/mean_reversion.py` → `MeanReversionModel.batch_evaluate()` | Edit (use `bb_entry_std`, `holding_period`) | Same as above. Optimization harness calls `batch_evaluate` — output shape (`pd.Series` of directions) unchanged. |
| `src/libs/models/trend_following.py` | New file | Additive. No existing code depends on it. |
| `src/libs/models/momentum.py` | New file | Additive. No existing code depends on it. |
| `configs/models.yaml` | Edit (add entries) | Only affects which models `ModelManager` instantiates at boot. |
| `configs/features.yaml` | Edit (ensure EMA dual-period) | May add a second EMA config if not already present. Additive. |

**Execution flows affected:**
- Optimization flow: `OptunaRunner` → `objective_fn` → `model.batch_evaluate()` — temporal guard will validate DataFrame index monotonicity before calling subclass logic.
- Live inference: `StrategyWorker` → `ModelManager` → `model.evaluate()` — new models become available for live inference once configured.

---

## 4. Follow-up A: `TrendFollowingModel`

### 4.1 Strategy Logic

**Thesis:** Capture sustained directional moves using EMA crossover with optional MACD confirmation.

**Required indicators:** `EMA` (two instances: fast and slow), `MACD`, `ATR`.

**Required feature fields:**
- `EMA_fast` — fast EMA value (e.g., period 9 or 12)
- `EMA_slow` — slow EMA value (e.g., period 21 or 26)
- `MACD.line`, `MACD.signal`, `MACD.histogram`
- `ATR` — for conviction scaling

**Signal logic (`evaluate`):**

```
LONG when:
  1. EMA_fast > EMA_slow (fast crossed above slow)
  2. AND MACD histogram > 0 (optional confirmation, controlled by `require_macd_confirm` param)
  3. Conviction = clip(abs(EMA_fast - EMA_slow) / ATR, 0, 1)

SHORT when:
  1. EMA_fast < EMA_slow
  2. AND MACD histogram < 0 (if confirmation enabled)
  3. Conviction same formula

FLAT otherwise.
```

**Batch logic (`batch_evaluate`):**
Same conditions applied vectorially across DataFrame columns.

### 4.2 Hyperparameters

| Param | Type | Default | Low | High | Step | Purpose |
|---|---|---|---|---|---|---|
| `ema_fast_period` | int | 12 | 5 | 20 | 1 | Fast EMA lookback |
| `ema_slow_period` | int | 26 | 15 | 50 | 1 | Slow EMA lookback |
| `require_macd_confirm` | categorical | True | — | — | — | Whether MACD histogram must agree with EMA crossover |
| `atr_conviction_scale` | float | 1.0 | 0.5 | 3.0 | 0.1 | Divisor for ATR-based conviction normalization |

**Constraint:** `ema_fast_period` must always be less than `ema_slow_period`. The model's `evaluate()` and `batch_evaluate()` must enforce this at construction (`__init__`) and raise `ValueError` if violated.

### 4.3 `ModelMeta` Declaration

```python
meta = ModelMeta(
    name="TrendFollowing",
    required_indicators=["EMA", "MACD", "ATR"],
    required_fields=["EMA_fast", "EMA_slow", "MACD.line", "MACD.signal", "MACD.histogram", "ATR"],
    hyperparameter_schema={
        "ema_fast_period": ParamDef(type="int", default=12, low=5, high=20, step=1),
        "ema_slow_period": ParamDef(type="int", default=26, low=15, high=50, step=1),
        "require_macd_confirm": ParamDef(type="categorical", default=True, choices=[True, False]),
        "atr_conviction_scale": ParamDef(type="float", default=1.0, low=0.5, high=3.0, step=0.1),
    },
    min_history_bars=50,
)
```

### 4.4 Feature Mapping Note

The model requires two separate EMA series (fast and slow). The feature pipeline computes a single `EMA` indicator per config entry. The `FeatureVector.features` dict must contain `EMA_fast` and `EMA_slow` as separate keys.

**How this works today:** `features.yaml` can declare multiple EMA entries with different periods. The `FeatureManager` tags them by period. The model's `evaluate()` should look up features by indicator name and fall back to extracting the fast/slow values from the features dict. The coder should use these conventions:

- `features["EMA_fast"]` or `features["EMA"]` with period matching `ema_fast_period`
- `features["EMA_slow"]` or a second `EMA` entry

**If the feature pipeline does not support dual-EMA tagging**, the model should accept `ema_fast_value` and `ema_slow_value` as direct keys in `FeatureVector.features`, and the `StrategyWorker` / `FeatureManager` mapping is a separate follow-up. For batch mode, expect DataFrame columns `EMA_fast` and `EMA_slow`.

### 4.5 File Location

`src/libs/models/trend_following.py`

---

## 5. Follow-up A (continued): `MomentumModel`

### 5.1 Strategy Logic

**Thesis:** Capture momentum regime by combining RSI directional bias with MACD histogram direction.

**Required indicators:** `RSI`, `MACD`.

**Required feature fields:**
- `RSI.value` (or `RSI` as float)
- `MACD.histogram`
- `MACD.line`

**Signal logic (`evaluate`):**

```
LONG when:
  1. RSI > rsi_long_threshold (momentum is bullish, default 55)
  2. AND MACD histogram > 0 (positive momentum)
  3. AND MACD line > 0 (above zero line, optional via `require_macd_positive` param)
  4. Conviction = clip((RSI - 50) / 50, 0, 1)  — distance from neutral

SHORT when:
  1. RSI < rsi_short_threshold (momentum is bearish, default 45)
  2. AND MACD histogram < 0
  3. AND MACD line < 0 (if `require_macd_positive` enabled)
  4. Conviction = clip((50 - RSI) / 50, 0, 1)

FLAT otherwise.
```

**Design note:** This is distinct from `MeanReversionModel` which uses RSI extremes (oversold/overbought) as reversal signals. `MomentumModel` uses RSI *directional bias* (above/below 50 midline) as continuation signals.

### 5.2 Hyperparameters

| Param | Type | Default | Low | High | Step | Purpose |
|---|---|---|---|---|---|---|
| `rsi_long_threshold` | int | 55 | 50 | 70 | 1 | RSI above this triggers long bias |
| `rsi_short_threshold` | int | 45 | 30 | 50 | 1 | RSI below this triggers short bias |
| `require_macd_positive` | categorical | False | — | — | — | Whether MACD line must be same-sign as direction |
| `histogram_min_abs` | float | 0.0 | 0.0 | 1.0 | 0.01 | Minimum absolute histogram value to trigger (noise filter) |

**Constraint:** `rsi_short_threshold` must be less than `rsi_long_threshold`. Enforce at `__init__`.

### 5.3 `ModelMeta` Declaration

```python
meta = ModelMeta(
    name="Momentum",
    required_indicators=["RSI", "MACD"],
    required_fields=["RSI.value", "MACD.histogram", "MACD.line"],
    hyperparameter_schema={
        "rsi_long_threshold": ParamDef(type="int", default=55, low=50, high=70, step=1),
        "rsi_short_threshold": ParamDef(type="int", default=45, low=30, high=50, step=1),
        "require_macd_positive": ParamDef(type="categorical", default=False, choices=[True, False]),
        "histogram_min_abs": ParamDef(type="float", default=0.0, low=0.0, high=1.0, step=0.01),
    },
    min_history_bars=35,
)
```

### 5.4 File Location

`src/libs/models/momentum.py`

---

## 6. Follow-up B: Wire `bb_entry_std` / `holding_period` into `MeanReversionModel`

### 6.1 Current State

`MeanReversionModel.hyperparameter_schema` declares:
- `bb_entry_std` (float, default 2.0, range 1.0–3.0)
- `holding_period` (int, default 5, range 1–20)

These are exposed to Optuna for search-space construction, but neither `evaluate()` nor `batch_evaluate()` uses them.

### 6.2 `bb_entry_std` — Dynamic Bollinger Band Width

**Current behavior:** `evaluate()` compares `close <= bb_lower` and `close >= bb_upper`, where `bb_lower` and `bb_upper` come directly from the `BollingerBands` indicator (computed with `num_std` from `features.yaml`).

**Problem:** The indicator's `num_std` (e.g., 2.0) is a feature-pipeline parameter. The model's `bb_entry_std` is a model-level hyperparameter. If they differ, the model should apply its own threshold relative to the Bollinger midline.

**Specified behavior:** Recompute the model-level entry bands from the Bollinger midline:

```python
# In evaluate():
bb_mid = (bb_upper + bb_lower) / 2.0
bb_range = (bb_upper - bb_lower) / 2.0  # half-width at indicator's num_std
# Scale to model's bb_entry_std:
# If indicator used num_std=2.0, one unit of std = bb_range / 2.0
std_unit = bb_range / indicator_num_std  # indicator_num_std from features config, default 2.0
model_lower = bb_mid - self.params["bb_entry_std"] * std_unit
model_upper = bb_mid + self.params["bb_entry_std"] * std_unit
```

**Simplification for v1:** Since the model cannot directly query the indicator's `num_std` at evaluation time, use a simpler approach:

```python
# Approximate: treat bb_upper/bb_lower as the 2-std band (the default).
# bb_entry_std controls how far beyond the band price must be for entry.
# ratio = bb_entry_std / 2.0  (assuming indicator default num_std=2.0)
# model_lower = bb_mid - ratio * (bb_mid - bb_lower)
# model_upper = bb_mid + ratio * (bb_upper - bb_mid)
bb_mid = (bb_upper + bb_lower) / 2.0
entry_ratio = self.params["bb_entry_std"] / 2.0  # 2.0 = assumed indicator num_std
model_lower = bb_mid - entry_ratio * (bb_mid - bb_lower)
model_upper = bb_mid + entry_ratio * (bb_upper - bb_mid)
```

Then replace comparisons:
- `close <= bb_lower` → `close <= model_lower`
- `close >= bb_upper` → `close >= model_upper`

Apply the same logic in `batch_evaluate()` using vectorized operations.

**When `bb_entry_std` equals the indicator's `num_std` (both 2.0 by default), behavior is identical to current code.**

### 6.3 `holding_period` — Signal Cooldown

**Specified behavior for `evaluate()` (live tick):**

`holding_period` represents the minimum number of bars a signal should persist before the model can flip direction. This is primarily relevant for backtesting and optimization.

For `evaluate()` (live single-tick): the model is stateless by design — it receives a single `FeatureVector` and returns a `ModelOutput`. **Do not add state to `evaluate()`.** Instead:
- Add `holding_period` to the `ModelOutput.metadata` dict so that downstream consumers (`StrategyWorker`, position manager) can use it for signal persistence logic.
- `metadata["holding_period"] = self.params["holding_period"]`

**Specified behavior for `batch_evaluate()` (backtest/optimization):**

Apply a cooldown mask: after a non-zero signal is emitted on bar `i`, suppress direction changes for the next `holding_period` bars.

```python
# After computing raw directions:
cooldown = 0
last_dir = 0
for i in range(len(directions)):
    if cooldown > 0:
        directions.iloc[i] = last_dir  # hold previous direction
        cooldown -= 1
    elif directions.iloc[i] != 0 and directions.iloc[i] != last_dir:
        last_dir = directions.iloc[i]
        cooldown = self.params["holding_period"] - 1
```

This prevents whipsawing in backtests and makes optimization results reflect realistic holding behavior.

### 6.4 Files Changed

- `src/libs/models/mean_reversion.py` — `evaluate()` and `batch_evaluate()`

---

## 7. Follow-up C: Temporal Guard in `BaseModel` ABC

### 7.1 Problem

`batch_evaluate()` receives a `pd.DataFrame` but has no contract enforcement preventing a future model implementation from:
- Using `shift(-1)` (forward look)
- Applying rolling windows that include future data
- Sorting or reindexing in a way that breaks temporal ordering

### 7.2 Specified Design

Add a **wrapper method** in `BaseModel` that validates temporal ordering before dispatching to the subclass's `batch_evaluate()`. Use the Template Method pattern:

```python
class BaseModel(ABC):

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Validates temporal ordering then delegates to _batch_evaluate_impl."""
        self._validate_temporal_ordering(feature_df)
        result = self._batch_evaluate_impl(feature_df)
        self._validate_result_alignment(feature_df, result)
        return result

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Subclass implementation of batch evaluation."""
        ...

    def _validate_temporal_ordering(self, df: pd.DataFrame) -> None:
        """Raise if DataFrame index is not monotonically non-decreasing."""
        if hasattr(df.index, 'is_monotonic_increasing'):
            if not df.index.is_monotonic_increasing:
                raise ValueError(
                    f"{self.meta.name}: batch_evaluate input index is not "
                    "monotonically increasing — possible temporal ordering violation."
                )

    def _validate_result_alignment(self, df: pd.DataFrame, result: pd.Series) -> None:
        """Raise if result length or index doesn't match input."""
        if len(result) != len(df):
            raise ValueError(
                f"{self.meta.name}: batch_evaluate result length ({len(result)}) "
                f"does not match input length ({len(df)})."
            )
```

### 7.3 Migration — Rename in Subclasses

This is a **breaking change to the internal interface**: existing `batch_evaluate()` overrides in `MeanReversionModel` (and the two new models) must be renamed to `_batch_evaluate_impl()`.

**Affected subclasses:**
- `MeanReversionModel.batch_evaluate()` → `MeanReversionModel._batch_evaluate_impl()`
- `TrendFollowingModel.batch_evaluate()` → `TrendFollowingModel._batch_evaluate_impl()`
- `MomentumModel.batch_evaluate()` → `MomentumModel._batch_evaluate_impl()`

The public API (`model.batch_evaluate(df)`) remains unchanged — callers (`OptunaRunner.objective_fn`, tests) do not need modification.

### 7.4 Why Template Method Over a Decorator

- Template Method is explicit in the ABC contract — subclass authors see `_batch_evaluate_impl` as the method they must implement.
- A decorator on each subclass is opt-in and forgettable.
- The guard runs at the ABC level, so future models cannot accidentally bypass it.

### 7.5 Test Coverage for the Guard

```
test_batch_evaluate_rejects_non_monotonic_index
test_batch_evaluate_rejects_mismatched_result_length
test_batch_evaluate_passes_monotonic_index
```

### 7.6 Files Changed

- `src/libs/models/base.py` — `BaseModel` class
- `src/libs/models/mean_reversion.py` — rename method
- `src/libs/models/trend_following.py` — implement with new method name
- `src/libs/models/momentum.py` — implement with new method name

---

## 8. Configuration Updates

### 8.1 `configs/models.yaml` — Add New Model Entries

```yaml
models:
  assets:
    BTCUSDT:
      timeframes:
        1h:
          MeanReversion:
            enabled: true
            params:
              rsi_oversold: 30
              rsi_overbought: 70
              bb_entry_std: 2.0
              holding_period: 5
          TrendFollowing:
            enabled: true
            params:
              ema_fast_period: 12
              ema_slow_period: 26
              require_macd_confirm: true
              atr_conviction_scale: 1.0
          Momentum:
            enabled: true
            params:
              rsi_long_threshold: 55
              rsi_short_threshold: 45
              require_macd_positive: false
              histogram_min_abs: 0.0
        4h:
          MeanReversion:
            enabled: true
            params:
              rsi_oversold: 25
              rsi_overbought: 75
              bb_entry_std: 2.5
              holding_period: 3
          TrendFollowing:
            enabled: true
            params:
              ema_fast_period: 9
              ema_slow_period: 21
              require_macd_confirm: true
              atr_conviction_scale: 2.0
    ETHUSDT:
      timeframes:
        4h:
          MeanReversion:
            enabled: true
            params:
              rsi_oversold: 25
              rsi_overbought: 75
              bb_entry_std: 2.5
              holding_period: 3
          Momentum:
            enabled: true
            params:
              rsi_long_threshold: 55
              rsi_short_threshold: 45
    default:
      timeframes:
        default:
          MeanReversion:
            enabled: true
            params: {}
```

### 8.2 `configs/features.yaml` — Ensure Dual EMA + MACD + ATR

The default block already has `EMA` (period 20) and `MACD`. Verify that:
1. `ATR` is present in default (add if missing: `ATR: { period: 14 }`).
2. For asset/timeframe combos where `TrendFollowing` is enabled, ensure the feature config can supply two EMA values.

**Note:** The feature pipeline's ability to supply `EMA_fast` and `EMA_slow` as separate keys depends on how `FeatureManager` maps indicator outputs to the `FeatureVector.features` dict. If it only supports one EMA entry per asset/timeframe, the coder should document this limitation and use the model's `ema_fast_period` and `ema_slow_period` params only for Optuna search space — deferring dual-EMA feature mapping to a separate follow-up.

---

## 9. Implementation Order

| Step | Task | Depends On |
|---|---|---|
| 1 | **Temporal guard in `BaseModel`** (Follow-up C) | None — do this first since it changes the subclass interface |
| 2 | **Rename `MeanReversionModel.batch_evaluate` → `_batch_evaluate_impl`** | Step 1 |
| 3 | **Wire `bb_entry_std` / `holding_period` into `MeanReversionModel`** (Follow-up B) | Step 2 |
| 4 | **Implement `TrendFollowingModel`** (Follow-up A) | Step 1 (uses new `_batch_evaluate_impl` interface) |
| 5 | **Implement `MomentumModel`** (Follow-up A) | Step 1 |
| 6 | **Update `__init__.py`** to import new models | Steps 4, 5 |
| 7 | **Update `configs/models.yaml`** | Steps 4, 5 |
| 8 | **Verify `configs/features.yaml`** has ATR in default | Step 4 |
| 9 | **Write tests for all three follow-ups** | Steps 1–7 |
| 10 | **Run full test suite** | Step 9 |

---

## 10. Acceptance Criteria

### Follow-up A — New Models
- [ ] `TrendFollowingModel` registered in `ModelRegistry` and discoverable via `ModelRegistry.get("TrendFollowing")`.
- [ ] `MomentumModel` registered and discoverable via `ModelRegistry.get("Momentum")`.
- [ ] Both models implement `evaluate()` → `ModelOutput` and `_batch_evaluate_impl()` → `pd.Series`.
- [ ] Both models declare `ModelMeta` with correct `required_indicators`, `required_fields`, and `hyperparameter_schema`.
- [ ] `TrendFollowingModel.__init__` raises `ValueError` if `ema_fast_period >= ema_slow_period`.
- [ ] `MomentumModel.__init__` raises `ValueError` if `rsi_short_threshold >= rsi_long_threshold`.
- [ ] Default params produce correct signals for known test vectors.
- [ ] `validate_features()` returns missing indicators correctly.

### Follow-up B — `bb_entry_std` / `holding_period`
- [ ] `MeanReversionModel.evaluate()` uses `bb_entry_std` to compute model-level entry bands relative to the Bollinger midline.
- [ ] `MeanReversionModel.evaluate()` includes `holding_period` in `ModelOutput.metadata`.
- [ ] `MeanReversionModel._batch_evaluate_impl()` uses `bb_entry_std` for entry band computation.
- [ ] `MeanReversionModel._batch_evaluate_impl()` applies `holding_period` cooldown to suppress whipsaw.
- [ ] When `bb_entry_std=2.0` (default, matching indicator `num_std=2.0`), behavior is identical to current code.
- [ ] Existing tests continue to pass (possibly with minor adjustments to account for `holding_period` cooldown in batch mode).

### Follow-up C — Temporal Guard
- [ ] `BaseModel.batch_evaluate()` validates monotonically increasing index before dispatching.
- [ ] `BaseModel.batch_evaluate()` validates result length matches input length.
- [ ] Non-monotonic index raises `ValueError`.
- [ ] Mismatched result length raises `ValueError`.
- [ ] Subclasses implement `_batch_evaluate_impl()` instead of `batch_evaluate()`.
- [ ] Public API (`model.batch_evaluate(df)`) unchanged — no caller modifications needed.

---

## 11. Validation Checklist

- [ ] `PYTHONPATH=. ./.venv/bin/pytest tests/models/ -v` — all model tests pass.
- [ ] `PYTHONPATH=. ./.venv/bin/pytest tests/ -v` — full suite, no regressions.
- [ ] No new cross-app imports (`strategy_app` does not import from `signal_app` or vice versa).
- [ ] No `os.getenv()` or `logging.getLogger()` outside approved patterns.
- [ ] No `shift(-1)`, `iloc[-1]`, or forward-looking operations in any model's `_batch_evaluate_impl()`.
- [ ] `ModelRegistry.list_all()` returns `["MeanReversion", "TrendFollowing", "Momentum"]`.
- [ ] `configs/models.yaml` loads without error and `ModelManager` can instantiate all configured models.
- [ ] Hyperparameter constraints (`ema_fast < ema_slow`, `rsi_short < rsi_long`) are enforced.

---

## 12. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Dual-EMA feature mapping may not work if `FeatureManager` only supports one EMA per asset/timeframe | `TrendFollowingModel` should gracefully degrade: if `EMA_fast`/`EMA_slow` keys are missing, fall back to extracting from a generic `EMA` key, or return direction=0 with metadata explaining the missing features. Document as a known limitation for a future follow-up. |
| `holding_period` cooldown in `batch_evaluate` changes MeanReversion optimization landscapes | This is intentional — the cooldown makes backtests more realistic. Existing optimized params may need re-tuning. Document in commit message. |
| Template Method rename (`batch_evaluate` → `_batch_evaluate_impl`) breaks any external callers | The public API is unchanged. Only internal subclass implementations rename. Test suite validates this. |
| Temporal guard may be too strict for DataFrames with duplicate timestamps | Use `is_monotonic_increasing` (allows duplicates) not `is_monotonic_increasing` with strict inequality. `pd.Index.is_monotonic_increasing` returns True for non-decreasing sequences. |

---

## 13. Data Contracts

No new contracts are required. All models use the existing:
- Input: `FeatureVector` (live) / `pd.DataFrame` (batch)
- Output: `ModelOutput` (live) / `pd.Series` (batch)
- Params: `ParamDef` schema in `ModelMeta.hyperparameter_schema`

The only contract-adjacent change is adding `holding_period` to `MeanReversionModel`'s `ModelOutput.metadata` — this is a new key in the existing `dict[str, Any]` metadata field, not a schema change.

---

*This handoff is complete and actionable. The coder can implement all three follow-ups without additional architectural decisions.*
