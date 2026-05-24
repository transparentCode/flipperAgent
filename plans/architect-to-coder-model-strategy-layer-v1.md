---
goal: Design and specify the model-driven strategy layer with hyperparameter optimization for flipperAgent
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, strategy, model-layer, optimization, optuna, architecture]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Architect to Coder Handoff: Model-Driven Strategy Layer v1

## 1. Objective

Build a **model-driven strategy layer** where each model (e.g., `MeanReversionModel`, `TrendFollowingModel`, `MomentumModel`) declaratively specifies its required indicators, features, data contracts, and hyperparameters. The layer supports:

1. **Model registry** — models register themselves and are discovered dynamically at runtime via config.
2. **Model-specific feature requirements** — each model declares exactly which indicators/features it needs; the `FeatureManager` already computes these per asset/timeframe, and the model layer consumes the results.
3. **Hyperparameter optimization** — offline batch optimization using Optuna (single-objective) and Optuna's `NSGAIISampler` (multi-objective Pareto front), with trial persistence in TimescaleDB.
4. **Signal emission** — models produce `TradeSignal` objects (already defined in `src/libs/contracts/schemas.py`) published to Valkey streams for downstream consumption.

---

## 2. Scope Boundaries

### In Scope
- Model base class with declarative feature requirements and hyperparameter schema.
- Model registry (decorator-based, mirroring `IndicatorRegistry`).
- Configuration schema (`configs/models.yaml`) mapping asset/timeframe to models and their hyperparameters.
- `ModelManager` that wires feature outputs to the correct models per asset/timeframe.
- `StrategyWorker` that subscribes to feature output streams and dispatches to `ModelManager`.
- Offline hyperparameter optimization harness with Optuna.
- Trial storage schema in TimescaleDB.
- Pydantic contracts for model inputs, outputs, and optimization results.

### Explicit Non-Goals
- Order management / execution layer (future phase).
- Portfolio-level allocation, position sizing, or risk management.
- Live online parameter adaptation (deferred; v1 is offline-only optimization).
- ML model inference (neural nets, gradient-boosted trees) — v1 targets rule-based quantitative models only.
- Backtesting engine (the optimization harness calls a backtest runner, but the backtest engine itself is a separate handoff).
- Modifying the existing `FeatureManager`, `SignalWorker`, or indicator code.

---

## 3. Architecture Overview

### Data Flow

```
Ingestion (1m OHLCV)
    │
    ▼
Valkey Stream: market_data:{asset}:{timeframe}   (closed bar events)
    │
    ▼
SignalWorker (existing) → FeatureManager → indicator.update()
    │
    ▼
Valkey Stream: features:{asset}:{timeframe}       (computed feature vectors)  ◄── NEW publish point
    │
    ▼
StrategyWorker (NEW) → ModelManager → model.evaluate()
    │
    ▼
Valkey Stream: signals:{asset}:{timeframe}        (TradeSignal objects)
    │
    ▼
(Future) Order Management / Risk Gateway
```

### Key Design Decision: Feature Streams as Decoupling Boundary

The existing `SignalWorker.process_message()` computes indicators but does not currently publish feature vectors. **The first prerequisite** is wiring the existing `SignalWorker` to publish computed feature dictionaries to a new Valkey stream `features:{asset}:{timeframe}` after each tick. The strategy layer consumes this stream — it never imports or calls `FeatureManager` directly.

This preserves the existing decoupled microservice boundary:
- `signal_app` owns feature computation.
- `strategy_app` (NEW) owns model inference and signal generation.
- Valkey streams are the sole coupling surface.

---

## 4. Module Structure

