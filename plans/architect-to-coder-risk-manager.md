---
goal: Implement Risk Manager as a separate app with MTF aggregation, pluggable risk rules, multiple position sizing and SL/TP strategies, DB-persisted state, and paper trading mode
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, risk, position-sizing, mtf]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Risk Manager — Architect-to-Coder Handoff

## Objective

Build a Risk Manager module that sits between `strategy_app` (signal producer) and a future `execution_app` (order executor). It consumes `TradeSignal` messages from all timeframes per asset, applies configurable risk rules, sizes positions, attaches stop-loss/take-profit levels, and publishes `OrderExecutionRequest` messages. Account and position state are persisted to TimescaleDB.

## Locked-In Decisions

| Decision | Choice |
|---|---|
| Account mode | Paper trading (simulated balance from config) |
| MTF conflict resolution default | `conviction_weighted` — configurable per-asset |
| Position state persistence | TimescaleDB |
| Multi-model signal handling | Per-asset configurable: `aggregate` (combine) or `independent` (per-model budget) |
| Deployment | Separate app (`risk_app`) with own Valkey consumer group |
| SL/TP methods | All implemented: `atr_based`, `fixed_pct`, `trailing` — configurable per-asset per-TF |
| Scope | Full architecture, extensible toward derivatives/multi-leg futures |

---

## Scope Boundaries

### In Scope
- `src/libs/risk/` — core risk logic (engine, rules, sizer, position tracker, account state, MTF aggregator)
- `src/apps/risk_app/` — Valkey consumer per-asset
- `configs/risk.yaml` — risk configuration with fallback chains
- New Pydantic schemas in `src/libs/contracts/schemas.py`
- Enrichment of existing `TradeSignal` schema (add `model_name`, `metadata`)
- Corresponding update in `strategy_worker.py` to populate new fields
- `src/libs/common/enums.py` — add `RISK_MANAGER` to SystemComponent
- Tests under `tests/risk/`

### Explicit Non-Goals
- Live exchange integration (future execution_app concern)
- Cross-asset correlation limits (future rule, extensibility point only)
- Portfolio-level VaR (future rule)
- Derivatives / multi-leg futures (extensibility only, no implementation now)
- Modifying any model, indicator, or optimization code
- Database migration scripts (schema definition only — manual or alembic later)

---

## Affected Symbols, Modules, and Execution Flows

### New Files

```
src/libs/risk/
├── __init__.py
├── engine.py              # RiskEngine — evaluates rule chain, produces RiskAssessment
├── position_tracker.py    # PositionTracker — in-memory state + DB persistence
├── account_state.py       # AccountState — balance, equity, PnL, drawdown
├── sizer.py               # PositionSizer — fixed_fractional, kelly, volatility_scaled, equal_weight
├── stop_loss.py           # StopLossCalculator — atr_based, fixed_pct, trailing
├── take_profit.py         # TakeProfitCalculator — risk_reward, fixed_pct, trailing
├── rules/
│   ├── __init__.py        # RiskRuleRegistry
│   ├── base.py            # RiskRule ABC + RiskVerdict + RiskContext
│   ├── max_exposure.py    # MaxExposureRule — total exposure % of equity
│   ├── max_drawdown.py    # MaxDrawdownRule — circuit breaker
│   ├── max_positions.py   # MaxPositionsRule — concurrent position limit
│   ├── daily_loss.py      # DailyLossLimitRule — halt for the day
│   └── cooldown.py        # CooldownAfterLossRule — time-based cooldown
├── mtf/
│   ├── __init__.py
│   └── aggregator.py      # SignalAggregator — MTF conflict resolution

src/apps/risk_app/
├── __init__.py
├── main.py                # Entrypoint — discovers assets, spawns RiskWorkers
├── risk_worker.py         # Valkey consumer — per-asset, all timeframes

configs/risk.yaml          # Risk configuration

tests/risk/
├── __init__.py
├── test_engine.py
├── test_position_tracker.py
├── test_account_state.py
├── test_sizer.py
├── test_stop_loss.py
├── test_take_profit.py
├── test_rules.py
├── test_aggregator.py
├── test_risk_worker.py
```

### Modified Files

| File | Change |
|---|---|
| `src/libs/contracts/schemas.py` | Add `model_name` + `metadata` to `TradeSignal`; add `RiskVerdict`, `RiskAssessment`, `PositionState`, `AccountSnapshot` |
| `src/apps/strategy_app/strategy_worker.py` | Populate `model_name` and `metadata` on `TradeSignal` from `ModelOutput` |
| `src/libs/common/enums.py` | Add `RISK_MANAGER` to `SystemComponent` |

