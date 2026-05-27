---
goal: Feature Orthogonality Audit + EngineeredFeatureManager + SelectionLayer + ScoringModel base class
stage: architect-to-coder
date_created: 2026-05-27
last_updated: 2026-05-27
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, feature-engineering, selection-layer, scoring-model, alpha-discovery, phase-1]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect-to-Coder Handoff: Feature Orthogonality Audit + Engineered Feature Manager + Selection Layer (Phase 1)

## 1. Objective

Evolve the flipperAgent pipeline from "every non-neutral model output becomes a TradeSignal" to a layered system that:

1. **Audits** current indicator redundancy via a research notebook.
2. **Computes orthogonal engineered features** from raw indicator outputs (volume-adjusted momentum, ATR-normalized returns, residual momentum, regime scores).
3. **Ranks and filters** model outputs through a SelectionLayer before they become TradeSignals.
4. **Introduces a ScoringModel base class** that emits continuous edge scores (coexisting with legacy threshold models).

This is Phase 1 of the "Option C-Plus" hybrid evolutionary architecture approved on 2026-05-27. Legacy models (SqueezeBreakout, MeanReversion, TrendFollowing, Momentum) remain unchanged.

---

## 2. Scope Boundaries

### In Scope
- Research notebook for feature orthogonality audit
- `EngineeredFeatureManager` class in `src/libs/features/engineered/`
- Integration of engineered features into `FeatureVector` via `signal_app`
- `SelectionLayer` class in `src/libs/selection/`
- Integration of SelectionLayer into `StrategyWorker.process_features()`
- `ScoringModel` ABC in `src/libs/models/scoring_base.py`
- `ScoringOutput` contract in `src/libs/contracts/signal.py`
- Config additions to `features.yaml` and new `selection.yaml`
- Unit tests for all new modules

### Out of Scope (Explicit Non-Goals)
- Modifying any existing model logic (SqueezeBreakout, MeanReversion, TrendFollowing, Momentum)
- TradingView data ingestion or cross-sectional features (Phase 2)
- Writing actual scoring model implementations (Phase 2)
- Risk, execution, portfolio layers — untouched
- Optimization/backtest integration for new features — deferred
- Any changes to ingestion pipeline

---

## 3. Affected Symbols, Modules, and Execution Flows

### Files Modified (Minimal Changes Only)

| File | Change |
|------|--------|
| `src/apps/signal_app/signal_worker.py` | Add `EngineeredFeatureManager` call after raw indicators, merge results into `FeatureVector.features` |
| `src/apps/strategy_app/strategy_worker.py` | Insert `SelectionLayer` between `model_manager.evaluate()` and signal publishing |
| `src/libs/contracts/signal.py` | Add `ScoringOutput` model, add `SelectionResult` model |
| `configs/features.yaml` | Add `engineered_features` section |

### New Files

| File | Purpose |
|------|---------|
| `research/feature_orthogonality_audit.ipynb` | Research notebook |
| `src/libs/features/engineered/__init__.py` | Package init |
| `src/libs/features/engineered/base.py` | `EngineeredFeature` ABC |
| `src/libs/features/engineered/registry.py` | `EngineeredFeatureRegistry` |
| `src/libs/features/engineered/manager.py` | `EngineeredFeatureManager` |
| `src/libs/features/engineered/features.py` | First 6 engineered feature implementations |
| `src/libs/selection/__init__.py` | Package init |
| `src/libs/selection/base.py` | `SelectionStrategy` ABC |
| `src/libs/selection/strategies.py` | Concrete strategies (conviction-weighted, overlap-penalized, top-k) |
| `src/libs/selection/selection_layer.py` | `SelectionLayer` orchestrator |
| `src/libs/models/scoring_base.py` | `ScoringModel` ABC |
| `configs/selection.yaml` | Selection layer config |
| `tests/test_engineered_features.py` | Unit tests |
| `tests/test_selection_layer.py` | Unit tests |
| `tests/test_scoring_model.py` | Unit tests |

### Unchanged Files (Do NOT Modify)

- `src/libs/features/indicators/` — all existing indicator math
- `src/libs/features/indicators/base.py` — Indicator ABC
- `src/libs/features/indicators/registry.py` — IndicatorRegistry
- `src/libs/models/base.py` — BaseModel ABC
- `src/libs/models/registry.py` — ModelRegistry
- `src/libs/models/squeeze_breakout/` — entire directory
- `src/libs/models/mean_reversion/` — entire directory
- `src/libs/models/trend_following/` — entire directory
- `src/libs/models/momentum/` — entire directory
- `src/libs/models/feature_extractors.py` — shared extractors
- `src/apps/signal_app/feature_manager.py` — existing FeatureManager
- `src/apps/strategy_app/model_manager.py` — ModelManager
- `src/libs/risk/` — entire directory
- `src/libs/execution/` — entire directory
- `src/libs/portfolio/` — entire directory
- `src/apps/signal_app/main.py` — entry point
- `src/apps/strategy_app/main.py` — entry point
- `configs/models.yaml` — model configurations
- `configs/base.yaml`, `configs/risk.yaml`, `configs/execution.yaml`, `configs/portfolio.yaml`