```
src/
  apps/
    strategy_app/                       # NEW — strategy microservice
      __init__.py
      main.py                           # Entrypoint: boots StrategyWorker(s) per asset/timeframe
      strategy_worker.py                # Valkey consumer → ModelManager → signal publish
      model_manager.py                  # Wires feature dicts to registered models

  libs/
    models/                             # NEW — pure model logic (no I/O)
      __init__.py
      base.py                           # BaseModel ABC + ModelMeta dataclass
      registry.py                       # ModelRegistry (decorator-based)
      mean_reversion.py                 # Concrete: MeanReversionModel
      trend_following.py                # Concrete: TrendFollowingModel
      momentum.py                       # Concrete: MomentumModel

    optimization/                       # NEW — hyperparameter optimization
      __init__.py
      runner.py                         # OptunaRunner: single + multi-objective
      objective.py                      # Objective function wrappers
      trial_store.py                    # TimescaleDB trial persistence
      schemas.py                        # Pydantic: TrialResult, StudyConfig, ParamSpace

    contracts/
      schemas.py                        # (existing) TradeSignal, OrderExecutionRequest
                                        # + NEW: FeatureVector, ModelOutput, TrialResult

configs/
  models.yaml                           # NEW — model config per asset/timeframe
```

---

## 5. Core Abstractions

### 5.1 `BaseModel` (ABC) — `src/libs/models/base.py`

```python
# Conceptual interface — NOT implementation code.

class ModelMeta:
    """Declarative metadata each model exposes."""
    name: str                                    # e.g. "MeanReversion"
    required_indicators: list[str]               # e.g. ["RSI", "BollingerBands"]
    required_fields: list[str]                   # e.g. ["RSI.value", "BollingerBands.upper"]
    hyperparameter_schema: dict[str, ParamDef]   # name → {type, default, low, high, step}
    min_history_bars: int                         # warm-up requirement

class BaseModel(ABC):
    meta: ModelMeta

    def __init__(self, params: dict): ...
    def evaluate(self, features: FeatureVector) -> ModelOutput: ...
    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series: ...
    def validate_features(self, available: set[str]) -> list[str]: ...
```

**Design rationale:**
- `required_indicators` lets the system validate at boot that `features.yaml` includes everything the model needs for the configured asset/timeframe. If MACD is required but not in `features.yaml` for SOLUSDT/15m, the system fails fast with a clear config error.
- `hyperparameter_schema` enables Optuna to auto-build the search space from the model's own declaration — no separate mapping file.
- `batch_evaluate` accepts a DataFrame for offline backtest/optimization. `evaluate` accepts a single `FeatureVector` for live inference.
- `validate_features` returns missing feature names so the boot sequence can report exactly what's misconfigured.

### 5.2 `ModelRegistry` — `src/libs/models/registry.py`

Mirror the existing `IndicatorRegistry` pattern:

```python
class ModelRegistry:
    _registry: dict[str, type[BaseModel]] = {}

    @classmethod
    def register(cls, name: str): ...     # decorator

    @classmethod
    def get(cls, name: str) -> type[BaseModel]: ...

    @classmethod
    def list_all(cls) -> list[str]: ...
```

Models self-register via `@ModelRegistry.register("MeanReversion")`.

### 5.3 `ModelManager` — `src/apps/strategy_app/model_manager.py`

```python
class ModelManager:
    """Loads models for a specific (asset, timeframe) from configs/models.yaml."""
    def __init__(self, asset: str, timeframe: str): ...
    def validate_feature_coverage(self, available_features: set[str]) -> None: ...
    def evaluate(self, features: FeatureVector) -> list[ModelOutput]: ...
```

- Reads `models.yaml` to determine which models run for this asset/timeframe.
- Instantiates each model with its configured hyperparameters.
- On each feature vector arrival, calls `model.evaluate()` on each active model.
- Returns a list of `ModelOutput` objects (one per model).

### 5.4 `StrategyWorker` — `src/apps/strategy_app/strategy_worker.py`

```python
class StrategyWorker:
    """Valkey consumer for feature streams. Dispatches to ModelManager."""
    def __init__(self, asset: str, timeframe: str): ...
    async def start(self): ...                   # XREADGROUP on features:{asset}:{timeframe}
    async def process_features(self, features: dict) -> None: ...
```

- Follows the same XREADGROUP consumer-group pattern as `SignalWorker`.
- Deserializes feature dict → `FeatureVector` Pydantic model.
- Calls `ModelManager.evaluate()`.
- Converts `ModelOutput` → `TradeSignal` and publishes to `signals:{asset}:{timeframe}`.