### Not Changed

- All model code (`libs/models/`)
- All indicator code (`libs/features/`)
- All optimization code (`libs/optim_utils/`)
- `signal_app`, `ingestion_app`
- Existing configs (`base.yaml`, `models.yaml`, `features.yaml`, `optimization.yaml`)

---

## Data Contracts / Interfaces

### 1. TradeSignal Enrichment (modify existing)

```python
class TradeSignal(BaseModel):
    asset: str
    timeframe: str
    timestamp: float
    direction: int           # 1 long, -1 short, 0 flat
    conviction: float
    price: float
    idempotency_key: str
    model_name: str = ""                                    # NEW
    metadata: dict[str, Any] = Field(default_factory=dict)  # NEW — carries ATR, etc.
```

### 2. strategy_worker.py Update

Currently drops `model_name` and `metadata` from `ModelOutput`. Change to:

```python
signal = TradeSignal(
    asset=output.asset,
    timeframe=output.timeframe,
    timestamp=output.timestamp,
    direction=output.direction,
    conviction=output.conviction,
    price=feature_vec.bar_data.get("close", 0.0),
    idempotency_key=self._make_idempotency_key(...),
    model_name=output.model_name,          # NEW
    metadata=output.metadata,              # NEW
)
```

### 3. New Schemas

```python
class RiskVerdict(BaseModel):
    """Output of a single risk rule evaluation."""
    action: Literal["ALLOW", "MODIFY", "REJECT"]
    rule_name: str
    reason: str = ""
    adjusted_size: Optional[float] = None


class RiskAssessment(BaseModel):
    """Full risk evaluation result — passed to order publishing."""
    allowed: bool
    signal: TradeSignal
    proposed_size: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    rejection_reason: str = ""
    rules_applied: list[str] = Field(default_factory=list)
    verdicts: list[RiskVerdict] = Field(default_factory=list)


class PositionState(BaseModel):
    """Tracks a single open position."""
    asset: str
    direction: int                     # 1 long, -1 short
    entry_price: float
    current_price: float
    size: float
    unrealized_pnl: float
    entry_timestamp: float
    source_model: str
    source_timeframe: str
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    trailing_stop_distance: Optional[float] = None


class AccountSnapshot(BaseModel):
    """Point-in-time account state."""
    timestamp: float
    balance: float                     # initial + realized PnL
    equity: float                      # balance + unrealized PnL
    unrealized_pnl: float
    realized_pnl: float
    drawdown_pct: float
    peak_equity: float
    open_position_count: int
    daily_pnl: float
```

---

## Component Specifications

### A. RiskEngine (`libs/risk/engine.py`)

```
RiskEngine
├── __init__(rules: list[RiskRule], sizer: PositionSizer, sl_calc, tp_calc)
├── assess(signal, account, positions, risk_config) -> RiskAssessment
│   ├── 1. Run MTF aggregator (if enabled for asset)
│   ├── 2. Calculate proposed size via PositionSizer
│   ├── 3. Calculate SL/TP via calculators
│   ├── 4. Build RiskContext
│   ├── 5. Iterate rules — first REJECT stops chain
│   ├── 6. If MODIFY, update proposed_size
│   └── 7. Return RiskAssessment
```

Rules are loaded at boot from config. Order matters — evaluated sequentially.

### B. Risk Rules (`libs/risk/rules/`)

Each rule implements:

```python
class RiskRule(ABC):
    name: str

    @abstractmethod
    def evaluate(self, context: RiskContext) -> RiskVerdict:
        ...

@dataclass
class RiskContext:
    signal: TradeSignal
    proposed_size: float
    account: AccountState
    positions: PositionTracker
    risk_config: dict[str, Any]
```

**Rules to implement:**

| Rule | Logic |
|---|---|
| `MaxExposureRule` | Reject if total exposure + proposed > `max_total_exposure_pct` of equity |
| `MaxPositionsRule` | Reject if open positions >= `max_concurrent_positions` |
| `MaxDrawdownRule` | Reject ALL new trades if `current_drawdown_pct` > `max_drawdown_pct` (circuit breaker) |
| `DailyLossLimitRule` | Reject if `daily_pnl` loss > `daily_loss_limit_pct` of equity |
| `CooldownAfterLossRule` | Reject if last closed trade was a loss and happened < `cooldown_seconds` ago |