### Execution Flow (Before vs After)

**Before:**
```
SignalWorker.process_message()
  → FeatureManager.process_tick(data) → Dict[str, Any]  (raw indicators)
  → FeatureVector(features=raw_indicators, bar_data=...)
  → publish to features:{asset}:{tf}

StrategyWorker.process_features()
  → ModelManager.evaluate(FeatureVector) → list[ModelOutput]
  → for each non-neutral output → TradeSignal → publish to signals:{asset}:{tf}
```

**After:**
```
SignalWorker.process_message()
  → FeatureManager.process_tick(data) → Dict[str, Any]  (raw indicators)
  → EngineeredFeatureManager.compute(raw_indicators, bar_data) → Dict[str, float]  ← NEW
  → FeatureVector(features={**raw, **engineered}, bar_data=...)
  → publish to features:{asset}:{tf}

StrategyWorker.process_features()
  → ModelManager.evaluate(FeatureVector) → list[ModelOutput]
  → SelectionLayer.select(outputs, FeatureVector) → list[SelectionResult]  ← NEW
  → for each selected result → TradeSignal → publish to signals:{asset}:{tf}
```

---

## 4. Feature Orthogonality Audit — Notebook Spec

### File: `research/feature_orthogonality_audit.ipynb`

### Purpose
Compute rolling correlation matrices across all current indicator outputs to identify redundancy groups before building engineered features.

### Method

1. **Data source**: Load last 2000 bars from TimescaleDB for each deployed (asset, timeframe) pair:
   - BTC/1h, XRP/1h, SOL/1h, BNB/30m, DOGE/4h
   - Also BTC/4h, ETH/4h for cross-validation

2. **Indicator computation**: Instantiate all 16 configured indicators via `FeatureManager` in batch mode and collect their scalar outputs into a DataFrame. For multi-output indicators (MACD → line, signal, histogram; BollingerBands → upper, middle, lower, bandwidth; KeltnerChannel → upper, middle, lower), flatten each sub-field to a separate column.

3. **Correlation method**: Spearman rank correlation (handles non-linear monotonic relationships better than Pearson for indicator data).

4. **Rolling window**: 100-bar rolling Spearman correlation to detect temporal instability. Also compute the full-sample static correlation.

5. **Redundancy thresholds**:
   - `|ρ| > 0.85` → **redundant** — candidates for removal or combining into one composite
   - `0.60 < |ρ| ≤ 0.85` → **correlated** — may benefit from orthogonalization (residual extraction)
   - `|ρ| ≤ 0.60` → **orthogonal** — keep as independent

6. **Expected output**:
   - Full-sample Spearman correlation heatmap (seaborn/plotly)
   - Dendogram of hierarchical clustering (Ward linkage) to visualize feature groups
   - Table of all pairwise correlations > 0.60 with (indicator_A, indicator_B, ρ_mean, ρ_std, ρ_min, ρ_max)
   - Recommended orthogonal feature groups (5 buckets):
     - **Price-Structure**: KAMA_fast, KAMA_slow, EMA_fast, EMA_slow, BollingerBands, KeltnerChannel
     - **Momentum**: RSI, MACD, Momentum, LinReg, CCI
     - **Volume**: MFI, ADLine
     - **Volatility**: ATR, BB_bandwidth, KC_width
     - **Trend-Strength**: ADX

7. **Validation**: Confirm that cross-asset correlation patterns are stable (i.e., if RSI and CCI are redundant on BTC/1h, they should also be redundant on SOL/1h). Report exceptions.

### Notebook Structure (Cells)
1. Imports + DB connection setup
2. Fetch historical bars for all (asset, tf) pairs
3. Compute indicator outputs via `FeatureManager.prime()` + `process_tick()` loop
4. Flatten multi-output indicators into DataFrame columns
5. Full-sample Spearman correlation matrix + heatmap
6. Rolling 100-bar correlation stability analysis
7. Hierarchical clustering dendogram
8. Redundancy pairs table (ρ > 0.60)
9. Recommended feature groupings + summary

---

## 5. EngineeredFeatureManager Design