---

## 6. Configuration Schema: `configs/models.yaml`

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
              ema_cross_fast: 12
              ema_cross_slow: 26
              atr_multiplier: 1.5
        4h:
          TrendFollowing:
            enabled: true
            params:
              ema_cross_fast: 9
              ema_cross_slow: 21
              atr_multiplier: 2.0
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
    default:
      timeframes:
        default:
          MeanReversion:
            enabled: true
            params: {}    # uses model defaults from hyperparameter_schema
```

**Config resolution chain** (mirrors existing `features.yaml` pattern):
`Asset/Timeframe → Asset/default → default/Timeframe → default/default`

Each model entry supports:
- `enabled`: boolean toggle.
- `params`: overrides for the model's declared `hyperparameter_schema`. Missing keys use the model's defaults. This is where Optuna-optimized params land after a sweep.

---

## 7. Data Contracts (Pydantic)

### 7.1 `FeatureVector` — published by `SignalWorker`, consumed by `StrategyWorker`

```python
class FeatureVector(BaseModel):
    asset: str
    timeframe: str
    timestamp: float
    features: dict[str, Any]        # e.g. {"RSI": 42.3, "MACD": {"line": 0.5, "signal": 0.3, "histogram": 0.2}, ...}
    bar_data: dict[str, float]      # {"open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}
```

### 7.2 `ModelOutput` — returned by `BaseModel.evaluate()`

```python
class ModelOutput(BaseModel):
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    direction: int                  # 1 long, -1 short, 0 flat
    conviction: float               # 0.0–1.0
    metadata: dict[str, Any]        # model-specific debug info (e.g., {"rsi_value": 28, "trigger": "oversold"})
```

### 7.3 `TradeSignal` — already exists in `src/libs/contracts/schemas.py`

No changes needed. `StrategyWorker` converts `ModelOutput` → `TradeSignal` by adding `price` from `FeatureVector.bar_data["close"]` and computing `idempotency_key`.

### 7.4 Optimization Contracts

```python
class ParamDef(BaseModel):
    type: Literal["float", "int", "categorical"]
    default: Any
    low: Optional[float] = None
    high: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list[Any]] = None

class StudyConfig(BaseModel):
    model_name: str
    asset: str
    timeframe: str
    objectives: list[str]           # e.g. ["sharpe", "max_drawdown"]
    directions: list[str]           # e.g. ["maximize", "minimize"]
    n_trials: int = 200
    sampler: str = "TPE"            # "TPE" for single-obj, "NSGA-II" for multi-obj
    pruner: str = "MedianPruner"

class TrialResult(BaseModel):
    study_name: str
    trial_number: int
    params: dict[str, Any]
    values: dict[str, float]        # objective_name → value
    state: str                      # "COMPLETE", "PRUNED", "FAIL"
    duration_seconds: float
    timestamp: float
```

---

## 8. Hyperparameter Optimization Design

### 8.1 Architecture

```
                    ┌──────────────────────┐
                    │   OptunaRunner       │
                    │                      │
                    │  study = create_study│
                    │  study.optimize(     │
                    │    objective_fn,     │
                    │    n_trials          │
                    │  )                   │
                    └─────────┬────────────┘
                              │
                    ┌─────────▼────────────┐
                    │   objective_fn()     │
                    │                      │
                    │  1. trial.suggest_*  │
                    │     (from model's    │
                    │      param schema)   │
                    │  2. instantiate model│
                    │  3. run backtest     │
                    │  4. return metrics   │
                    └─────────┬────────────┘
                              │
                    ┌─────────▼────────────┐
                    │   BacktestRunner     │
                    │   (separate module)  │
                    │                      │
                    │  - loads historical  │
                    │    OHLCV from TSDB   │
                    │  - computes features │
                    │    via batch mode    │
                    │  - calls model's     │
                    │    batch_evaluate()  │
                    │  - computes metrics  │
                    └──────────────────────┘