Registry pattern (same as `ModelRegistry`):

```python
class RiskRuleRegistry:
    _registry: dict[str, type[RiskRule]] = {}

    @classmethod
    def register(cls, name: str): ...

    @classmethod
    def get(cls, name: str) -> type[RiskRule]: ...
```

### C. PositionSizer (`libs/risk/sizer.py`)

```python
class PositionSizer:
    def calculate(self, strategy: str, signal: TradeSignal,
                  account: AccountState, risk_config: dict) -> float:
        """Dispatch to sizing method. Returns position size in base asset units."""
        ...

    def _fixed_fractional(self, signal, account, config) -> float:
        """size = (equity * risk_per_trade_pct / 100) / (entry_price * stop_distance_pct)"""

    def _volatility_scaled(self, signal, account, config) -> float:
        """size = (equity * target_risk_pct / 100) / (ATR * atr_multiplier)
        ATR sourced from signal.metadata.get("ATR")"""

    def _kelly(self, signal, account, config) -> float:
        """size = kelly_fraction * (win_rate - (1 - win_rate) / rr_ratio) * equity / price
        Needs historical win_rate — fall back to fixed_fractional if unavailable."""

    def _equal_weight(self, signal, account, config) -> float:
        """size = equity / (max_concurrent_positions * price)"""
```

### D. StopLossCalculator (`libs/risk/stop_loss.py`)

```python
class StopLossCalculator:
    def calculate(self, method: str, signal: TradeSignal, config: dict) -> float | None:
        ...

    def _atr_based(self, signal, config) -> float:
        """SL = price ∓ ATR * multiplier (sign depends on direction)"""

    def _fixed_pct(self, signal, config) -> float:
        """SL = price * (1 ∓ pct/100)"""

    def _trailing(self, signal, config) -> float:
        """Initial SL same as atr_based. Trailing updates handled by PositionTracker."""
```

### E. TakeProfitCalculator (`libs/risk/take_profit.py`)

```python
class TakeProfitCalculator:
    def calculate(self, method: str, signal: TradeSignal,
                  stop_loss_price: float | None, config: dict) -> float | None:
        ...

    def _risk_reward(self, signal, sl_price, config) -> float:
        """TP = entry ± (|entry - SL| * ratio)"""

    def _fixed_pct(self, signal, config) -> float:
        """TP = price * (1 ± pct/100)"""

    def _trailing(self, signal, config) -> float:
        """Initial TP same as risk_reward. Trailing updates handled by PositionTracker."""
```

### F. AccountState (`libs/risk/account_state.py`)

```python
class AccountState:
    initial_balance: float
    realized_pnl: float
    unrealized_pnl: float
    peak_equity: float
    daily_pnl: float
    daily_reset_timestamp: float
    last_trade_pnl: float
    last_trade_timestamp: float

    @property
    def equity(self) -> float: return self.initial_balance + self.realized_pnl + self.unrealized_pnl

    @property
    def balance(self) -> float: return self.initial_balance + self.realized_pnl

    @property
    def current_drawdown_pct(self) -> float: ...

    def record_trade_close(self, pnl: float, timestamp: float) -> None: ...
    def update_unrealized(self, positions: list[PositionState]) -> None: ...
    def check_daily_reset(self, current_timestamp: float) -> None: ...
    def snapshot(self) -> AccountSnapshot: ...

    # DB persistence
    async def save_snapshot(self, db_pool) -> None: ...

    @classmethod
    async def load_latest(cls, db_pool, initial_balance: float) -> "AccountState": ...
```

### G. PositionTracker (`libs/risk/position_tracker.py`)

```python
class PositionTracker:
    positions: dict[str, list[PositionState]]  # asset -> list of open positions

    def open_position(self, state: PositionState) -> None: ...
    def close_position(self, asset: str, position_id: ...) -> float: ...  # returns PnL
    def update_prices(self, asset: str, current_price: float) -> None: ...
    def update_trailing_stops(self, asset: str, current_price: float) -> None: ...
    def check_sl_tp(self, asset: str, current_price: float) -> list[PositionState]: ...  # hit positions
    def get_total_exposure(self) -> float: ...
    def get_position_count(self) -> int: ...
    def get_asset_exposure(self, asset: str) -> float: ...

    # DB persistence
    async def save_positions(self, db_pool) -> None: ...

    @classmethod
    async def load_positions(cls, db_pool) -> "PositionTracker": ...
```