### 5.1. Location

```
src/libs/features/engineered/
    __init__.py
    base.py              # EngineeredFeature ABC
    registry.py          # EngineeredFeatureRegistry
    manager.py           # EngineeredFeatureManager
    features.py          # Concrete feature implementations
```

### 5.2. EngineeredFeature ABC

```python
# src/libs/features/engineered/base.py
from abc import ABC, abstractmethod
from typing import Any


class EngineeredFeature(ABC):
    """Base class for composite features computed from raw indicator outputs."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique feature name used as the key in FeatureVector.features."""
        ...

    @property
    @abstractmethod
    def required_indicators(self) -> list[str]:
        """List of raw indicator keys this feature needs from FeatureVector.features."""
        ...

    @property
    @abstractmethod
    def required_bar_fields(self) -> list[str]:
        """List of bar_data fields needed (e.g. ['close', 'volume'])."""
        ...

    @abstractmethod
    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
    ) -> float | None:
        """Compute the engineered feature value.
        
        Args:
            features: Raw indicator outputs from FeatureManager
            bar_data: OHLCV bar data
            state: Mutable per-feature state dict for rolling computations.
                   The manager maintains one state dict per feature instance.
                   
        Returns:
            float value, or None if insufficient data.
        """
        ...
```

**Design rationale**:
- `state` dict allows O(1) rolling computations (e.g. keep a deque of recent values) without the feature needing its own instance variables, keeping features stateless-friendly for batch mode.
- `required_indicators` + `required_bar_fields` enable boot-time validation (same pattern as `ModelMeta.required_indicators`).

### 5.3. EngineeredFeatureRegistry

```python
# src/libs/features/engineered/registry.py
from typing import Type
from libs.features.engineered.base import EngineeredFeature


class EngineeredFeatureRegistry:
    _registry: dict[str, Type[EngineeredFeature]] = {}

    @classmethod
    def register(cls, name: str):
        def wrapper(feature_class: Type[EngineeredFeature]):
            cls._registry[name] = feature_class
            return feature_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[EngineeredFeature]:
        if name not in cls._registry:
            raise KeyError(f"Engineered feature '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
```

### 5.4. First 6 Engineered Features

All features are registered via `@EngineeredFeatureRegistry.register("name")`.

#### Feature 1: `volume_adjusted_momentum`

**Formula**: $\text{VAM} = \text{Momentum} \times \frac{V_t}{\text{SMA}(V, 20)}$

Momentum weighted by relative volume. High-volume momentum breakouts are stronger signals.

**Required indicators**: `Momentum`  
**Required bar fields**: `volume`  
**State**: Rolling deque of last 20 volume values for SMA computation.

```python
# Pseudocode
vol_ratio = current_volume / mean(state["vol_window"])
vam = momentum_value * vol_ratio
```

#### Feature 2: `atr_normalized_return`

**Formula**: $\text{ANR}_t = \frac{C_t - C_{t-1}}{\text{ATR}_t}$

Bar-to-bar return scaled by current ATR. Standardizes return magnitude across volatility regimes.

**Required indicators**: `ATR`  
**Required bar fields**: `close`  
**State**: `prev_close` (single float).

```python
if state.get("prev_close") is not None:
    raw_return = close - state["prev_close"]
    anr = raw_return / atr if atr > 0 else 0.0
state["prev_close"] = close
```

#### Feature 3: `residual_momentum`

**Formula**: $\text{RM}_t = \text{Momentum}_t - \beta \times \text{RSI\_normalized}_t$

Momentum component unexplained by RSI. Captures momentum orthogonal to mean-reversion signals.

**Required indicators**: `Momentum`, `RSI`  
**Required bar fields**: none  
**State**: Rolling deque of (momentum, rsi_normalized) pairs for OLS β estimation (last 50 bars).

```python
rsi_norm = (rsi - 50) / 50  # center and scale RSI to [-1, 1]
# β estimated from rolling OLS of momentum ~ rsi_norm
residual = momentum - beta * rsi_norm
```

**Implementation note**: Use Welford-style online OLS (running sums of x, y, x², xy) to keep computation O(1) per tick. Recompute β from accumulators each tick.

#### Feature 4: `squeeze_intensity`

**Formula**: $\text{SI}_t = \frac{\text{BB\_bandwidth}_t}{\text{KC\_width}_t}$

Ratio of Bollinger Band width to Keltner Channel width. Values < 1.0 indicate a squeeze (BB inside KC). Lower values = tighter squeeze = more explosive breakout expected.

**Required indicators**: `BollingerBands`, `KeltnerChannel`  
**Required bar fields**: none  
**State**: none (pure function of current indicator values).