```

### 8.2 Single-Objective vs Multi-Objective

| Scenario | Sampler | Objective | When to Use |
|----------|---------|-----------|-------------|
| Maximize Sharpe only | `TPESampler` | `sharpe_ratio` | Simple, fast convergence |
| Maximize Sharpe, minimize drawdown | `NSGAIISampler` | `[sharpe, max_drawdown]` | Pareto front exploration |
| Maximize Sharpe, minimize turnover, control drawdown | `NSGAIISampler` | `[sharpe, max_drawdown, turnover]` | Full multi-objective |

The `StudyConfig.objectives` and `StudyConfig.directions` fields control this. Optuna natively supports both via `create_study(directions=[...])`.

### 8.3 Optimization is Offline Only (v1)

- Runs as a CLI command or script: `python -m src.libs.optimization.runner --model MeanReversion --asset BTCUSDT --timeframe 1h`
- Reads historical OHLCV from TimescaleDB.
- Uses `Indicator.batch()` for vectorized feature computation (Numba-accelerated per established indicator architecture).
- Uses `BaseModel.batch_evaluate()` for vectorized signal generation.
- Stores all trial results in TimescaleDB table `optimization_trials`.
- After a study completes, the best params can be written back to `models.yaml` (manual or automated).

### 8.4 Trial Persistence — TimescaleDB

```sql
CREATE TABLE optimization_trials (
    id              BIGSERIAL PRIMARY KEY,
    study_name      TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    asset           TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    trial_number    INT NOT NULL,
    params          JSONB NOT NULL,
    objective_values JSONB NOT NULL,     -- {"sharpe": 1.23, "max_drawdown": -0.15}
    state           TEXT NOT NULL,       -- COMPLETE, PRUNED, FAIL
    duration_s      FLOAT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (study_name, trial_number)
);

-- Enable time-based querying
SELECT create_hypertable('optimization_trials', 'created_at', migrate_data => true);
```

### 8.5 Param Feedback Loop

After optimization:
1. Query Pareto front or best trial from `optimization_trials`.
2. Update `models.yaml` with the winning params.
3. `StrategyWorker` picks up the new config via `ConfigManager` hot-reload (already supports watchdog + atomic pointer swap per existing architecture).

---

## 9. Integration with Existing Systems

### 9.1 Feature Coverage Validation (Boot-Time)

When `ModelManager.__init__` loads models for an asset/timeframe:

1. Read `features.yaml` to determine which indicators are configured for this asset/timeframe.
2. For each model, call `model.validate_features(available_indicators)`.
3. If any required indicator is missing, raise `ConfigurationError` with a clear message:
   `"Model 'MeanReversion' for SOLUSDT/15m requires ['RSI', 'BollingerBands'] but features.yaml only provides ['RSI']"`

This prevents silent failures where a model expects features that aren't being computed.

### 9.2 SignalWorker Feature Publishing (Prerequisite Change)

The existing `SignalWorker.process_message()` must be extended to publish the feature dict to Valkey after computing indicators. This is a **minimal, additive change** to the existing file:

After `results = self.feature_manager.process_tick(data_tuple)`, publish:
```
XADD features:{asset}:{timeframe} * <serialized FeatureVector>
```

This is the **only modification to existing code**. All other work is net-new modules.

### 9.3 Docker Topology

Add a new service to `docker-compose.yml`:

```yaml
strategy-worker:
  build:
    context: .
    dockerfile: Dockerfile
  command: python -m apps.strategy_app.main
  environment:
    POSTGRES_URI: ...
    REDIS_URI: ...
    VALKEY_URI: ...
  depends_on:
    - db
    - broker