### H. MTF SignalAggregator (`libs/risk/mtf/aggregator.py`)

```python
class SignalAggregator:
    def aggregate(self, signals: list[TradeSignal], strategy: str,
                  tf_weights: dict[str, float]) -> TradeSignal | None:
        """Resolve multiple signals for same asset across timeframes."""
        ...

    def _conviction_weighted(self, signals, tf_weights) -> TradeSignal | None:
        """Net direction = sign(sum(direction * conviction * tf_weight)).
        Net conviction = |weighted_sum| / sum(weights).
        Returns None if net direction is 0 (cancel)."""

    def _higher_tf_priority(self, signals, tf_weights) -> TradeSignal | None:
        """Take the signal from the highest timeframe. Ignore lower TFs on conflict."""

    def _cancel_on_conflict(self, signals, tf_weights) -> TradeSignal | None:
        """If any disagreement on direction, return None."""

    def _independent(self, signals, tf_weights) -> list[TradeSignal]:
        """No aggregation — each signal processed independently with budget slice."""
```

**Timeframe ordering:** `1m < 5m < 15m < 1h < 4h < 1d` (use `BARS_PER_YEAR` keys from `optim_utils/scoring.py` as canonical ordering).

### I. RiskWorker (`apps/risk_app/risk_worker.py`)

```python
class RiskWorker:
    """Per-asset Valkey consumer. Subscribes to signals:{asset}:{tf} for ALL timeframes."""

    def __init__(self, asset: str, timeframes: list[str], risk_engine: RiskEngine):
        self.asset = asset
        self.signal_stream_keys = [f"signals:{asset}:{tf}" for tf in timeframes]
        self.order_stream_key = f"orders:{asset}"
        self.group_name = "risk_app_group"
        ...

    async def start(self):
        """Consume from all signal streams, buffer for MTF aggregation,
        run risk engine, publish OrderExecutionRequest."""

    async def _process_signal_batch(self, signals: list[TradeSignal]):
        """MTF aggregation → RiskEngine.assess() → publish or reject."""
```

**Signal buffering for MTF:** When `conflict_resolution != "independent"`, the worker buffers signals within a configurable window (`signal_timeout_seconds`) before aggregating. When using `independent`, each signal is processed immediately.

### J. risk_app main.py (`apps/risk_app/main.py`)

```python
def _discover_assets(config_mgr: ConfigManager) -> dict[str, list[str]]:
    """Read models.yaml to find all (asset, [timeframes]) pairs.
    Returns: {"BTCUSDT": ["1h", "4h"], "ETHUSDT": ["4h"], ...}"""

async def _run():
    # 1. Load configs: risk.yaml, models.yaml
    # 2. Discover assets and their timeframes
    # 3. Bootstrap AccountState from DB (or initial_balance)
    # 4. Bootstrap PositionTracker from DB
    # 5. Build RiskEngine with rules from config
    # 6. Spawn one RiskWorker per asset
    # 7. asyncio.gather all workers
```

---

## Config: `configs/risk.yaml`

```yaml
risk:
  account:
    initial_balance: 10000
    currency: USDT
    leverage_limit: 5.0

  global_limits:
    max_total_exposure_pct: 80
    max_concurrent_positions: 10
    max_drawdown_pct: 15
    daily_loss_limit_pct: 5
    cooldown_after_loss_seconds: 0

  rules:
    - MaxExposureRule
    - MaxPositionsRule
    - MaxDrawdownRule
    - DailyLossLimitRule
    - CooldownAfterLossRule

  position_sizing:
    default_strategy: volatility_scaled
    fixed_fractional:
      risk_per_trade_pct: 2.0
    volatility_scaled:
      target_risk_pct: 1.0
      atr_multiplier: 2.0
    kelly:
      fraction: 0.5
    equal_weight: {}

  stop_loss:
    default_method: atr_based
    atr_based:
      multiplier: 2.0
    fixed_pct:
      pct: 2.0
    trailing:
      atr_multiplier: 2.0

  take_profit:
    default_method: risk_reward
    risk_reward:
      ratio: 2.0
    fixed_pct:
      pct: 4.0
    trailing:
      atr_multiplier: 3.0

  mtf:
    default_conflict_resolution: conviction_weighted
    signal_timeout_seconds: 300
    timeframe_weights:
      1m: 0.25
      5m: 0.5
      15m: 0.75
      1h: 1.0
      4h: 1.5
      1d: 2.0

  assets:
    BTCUSDT:
      max_position_pct: 40
      signal_handling: aggregate
      position_sizing:
        strategy: volatility_scaled
      stop_loss:
        method: atr_based
      timeframes:
        1h:
          risk_budget_pct: 60
        4h:
          risk_budget_pct: 40
    ETHUSDT:
      max_position_pct: 30
      signal_handling: aggregate
    SOLUSDT:
      max_position_pct: 20
      signal_handling: independent
      stop_loss:
        method: trailing
    default:
      max_position_pct: 20
      signal_handling: aggregate
      position_sizing:
        strategy: volatility_scaled
      stop_loss:
        method: atr_based
      take_profit:
        method: risk_reward
```