```python
bb_bw = bb["upper"] - bb["lower"]
kc_w = kc["upper"] - kc["lower"]
si = bb_bw / kc_w if kc_w > 0 else 1.0
```

#### Feature 5: `regime_score`

**Formula**: $\text{RS}_t = \text{tanh}\left(\frac{\text{ADX}_t - 25}{10}\right)$

Continuous regime indicator. Positive values → trending, negative → ranging. The tanh squashing keeps the output bounded in (-1, 1) with center at ADX=25.

**Required indicators**: `ADX`  
**Required bar fields**: none  
**State**: none (pure function).

```python
import math
regime = math.tanh((adx - 25) / 10)
```

#### Feature 6: `mean_reversion_z`

**Formula**: $z_t = \frac{C_t - \text{KAMA\_slow}_t}{\text{ATR}_t}$

Z-score of price deviation from slow adaptive moving average, volatility-normalized. Large |z| indicates price stretched from equilibrium.

**Required indicators**: `KAMA_slow`, `ATR`  
**Required bar fields**: `close`  
**State**: none (pure function).

```python
z = (close - kama_slow) / atr if atr > 0 else 0.0
```

### 5.5. EngineeredFeatureManager

```python
# src/libs/features/engineered/manager.py
from typing import Any
from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent
from libs.features.engineered.base import EngineeredFeature
from libs.features.engineered.registry import EngineeredFeatureRegistry

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


class EngineeredFeatureManager:
    """Computes engineered features from raw indicator outputs."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self._features: list[EngineeredFeature] = []
        self._state: dict[str, dict[str, Any]] = {}  # per-feature state
        self._initialize()

    def _initialize(self) -> None:
        """Load engineered features from config."""
        config_mgr = ConfigManager()
        config_mgr.register_file(CONFIG_FILE_FEATURES)
        eng_config = config_mgr.get("engineered_features", {})

        # Same fallback chain as FeatureManager:
        # asset/tf → asset/default → default/tf → default/default
        assets_config = eng_config.get("assets", {})
        asset_node = assets_config.get(self.asset, assets_config.get("default", {}))
        tf_node = asset_node.get("timeframes", {}).get(
            self.timeframe, asset_node.get("timeframes", {}).get("default", {})
        )

        for feat_name, feat_params in tf_node.items():
            if isinstance(feat_params, dict) and not feat_params.get("enabled", True):
                continue
            try:
                feat_cls = EngineeredFeatureRegistry.get(feat_name)
                self._features.append(feat_cls())
                self._state[feat_name] = {}
                logger.info(f"Loaded engineered feature '{feat_name}' for {self.asset}/{self.timeframe}")
            except KeyError:
                logger.warning(f"Engineered feature '{feat_name}' not found in registry, skipping.")

    def validate_inputs(self, available_indicators: set[str], available_bar_fields: set[str]) -> list[str]:
        """Return list of missing dependencies."""
        missing = []
        for feat in self._features:
            for ind in feat.required_indicators:
                if ind not in available_indicators:
                    missing.append(f"{feat.name} requires indicator '{ind}'")
            for bf in feat.required_bar_fields:
                if bf not in available_bar_fields:
                    missing.append(f"{feat.name} requires bar field '{bf}'")
        return missing

    def compute(self, features: dict[str, Any], bar_data: dict[str, float]) -> dict[str, float]:
        """Compute all configured engineered features.
        
        Args:
            features: Raw indicator outputs (from FeatureManager.process_tick)
            bar_data: OHLCV data
            
        Returns:
            Dict mapping engineered feature name → float value.
            Keys are prefixed with 'eng_' to distinguish from raw indicators.
        """
        results: dict[str, float] = {}
        for feat in self._features:
            try:
                value = feat.compute(features, bar_data, self._state[feat.name])
                if value is not None:
                    results[f"eng_{feat.name}"] = value
            except Exception as e:
                logger.error(f"Engineered feature '{feat.name}' failed: {e}", exc_info=True)
        return results
```

**Key design decisions**:
- Engineered feature keys are prefixed with `eng_` to prevent collision with raw indicator keys in the shared `FeatureVector.features` dict.
- State is managed by the manager (not the feature) to keep features easy to test in isolation.
- Same config fallback chain as FeatureManager for consistency.
- `validate_inputs()` can be called at boot alongside `ModelManager.validate_feature_coverage()`.

### 5.6. Integration with SignalWorker

**Change to `src/apps/signal_app/signal_worker.py`** — approximately 10 lines added:

```python
# In __init__:
from libs.features.engineered.manager import EngineeredFeatureManager
# ...
self.engineered_manager = EngineeredFeatureManager(asset, timeframe)

# In process_message(), after FeatureManager.process_tick():
results = self.feature_manager.process_tick(data_tuple)

# NEW: compute engineered features
engineered = self.engineered_manager.compute(results, {
    "open": open_, "high": high, "low": low,
    "close": close, "volume": volume,
})
results.update(engineered)  # merge into features dict

# FeatureVector is constructed as before — engineered features are now inside features=results
```

### 5.7. Config Format — `features.yaml` Addition

Add a new top-level section `engineered_features` in `configs/features.yaml`:

```yaml
engineered_features:
  assets:
    default:
      timeframes:
        default:
          volume_adjusted_momentum:
            enabled: true
          atr_normalized_return:
            enabled: true
          residual_momentum:
            enabled: true
            ols_window: 50
          squeeze_intensity:
            enabled: true
          regime_score:
            enabled: true
            adx_center: 25
            adx_scale: 10
          mean_reversion_z:
            enabled: true
```

This is intentionally separate from the `features:` block so it doesn't interfere with the existing FeatureManager config resolution. Per-asset overrides follow the same fallback chain.

### 5.8. FeatureVector — No Contract Change

`FeatureVector.features` is already `dict[str, Any]`. Engineered features are merged into this dict with `eng_` prefix. No schema change needed. Downstream models that don't know about engineered features simply ignore the `eng_*` keys.

---

## 6. SelectionLayer Design

### 6.1. Location

```
src/libs/selection/
    __init__.py
    base.py              # SelectionStrategy ABC
    strategies.py        # Concrete strategies
    selection_layer.py   # SelectionLayer orchestrator
```

### 6.2. New Contracts

Add to `src/libs/contracts/signal.py`:

```python
class ScoringOutput(BaseModel):
    """Returned by ScoringModel.evaluate() — continuous edge score."""
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    edge_score: float = Field(..., description="Continuous edge estimate, unbounded")
    conviction: float = Field(default=1.0, ge=0.0, le=1.0, description="Model self-confidence")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectionCandidate(BaseModel):
    """Unified candidate for the selection layer.
    
    Normalizes both ModelOutput (threshold models) and ScoringOutput (scoring models)
    into a common representation.
    """
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    direction: int  # 1, -1, 0
    edge_score: float  # normalized continuous score
    conviction: float
    source_type: Literal["threshold", "scoring"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectionResult(BaseModel):
    """Output of the SelectionLayer — a ranked, filtered candidate."""
    candidate: SelectionCandidate
    rank: int
    selection_score: float = Field(..., description="Final composite selection score")
    penalties: dict[str, float] = Field(default_factory=dict, description="Applied penalties breakdown")
```

### 6.3. SelectionStrategy ABC

```python
# src/libs/selection/base.py
from abc import ABC, abstractmethod
from libs.contracts.signal import SelectionCandidate, SelectionResult, FeatureVector


class SelectionStrategy(ABC):
    """Base class for signal selection/filtering strategies."""

    @abstractmethod
    def select(
        self,
        candidates: list[SelectionCandidate],
        feature_vec: FeatureVector,
        config: dict,
    ) -> list[SelectionResult]:
        """Rank and filter candidates.
        
        Args:
            candidates: Normalized model outputs
            feature_vec: Current feature vector (for feature-aware filtering)
            config: Strategy-specific parameters
            
        Returns:
            Ordered list of SelectionResults (best first), possibly shorter than input.
        """
        ...
```

### 6.4. Concrete Strategies

#### `ConvictionWeightedStrategy`
Ranks by `edge_score * conviction`. No filtering.

```python
score = candidate.edge_score * candidate.conviction
# Sort descending, assign ranks
```

#### `OverlapPenalizedStrategy`
Penalizes candidates that are correlated with higher-ranked candidates from the same asset.

```python
for each candidate (sorted by base score descending):
    penalty = 0.0
    for already_selected in selected:
        if candidate.asset == already_selected.asset and candidate.direction == already_selected.direction:
            penalty += config.get("same_direction_penalty", 0.3)
    adjusted_score = base_score * (1.0 - min(penalty, config.get("max_penalty", 0.8)))
```

This discourages multiple models firing the same direction on the same asset from all becoming signals.

#### `TopKStrategy`
Wraps another strategy and truncates to top-K results.

```python
inner_results = inner_strategy.select(candidates, feature_vec, config)
return inner_results[:config.get("top_k", 3)]
```

### 6.5. SelectionLayer Orchestrator