```

### 9.4 SystemComponent Enum

Add `MODEL_STRATEGY = "MODEL_STRATEGY"` and `OPTIMIZATION = "OPTIMIZATION"` to `src/libs/common/enums.py`.

---

## 10. Implementation Order

| Phase | Module | Description | Dependencies |
|-------|--------|-------------|--------------|
| **1** | `src/libs/contracts/schemas.py` | Add `FeatureVector`, `ModelOutput`, `ParamDef`, `StudyConfig`, `TrialResult` | None |
| **2** | `src/libs/models/base.py` | `BaseModel` ABC, `ModelMeta` dataclass | Phase 1 |
| **3** | `src/libs/models/registry.py` | `ModelRegistry` (decorator pattern) | Phase 2 |
| **4** | `src/libs/models/mean_reversion.py` | First concrete model | Phase 2, 3 |
| **5** | `configs/models.yaml` | Initial config for BTCUSDT | Phase 4 |
| **6** | `src/apps/strategy_app/model_manager.py` | Config-driven model loading + feature validation | Phase 3, 5 |
| **7** | `src/apps/signal_app/signal_worker.py` | Add feature vector publishing to Valkey (minimal edit) | Phase 1 |
| **8** | `src/apps/strategy_app/strategy_worker.py` | Valkey consumer + signal publisher | Phase 6, 7 |
| **9** | `src/apps/strategy_app/main.py` | Entrypoint: boots workers per asset/timeframe from config | Phase 8 |
| **10** | `src/libs/optimization/schemas.py` | Optimization Pydantic models (if not in contracts) | Phase 1 |
| **11** | `src/libs/optimization/trial_store.py` | TimescaleDB trial persistence | Phase 10 |
| **12** | `src/libs/optimization/objective.py` | Objective function wrappers | Phase 4, 11 |
| **13** | `src/libs/optimization/runner.py` | `OptunaRunner` CLI | Phase 12 |
| **14** | `src/libs/common/enums.py` | Add MODEL_STRATEGY, OPTIMIZATION | Phase 1 |
| **15** | `docker-compose.yml` | Add `strategy-worker` service | Phase 9 |
| **16** | Tests | Unit + integration tests | All phases |

---

## 11. Acceptance Criteria

1. **Boot validation**: `ModelManager` refuses to start if `features.yaml` doesn't cover all indicators required by configured models for that asset/timeframe.
2. **Feature consumption**: `StrategyWorker` correctly deserializes `FeatureVector` from Valkey stream and passes features to models.
3. **Signal emission**: Models produce `ModelOutput`, which `StrategyWorker` converts to `TradeSignal` and publishes to `signals:{asset}:{timeframe}`.
4. **Config-driven**: Adding a new model for an asset/timeframe requires only a `models.yaml` entry and a registered model class — no code changes to `StrategyWorker` or `ModelManager`.
5. **Registry works**: `@ModelRegistry.register("MyModel")` makes the model discoverable from config.
6. **Optimization runs**: `OptunaRunner` can execute a study for a given model/asset/timeframe, storing all trials in TimescaleDB.
7. **Multi-objective**: `NSGAIISampler` produces a Pareto front when multiple objectives are configured.
8. **Trial persistence**: All trials queryable from `optimization_trials` table with JSONB params and objective values.
9. **Idempotency**: `TradeSignal.idempotency_key` is deterministically derived from `(model_name, asset, timeframe, timestamp)`.
10. **Dual-mode models**: `evaluate()` for live, `batch_evaluate()` for optimization — same logic, different execution paths.

---

## 12. Validation Checklist

- [ ] No direct imports between `strategy_app` and `signal_app` — Valkey streams only.
- [ ] No direct imports between `strategy_app` and `ingestion_app`.
- [ ] `BaseModel.evaluate()` and `batch_evaluate()` produce identical outputs for identical inputs (parity test).
- [ ] `FeatureVector` Pydantic validation rejects malformed payloads.
- [ ] Config fallback chain works: asset/tf → asset/default → default/tf → default/default.
- [ ] Missing features raise `ConfigurationError` at boot, not silent `None` at runtime.
- [ ] Optuna single-objective study converges (test with mock objective).
- [ ] Optuna multi-objective study produces ≥ 2 Pareto-optimal trials.
- [ ] `TrialResult` round-trips through TimescaleDB correctly (JSONB params).
- [ ] Feature vector publishing does not break existing `SignalWorker` tests.
- [ ] No look-ahead bias in backtest: features computed only from data available at bar close time.
- [ ] No survivorship bias: optimization uses the full asset history, not just surviving periods.
- [ ] Transaction cost model is pluggable in the objective function (even if v1 uses zero costs).

---

## 13. Architecture Tradeoffs and Rejected Options

### Option A (CHOSEN): Model-driven with declarative feature requirements
- **Pros**: Each model owns its contract. Boot-time validation catches misconfigs. Clean separation of concerns. Easy to add new models.
- **Cons**: Requires feature coverage validation logic. Models must maintain `ModelMeta` in sync with their logic.
- **Why chosen**: Matches the existing `IndicatorRegistry` pattern. Scales naturally with new models.

### Option B (REJECTED): Feature-driven — models passively receive all available features
- **Pros**: Simpler wiring. No validation needed.
- **Cons**: Models silently fail on missing features. No contract enforcement. Hard to reason about which features a model actually uses.
- **Why rejected**: Violates the explicit-over-implicit principle. Silent failures are unacceptable in a quant pipeline.

### Option C (REJECTED): Monolithic strategy engine — single model per asset/timeframe
- **Pros**: Simpler architecture.
- **Cons**: Cannot run multiple models on the same asset/timeframe. Cannot compare model performance. Prevents ensemble strategies.
- **Why rejected**: User explicitly wants multiple models with different indicator requirements.

### Option D (REJECTED): Online hyperparameter adaptation
- **Pros**: Adapts to regime changes.
- **Cons**: Risk of overfitting to noise. Complex state management. Requires robust guardrails. Insufficient data to validate safety.
- **Why rejected**: Premature. v1 should prove offline optimization works before attempting live adaptation. Can be added as v2.

### Optimization Storage: TimescaleDB vs SQLite (Optuna default)
- **Chose TimescaleDB**: Already in the stack. Time-series queries on trials are natural. Shared across services.
- **Rejected SQLite**: Single-node, file-based, not accessible from Docker containers easily.

---

## 14. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Feature/model config drift | Models silently produce garbage | Boot-time validation in `ModelManager.validate_feature_coverage()` |
| Look-ahead bias in backtest | Optimization finds false alpha | `batch_evaluate` must only access features computed from data ≤ current bar timestamp |
| Overfitting in optimization | Poor out-of-sample performance | Train/test split in objective function; Optuna `MedianPruner` for early stopping |
| Valkey feature stream latency | Models evaluate stale features | Monitor lag between feature publish and strategy consume; alert if > 1 bar period |
| Multiple models producing conflicting signals | Ambiguous execution | v1: each model produces independent signals. Future v2: ensemble/arbitration layer |
| Optuna study explosion (too many params) | Slow convergence | Models should expose ≤ 10 hyperparameters. Use Sobol for sensitivity before full sweeps |

---

## 15. Blast Radius

### Existing Code Modifications (Minimal)
1. **`src/apps/signal_app/signal_worker.py`**: Add ~5 lines to publish `FeatureVector` to Valkey after `process_tick()`. No changes to existing logic flow.
2. **`src/libs/common/enums.py`**: Add 2 enum values. No existing values changed.
3. **`src/libs/contracts/schemas.py`**: Add new Pydantic models. No existing models changed.
4. **`docker-compose.yml`**: Add one service block. No existing services changed.
5. **`configs/`**: Add `models.yaml`. No existing config files changed.

### Affected Execution Flows
- **Feature computation flow**: Extended (not modified) by publishing feature vectors to a new Valkey stream.
- **No existing flows are altered or broken.**

### New Execution Flows
- `StrategyWorker` → `ModelManager` → `BaseModel.evaluate()` → `TradeSignal` publish.
- `OptunaRunner` → `objective_fn` → `BacktestRunner` → `BaseModel.batch_evaluate()`.

---

## 16. Future Extensions (Not in v1)

- **Ensemble layer**: Aggregate signals from multiple models into a composite signal.
- **Online adaptation**: Warm-start Optuna studies with live performance feedback.
- **ML models**: Extend `BaseModel` for sklearn/pytorch models with serialization.
- **Feature store**: Persist computed features to TimescaleDB for replay and debugging.
- **Walk-forward optimization**: Rolling window re-optimization with out-of-sample validation.
- **Order management integration**: Convert `TradeSignal` to `OrderExecutionRequest` with position sizing.