---

## Stream Topology

```
signals:BTCUSDT:1h ──┐
signals:BTCUSDT:4h ──┤── RiskWorker(BTCUSDT) ──► orders:BTCUSDT
                     │
signals:ETHUSDT:4h ──┤── RiskWorker(ETHUSDT) ──► orders:ETHUSDT
                     │
signals:SOLUSDT:15m ─┤── RiskWorker(SOLUSDT) ──► orders:SOLUSDT
```

Consumer group: `risk_app_group` (distinct from `strategy_app_group`).

---

## Implementation Order

| Step | What | Depends On |
|---|---|---|
| 1 | Add `RISK_MANAGER` to `SystemComponent` enum | — |
| 2 | Enrich `TradeSignal` schema: add `model_name`, `metadata` | — |
| 3 | Update `strategy_worker.py` to populate `model_name` + `metadata` | Step 2 |
| 4 | New schemas: `RiskVerdict`, `RiskAssessment`, `PositionState`, `AccountSnapshot` | — |
| 5 | `libs/risk/rules/base.py` — `RiskRule` ABC, `RiskContext`, `RiskRuleRegistry` | Step 4 |
| 6 | `libs/risk/account_state.py` — `AccountState` | Step 4 |
| 7 | `libs/risk/position_tracker.py` — `PositionTracker` | Step 4 |
| 8 | `libs/risk/sizer.py` — `PositionSizer` (all 4 strategies) | Steps 4, 6 |
| 9 | `libs/risk/stop_loss.py` — `StopLossCalculator` (all 3 methods) | Step 4 |
| 10 | `libs/risk/take_profit.py` — `TakeProfitCalculator` (all 3 methods) | Step 4 |
| 11 | Implement all 5 risk rules in `libs/risk/rules/` | Step 5 |
| 12 | `libs/risk/mtf/aggregator.py` — `SignalAggregator` (all 4 strategies) | Step 4 |
| 13 | `libs/risk/engine.py` — `RiskEngine` | Steps 5–12 |
| 14 | `configs/risk.yaml` | — |
| 15 | `apps/risk_app/risk_worker.py` | Steps 13, 14 |
| 16 | `apps/risk_app/main.py` | Step 15 |
| 17 | Tests: `tests/risk/test_*.py` | Steps 1–16 |

---

## Acceptance Criteria

1. `TradeSignal` carries `model_name` and `metadata`; existing tests still pass
2. All 5 risk rules implement `RiskRule` ABC and are registered via `RiskRuleRegistry`
3. `PositionSizer` supports all 4 strategies; dispatches based on config string
4. `StopLossCalculator` supports `atr_based`, `fixed_pct`, `trailing`
5. `TakeProfitCalculator` supports `risk_reward`, `fixed_pct`, `trailing`
6. `SignalAggregator` supports `conviction_weighted`, `higher_tf_priority`, `cancel_on_conflict`, `independent`
7. `RiskEngine.assess()` chains rules, sizes position, attaches SL/TP, returns `RiskAssessment`
8. `AccountState` tracks balance/equity/drawdown/daily_pnl; supports snapshot serialization
9. `PositionTracker` opens/closes positions, checks SL/TP hits, updates trailing stops
10. `RiskWorker` consumes from multiple signal streams, runs engine, publishes to `orders:{asset}`
11. `risk_app/main.py` discovers assets from models.yaml, spawns workers
12. `configs/risk.yaml` parsed by `ConfigManager` with fallback chains (asset → default)
13. All new code uses `bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)`
14. No `os.getenv`, no `logging.getLogger`, no cross-app imports
15. Tests cover: each rule (allow/reject), each sizing strategy, each SL/TP method, MTF aggregation (all 4 modes), engine chain, account state transitions, position lifecycle