```python
# src/libs/selection/selection_layer.py
class SelectionLayer:
    """Normalizes model outputs and applies selection strategies."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self._strategy: SelectionStrategy = ...  # loaded from config
        self._config: dict = ...  # loaded from selection.yaml

    def normalize_model_output(self, output: ModelOutput) -> SelectionCandidate:
        """Convert threshold-model ModelOutput to SelectionCandidate.
        
        Normalization: edge_score = direction * conviction
        This maps direction=1,conviction=0.8 → edge_score=0.8
        and direction=-1,conviction=0.6 → edge_score=-0.6
        """
        return SelectionCandidate(
            model_name=output.model_name,
            asset=output.asset,
            timeframe=output.timeframe,
            timestamp=output.timestamp,
            direction=output.direction,
            edge_score=float(output.direction) * output.conviction,
            conviction=output.conviction,
            source_type="threshold",
            metadata=output.metadata,
        )

    def normalize_scoring_output(self, output: ScoringOutput) -> SelectionCandidate:
        """Convert ScoringOutput to SelectionCandidate.
        
        Direction is derived from sign of edge_score.
        """
        direction = 1 if output.edge_score > 0 else (-1 if output.edge_score < 0 else 0)
        return SelectionCandidate(
            model_name=output.model_name,
            asset=output.asset,
            timeframe=output.timeframe,
            timestamp=output.timestamp,
            direction=direction,
            edge_score=output.edge_score,
            conviction=output.conviction,
            source_type="scoring",
            metadata=output.metadata,
        )

    def select(
        self,
        model_outputs: list[ModelOutput],
        scoring_outputs: list[ScoringOutput] | None,
        feature_vec: FeatureVector,
    ) -> list[SelectionResult]:
        """Normalize all outputs and run selection strategy."""
        candidates: list[SelectionCandidate] = []

        for mo in model_outputs:
            if mo.direction != 0:  # preserve existing behavior: skip neutral
                candidates.append(self.normalize_model_output(mo))

        if scoring_outputs:
            for so in scoring_outputs:
                if abs(so.edge_score) > self._config.get("min_edge_threshold", 0.0):
                    candidates.append(self.normalize_scoring_output(so))

        if not candidates:
            return []

        return self._strategy.select(candidates, feature_vec, self._config)
```

### 6.6. Integration with StrategyWorker

**Change to `src/apps/strategy_app/strategy_worker.py`** — replace the signal publishing loop:

```python
# In __init__:
from libs.selection.selection_layer import SelectionLayer
# ...
self.selection_layer = SelectionLayer(asset, timeframe)

# In process_features(), replace the existing loop:
async def process_features(self, payload: dict) -> None:
    # ... (existing deserialization unchanged) ...
    feature_vec = valkey_decode(payload, FeatureVector)
    outputs = self.model_manager.evaluate(feature_vec)

    # NEW: run selection layer (no scoring outputs in Phase 1)
    selected = self.selection_layer.select(
        model_outputs=outputs,
        scoring_outputs=None,  # Phase 2 will populate this
        feature_vec=feature_vec,
    )

    for result in selected:
        candidate = result.candidate
        signal = TradeSignal(
            asset=candidate.asset,
            timeframe=candidate.timeframe,
            timestamp=candidate.timestamp,
            direction=candidate.direction,
            conviction=candidate.conviction,
            price=feature_vec.bar_data.get("close", 0.0),
            idempotency_key=self._make_idempotency_key(
                candidate.model_name, candidate.asset,
                candidate.timeframe, candidate.timestamp,
            ),
            model_name=candidate.model_name,
            metadata={
                **candidate.metadata,
                "selection_rank": result.rank,
                "selection_score": result.selection_score,
                "selection_penalties": result.penalties,
            },
        )
        if self.redis_client:
            await self.redis_client.xadd(
                self.signal_stream_key, valkey_encode(signal),
                maxlen=5000, approximate=True,
            )
```

### 6.7. Config Format — `configs/selection.yaml`

```yaml
selection:
  assets:
    default:
      timeframes:
        default:
          strategy: overlap_penalized_top_k   # strategy name
          top_k: 3                             # max signals per evaluation cycle
          min_edge_threshold: 0.0              # minimum |edge_score| for scoring models
          same_direction_penalty: 0.3          # penalty for same-asset same-direction overlap
          max_penalty: 0.8                     # cap on cumulative overlap penalty
    BTCUSDT:
      timeframes:
        1h:
          strategy: overlap_penalized_top_k
          top_k: 2                             # BTC 1h has 4 models — limit harder
```

Same fallback chain as all other configs. Add `CONFIG_FILE_SELECTION = "selection"` to `libs/common/constants.py`.