## Validation Checklist

- [ ] Existing 130 tests still pass (TradeSignal enrichment is backward-compatible: new fields have defaults)
- [ ] Each risk rule tested: ALLOW case + REJECT case
- [ ] Each sizing strategy tested with known inputs → expected output
- [ ] Each SL/TP method tested (long + short direction)
- [ ] MTF aggregation: conviction_weighted with agreeing signals, conflicting signals, single signal
- [ ] MTF aggregation: higher_tf_priority, cancel_on_conflict, independent
- [ ] RiskEngine: full chain with multiple rules
- [ ] AccountState: PnL recording, drawdown calculation, daily reset
- [ ] PositionTracker: open, close, PnL, trailing stop update, SL/TP hit detection
- [ ] Config parsing: fallback from asset-specific to default

---

## Blast Radius

| Area | Impact |
|---|---|
| `TradeSignal` schema | Two new optional fields with defaults — fully backward-compatible |
| `strategy_worker.py` | 2-line change to forward `model_name` + `metadata` — no behavioral change |
| `SystemComponent` enum | One new member — no existing code affected |
| All other existing code | Untouched |

---

## Conventions to Follow

- Pattern: `RiskRuleRegistry` same as `ModelRegistry` and `IndicatorRegistry`
- Logging: `bind_logger(__name__, system_component=SystemComponent.RISK_MANAGER)`
- Config: `ConfigManager` singleton, `register_file("configs/risk.yaml")`
- Schemas: Pydantic `BaseModel` in `libs/contracts/schemas.py`
- No cross-app imports: `risk_app` imports from `libs/risk/`, never from `apps/strategy_app/`
- Stream keys: `signals:{asset}:{timeframe}` (consume), `orders:{asset}` (produce)
- Tests: pytest, under `tests/risk/`, no Docker/DB dependency (mock DB operations)

---

## DB Schema (Reference Only — Not Implemented Now)

For `PositionTracker` and `AccountState` persistence, the coder should define `save_*` and `load_*` methods with `asyncpg` pool as parameter. The actual DB tables are:

```sql
-- positions (for recovery on restart)
CREATE TABLE IF NOT EXISTS risk_positions (
    id SERIAL PRIMARY KEY,
    asset TEXT NOT NULL,
    direction INT NOT NULL,
    entry_price DOUBLE PRECISION NOT NULL,
    size DOUBLE PRECISION NOT NULL,
    entry_timestamp TIMESTAMPTZ NOT NULL,
    source_model TEXT NOT NULL,
    source_timeframe TEXT NOT NULL,
    stop_loss_price DOUBLE PRECISION,
    take_profit_price DOUBLE PRECISION,
    trailing_stop_distance DOUBLE PRECISION,
    closed_at TIMESTAMPTZ,
    close_price DOUBLE PRECISION,
    realized_pnl DOUBLE PRECISION
);

-- account snapshots (periodic, for equity curve)
CREATE TABLE IF NOT EXISTS risk_account_snapshots (
    timestamp TIMESTAMPTZ NOT NULL,
    balance DOUBLE PRECISION NOT NULL,
    equity DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    realized_pnl DOUBLE PRECISION NOT NULL,
    drawdown_pct DOUBLE PRECISION NOT NULL,
    peak_equity DOUBLE PRECISION NOT NULL,
    open_position_count INT NOT NULL,
    daily_pnl DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('risk_account_snapshots', 'timestamp', if_not_exists => TRUE);
```

The coder should implement the Python-side `save_*`/`load_*` methods. The SQL DDL above is reference for what the methods expect. Actual migration is out of scope.

---

## Residual Risks / Follow-Ups

- **Signal buffering latency:** MTF aggregation with `signal_timeout_seconds` introduces delay. For `independent` mode there is no delay.
- **Paper trading accuracy:** No slippage simulation, no order book depth. Acceptable for v1.
- **Kelly criterion cold-start:** No historical win-rate data initially. Fall back to `fixed_fractional` when win-rate unavailable.
- **Trailing stop complexity:** Requires price updates between signals. `RiskWorker` may need to also consume `stream:ohlcv:{asset}:{timeframe}` for price ticks. Defer to implementation — can start with updating trailing stops only on new signals.

---

This document is complete enough for the Coder Agent to implement without guessing.