---

## 7. ScoringModel Base Class Design

### 7.1. Location

`src/libs/models/scoring_base.py`

### 7.2. Interface

```python
# src/libs/models/scoring_base.py
from __future__ import annotations
from abc import abstractmethod
from typing import Any
import pandas as pd
from libs.contracts.schemas import FeatureVector, ScoringOutput, ParamDef
from libs.models.base import ModelMeta


class ScoringModel:
    """Base class for models that emit continuous edge scores.
    
    Unlike BaseModel which returns direction ∈ {-1, 0, 1} + conviction,
    ScoringModel returns a continuous edge_score that the SelectionLayer
    normalizes alongside threshold-model outputs.
    
    ScoringModel instances are registered in the same ModelRegistry as
    BaseModel subclasses, but the ModelManager dispatches to evaluate()
    which returns ScoringOutput instead of ModelOutput.
    """

    meta: ModelMeta

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = {**self._defaults(), **params}

    def _defaults(self) -> dict[str, Any]:
        return {k: v.default for k, v in self.meta.hyperparameter_schema.items()}

    def validate_features(self, available: set[str]) -> list[str]:
        return [ind for ind in self.meta.required_indicators if ind not in available]

    def validate_required_fields(self, available: set[str]) -> list[str]:
        missing: list[str] = []
        for f in self.meta.required_fields:
            prefix = f.split(".")[0] if "." in f else f
            if prefix not in available:
                missing.append(f)
        return missing

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        """Return a continuous edge score for the current bar."""
        ...

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Batch edge scores for backtesting. Returns float Series."""
        ...

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        ...
```

### 7.3. How It Differs from BaseModel

| Aspect | BaseModel | ScoringModel |
|--------|-----------|--------------|
| Output contract | `ModelOutput` (direction ±1/0, conviction 0-1) | `ScoringOutput` (continuous edge_score, conviction) |
| Direction | Explicit in output | Derived from sign of edge_score |
| Neutral handling | Returns `direction=0` | Returns `edge_score≈0` |
| SelectionLayer normalization | `edge_score = direction * conviction` | `edge_score` used directly |
| Registration | `@ModelRegistry.register("Name")` | Same registry |

### 7.4. ModelManager Adaptation (Phase 2 — documented here for design completeness)

In Phase 2, `ModelManager.evaluate()` will be updated to return `tuple[list[ModelOutput], list[ScoringOutput]]` by dispatching based on `isinstance(model, ScoringModel)`. **In Phase 1, no changes to ModelManager** — the SelectionLayer accepts `scoring_outputs=None`.

---

## 8. Implementation Order

### Phase 1A: Research Notebook (no production code)
1. Create `research/feature_orthogonality_audit.ipynb`
2. Run audit, document findings
3. **Gate**: Review orthogonality results before proceeding

### Phase 1B: EngineeredFeatureManager
1. Create `src/libs/features/engineered/base.py` — ABC
2. Create `src/libs/features/engineered/registry.py` — registry
3. Create `src/libs/features/engineered/features.py` — 6 features
4. Create `src/libs/features/engineered/manager.py` — manager
5. Add `engineered_features` section to `configs/features.yaml`
6. Write `tests/test_engineered_features.py`
   - Test each feature in isolation with known inputs
   - Test state accumulation over multiple ticks
   - Test manager config loading with fallback chain
   - Test `validate_inputs()` catches missing indicators
7. **Gate**: All engineered feature tests pass

### Phase 1C: SignalWorker Integration
1. Modify `src/apps/signal_app/signal_worker.py` — add ~10 lines
2. Verify existing signal_worker tests still pass
3. Add integration test: process_message produces FeatureVector with `eng_*` keys
4. **Gate**: All existing tests pass + new integration test

### Phase 1D: Contracts + ScoringModel ABC
1. Add `ScoringOutput`, `SelectionCandidate`, `SelectionResult` to `src/libs/contracts/signal.py`
2. Create `src/libs/models/scoring_base.py` — ScoringModel ABC
3. Write `tests/test_scoring_model.py` — contract serialization, ABC compliance
4. **Gate**: Contract tests pass, no import errors

### Phase 1E: SelectionLayer
1. Create `src/libs/selection/base.py` — SelectionStrategy ABC
2. Create `src/libs/selection/strategies.py` — 3 strategies
3. Create `src/libs/selection/selection_layer.py` — orchestrator
4. Create `configs/selection.yaml`
5. Add `CONFIG_FILE_SELECTION` to `libs/common/constants.py`
6. Write `tests/test_selection_layer.py`:
   - Test normalization of ModelOutput → SelectionCandidate
   - Test normalization of ScoringOutput → SelectionCandidate
   - Test ConvictionWeightedStrategy ranking
   - Test OverlapPenalizedStrategy penalty application
   - Test TopKStrategy truncation
   - Test with mixed threshold + scoring candidates
   - Test empty candidates → empty results
   - Test config fallback chain
7. **Gate**: All selection tests pass

### Phase 1F: StrategyWorker Integration
1. Modify `src/apps/strategy_app/strategy_worker.py` — replace signal publishing loop
2. Verify all existing strategy_worker tests pass
3. Add integration test: evaluate → select → publish pipeline
4. Verify selection metadata appears in TradeSignal.metadata
5. **Gate**: Full test suite passes, no regression

---

## 9. Acceptance Criteria

1. **Orthogonality notebook** produces correlation heatmap, dendogram, and redundancy table for at least 3 (asset, timeframe) pairs.
2. **EngineeredFeatureManager** computes all 6 features from raw indicator outputs with O(1) per-tick cost.
3. **FeatureVector** published by SignalWorker includes `eng_*` prefixed keys alongside raw indicator keys.
4. **SelectionLayer** reduces model outputs to ranked, filtered `SelectionResult` list with audit trail (penalties dict).
5. **ScoringModel** ABC compiles, is importable, and can be subclassed (even though no concrete implementations exist in Phase 1).
6. **Existing test suite** passes with zero regression.
7. **No changes** to existing model logic, indicator math, risk, execution, or portfolio modules.
8. **Config** follows the established fallback chain pattern.

---

## 10. Validation Checklist

- [ ] All existing tests pass after each phase gate
- [ ] Engineered features produce deterministic outputs for fixed inputs
- [ ] Engineered feature state is correctly maintained across ticks
- [ ] `eng_*` prefix prevents key collisions in FeatureVector.features
- [ ] SelectionLayer handles empty model outputs gracefully
- [ ] SelectionLayer handles mixed threshold + scoring outputs
- [ ] Overlap penalty correctly penalizes same-asset same-direction duplicates
- [ ] TopK truncation respects configured limit
- [ ] Selection metadata (rank, score, penalties) propagates to TradeSignal.metadata
- [ ] Config fallback chain works for engineered_features and selection configs
- [ ] No import cycles introduced between new modules
- [ ] ScoringOutput round-trips through valkey_encode/valkey_decode

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Engineered features with stale state after reconnect | Incorrect feature values | EngineeredFeatureManager state is reset on prime; document that re-prime also resets engineered state |
| Selection layer too aggressive (top-k=1) drops valid signals | Missed trades | Default top_k=3, configurable per asset/tf; log dropped candidates at DEBUG level |
| `eng_*` prefix collision with future indicator names | Key overwrite | Convention: raw indicators never start with `eng_`; validate at boot |
| Rolling OLS for residual_momentum has cold-start | NaN for first 50 bars | Feature returns `None` until window is full; manager skips None values |
| ScoringModel and BaseModel in same registry may confuse ModelManager dispatch | Wrong output type | Phase 1: no scoring models registered; Phase 2: ModelManager checks `isinstance` before dispatch |

---

## 12. Architecture Tradeoffs and Rejected Options

### Option A: Engineered features inside existing FeatureManager
**Rejected** because FeatureManager's `_initialize_indicators()` expects `Indicator` ABC instances with `update()/prime()/batch()`. Engineered features have a different interface (they consume indicator outputs, not raw OHLCV). Mixing them would require modifying the Indicator ABC or adding special-case dispatch in FeatureManager — both violate the single-responsibility principle.

### Option B: SelectionLayer inside ModelManager
**Rejected** because ModelManager is already responsible for model lifecycle, config loading, and feature validation. Selection is a cross-model concern that needs access to the full list of outputs. Keeping it separate preserves ModelManager's single purpose and makes the selection strategy independently testable and configurable.

### Option C: ScoringModel inherits from BaseModel
**Rejected** because BaseModel's `evaluate()` signature returns `ModelOutput` (which has `direction: int`). ScoringModel returns `ScoringOutput` (which has `edge_score: float`). Inheriting would require either a broken Liskov substitution or a Union return type, both of which are worse than a parallel ABC. The common validation methods (`validate_features`, `validate_required_fields`) are duplicated (~10 lines) intentionally to keep the class hierarchies clean.

### Option D: Separate Valkey stream for engineered features
**Rejected** because it would require StrategyWorker to consume two streams and correlate timestamps. Merging engineered features into the existing `FeatureVector.features` dict with an `eng_` prefix is simpler and maintains the single-stream-per-asset-timeframe architecture.
