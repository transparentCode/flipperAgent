---
goal: Implement Execution App with paper/live mode, feedback loop to Risk Manager, and Binance USD-M Futures integration
stage: architect-to-coder
date_created: 2026-05-25
last_updated: 2026-05-25
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, execution, paper-trading, binance, order-management]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Execution App — Architect-to-Coder Handoff

## Objective

Build an Execution App that consumes `OrderExecutionRequest` messages from `orders:{asset}` Valkey streams (published by Risk Manager), executes them via a pluggable executor (paper or live), and publishes fill results back to a `fills:{asset}` stream so that Risk Manager can update its `PositionTracker` and `AccountState`.

---

## Locked-In Decisions

| Decision | Choice |
|---|---|
| Deployment | Separate app (`execution_app`) with own Valkey consumer group |
| Executor pattern | Adapter ABC — `PaperExecutor` and `BinanceExecutor` implementations |
| Default mode | Paper (simulated fills from config) |
| Feedback loop | Publish `ExecutionReport` to `fills:{asset}` Valkey stream |
| Risk Manager feedback | New `FillListener` component in `risk_app` consumes `fills:{asset}` and updates PositionTracker + AccountState |
| Idempotency | In-memory LRU set (bounded) + DB table for persistence across restarts |
| Order types | `market` now; `limit`, `stop_market` as extensibility points (interface only, no impl) |
| Rate limiting | Token bucket per-asset, configurable in execution.yaml |
| Slippage simulation (paper) | Configurable fixed bps + random jitter |
| Slippage tracking (live) | Compare requested_price vs fill_price, log and persist |
| Balance/margin pre-check | Paper: check against AccountState; Live: exchange validates |
| User data stream (live) | Binance `listenKey` WebSocket for real-time fill updates |
| Reconciliation | Periodic task comparing local position state vs exchange position state |
| Scope | Full architecture, extensible toward derivatives/multi-leg futures |

---

## Scope Boundaries

### In Scope
- `src/libs/execution/` — core execution logic (executor ABC, paper executor, order manager, fill tracker, idempotency store)
- `src/apps/execution_app/` — Valkey consumer per-asset, main entrypoint
- `src/apps/risk_app/fill_listener.py` — NEW: consumes `fills:{asset}`, updates PositionTracker/AccountState
- `configs/execution.yaml` — execution configuration
- New Pydantic schemas in `src/libs/contracts/schemas.py`
- Enrichment of `OrderExecutionRequest` (add `stop_loss_price`, `take_profit_price`)
- Tests under `tests/execution/`
- Update `risk_app/main.py` to spawn FillListener tasks alongside RiskWorkers

### Explicit Non-Goals
- Live Binance executor implementation (interface + stub only — needs API keys and testing)
- Alembic migrations (schema definition only)
- Multi-leg / complex order types (extensibility point in ABC)
- Portfolio-level reconciliation
- UI / dashboard

---

## Affected Symbols, Modules, and Execution Flows

### New Files

```
src/libs/execution/
├── __init__.py
├── executor_base.py       # BaseExecutor ABC
├── paper_executor.py      # PaperExecutor — simulated fills
├── binance_executor.py    # BinanceExecutor — stub with interface
├── order_manager.py       # OrderManager — lifecycle, retry, timeout
├── fill_tracker.py        # FillTracker — slippage tracking, fill history
├── idempotency.py         # IdempotencyStore — dedup check

src/apps/execution_app/
├── __init__.py
├── main.py                # Entrypoint — discovers assets, spawns ExecutionWorkers
├── execution_worker.py    # Valkey consumer — per-asset

src/apps/risk_app/
├── fill_listener.py       # NEW — consumes fills:{asset}, updates risk state

tests/execution/
├── __init__.py
├── test_paper_executor.py
├── test_order_manager.py
├── test_fill_tracker.py
├── test_idempotency.py
├── test_execution_worker.py

configs/execution.yaml
```

### Modified Files

| File | Change |
|---|---|
| `src/libs/contracts/schemas.py` | Add `ExecutionReport`, `OrderFill`, `OrderStatus` enum; enrich `OrderExecutionRequest` with SL/TP prices |
| `src/apps/risk_app/risk_worker.py` | Pass `stop_loss_price` and `take_profit_price` from `RiskAssessment` into `OrderExecutionRequest` |
| `src/apps/risk_app/main.py` | Spawn `FillListener` tasks alongside `RiskWorker` tasks |
| `src/libs/common/enums.py` | Add `EXECUTION` to `SystemComponent` (or reuse existing `TRADE_EXECUTION`) |

### Not Changed
- All model, indicator, optimization code
- signal_app, strategy_app, ingestion_app
- libs/risk/ core logic (engine, rules, sizer, etc.)
- Existing configs (base.yaml, models.yaml, features.yaml, optimization.yaml, risk.yaml)

---

## Data Contracts / Interfaces

### 1. OrderExecutionRequest Enrichment (modify existing)

```python
class OrderExecutionRequest(BaseModel):
    asset: str
    side: str                          # "buy" or "sell"
    size: float
    order_type: str = "market"
    timestamp: float
    requested_price: float
    idempotency_key: str
    stop_loss_price: Optional[float] = None      # NEW — from RiskAssessment
    take_profit_price: Optional[float] = None     # NEW — from RiskAssessment
```

### 2. risk_worker.py Update

Currently builds `OrderExecutionRequest` without SL/TP. Change to:

```python
order = OrderExecutionRequest(
    asset=signal.asset,
    side="buy" if signal.direction == 1 else "sell",
    size=assessment.proposed_size,
    order_type="market",
    timestamp=signal.timestamp,
    requested_price=signal.price,
    idempotency_key=signal.idempotency_key,
    stop_loss_price=assessment.stop_loss_price,       # NEW
    take_profit_price=assessment.take_profit_price,   # NEW
)
```

### 3. New Schemas

```python
class OrderStatus(str, Enum):
    """Order lifecycle states."""
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderFill(BaseModel):
    """A single fill event (partial or complete)."""
    fill_id: str
    asset: str
    side: str
    size: float                         # filled quantity
    fill_price: float
    commission: float = 0.0
    commission_asset: str = "USDT"
    timestamp: float
    is_maker: bool = False


class ExecutionReport(BaseModel):
    """Published to fills:{asset} after order execution completes."""
    order_id: str                       # internal tracking ID
    idempotency_key: str
    asset: str
    side: str
    requested_size: float
    filled_size: float
    requested_price: float
    average_fill_price: float
    status: OrderStatus
    fills: list[OrderFill] = Field(default_factory=list)
    slippage_bps: float = 0.0          # (avg_fill - requested) / requested * 10000
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    timestamp: float
    error_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

## Component Specifications

### A. BaseExecutor (`libs/execution/executor_base.py`)

```python
class BaseExecutor(ABC):
    """Pluggable executor — paper or live exchange."""

    @abstractmethod
    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport:
        """Submit order and return execution report."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str, asset: str) -> bool:
        """Cancel a pending order. Returns True if cancelled."""
        ...

    @abstractmethod
    async def get_positions(self, asset: str | None = None) -> list[dict]:
        """Query current positions from the execution venue."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, float]:
        """Query account balance from the execution venue."""
        ...
```

### B. PaperExecutor (`libs/execution/paper_executor.py`)

```python
class PaperExecutor(BaseExecutor):
    """Simulated execution for paper trading."""

    def __init__(self, config: dict[str, Any]):
        self.slippage_bps = config.get("slippage_bps", 5.0)
        self.slippage_jitter_bps = config.get("slippage_jitter_bps", 2.0)
        self.commission_bps = config.get("commission_bps", 4.0)
        self.fill_delay_ms = config.get("fill_delay_ms", 50)
        self.partial_fill_probability = config.get("partial_fill_probability", 0.0)

    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport:
        """Simulate fill with configurable slippage and commission."""
        # 1. Apply slippage: fill_price = requested ± slippage (direction-aware)
        # 2. Apply commission
        # 3. Return single-fill ExecutionReport with status=FILLED
        # 4. If partial_fill_probability > 0, randomly split into 2 fills
        ...

    async def cancel_order(self, order_id: str, asset: str) -> bool:
        return True  # Always succeeds in paper mode

    async def get_positions(self, asset: str | None = None) -> list[dict]:
        return []  # Paper mode doesn't track exchange-side positions

    async def get_balance(self) -> dict[str, float]:
        return {}  # Balance tracked in AccountState
```

### C. BinanceExecutor (`libs/execution/binance_executor.py`) — STUB ONLY

```python
class BinanceExecutor(BaseExecutor):
    """Live execution via Binance USD-M Futures API.

    STUB — interface defined, implementation deferred until API key setup.
    """

    def __init__(self, config: dict[str, Any]):
        # Will use: UMFutures(key=..., secret=...) from binance-futures-connector
        # Will need: listenKey management for user data stream
        ...

    async def execute_order(self, order: OrderExecutionRequest) -> ExecutionReport:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def cancel_order(self, order_id: str, asset: str) -> bool:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def get_positions(self, asset: str | None = None) -> list[dict]:
        raise NotImplementedError("BinanceExecutor not yet implemented")

    async def get_balance(self) -> dict[str, float]:
        raise NotImplementedError("BinanceExecutor not yet implemented")
```

### D. OrderManager (`libs/execution/order_manager.py`)

```python
class OrderManager:
    """Manages order lifecycle: validate → submit → track → report."""

    def __init__(self, executor: BaseExecutor, idempotency_store: IdempotencyStore,
                 fill_tracker: FillTracker):
        ...

    async def process_order(self, order: OrderExecutionRequest) -> ExecutionReport | None:
        """Full order lifecycle. Returns None if deduplicated."""
        # 1. Idempotency check — skip if already processed
        # 2. Validate order (size > 0, valid side, etc.)
        # 3. Execute via executor
        # 4. Record in fill tracker (slippage tracking)
        # 5. Mark idempotency key as processed
        # 6. Return ExecutionReport
        ...
```

### E. IdempotencyStore (`libs/execution/idempotency.py`)

```python
class IdempotencyStore:
    """Deduplication store for order idempotency keys."""

    def __init__(self, max_size: int = 10_000):
        self._seen: OrderedDict[str, float] = OrderedDict()  # key → timestamp
        self._max_size = max_size

    def is_duplicate(self, key: str) -> bool:
        """Check if key was already processed."""
        ...

    def mark_processed(self, key: str, timestamp: float) -> None:
        """Record key as processed. Evicts oldest if at capacity."""
        ...

    # DB persistence for restart recovery
    async def save(self, db_pool) -> None: ...

    @classmethod
    async def load(cls, db_pool, max_size: int = 10_000) -> "IdempotencyStore": ...
```

### F. FillTracker (`libs/execution/fill_tracker.py`)

```python
class FillTracker:
    """Track fill history and slippage metrics."""

    def record_fill(self, report: ExecutionReport) -> None:
        """Record execution report for slippage analysis."""
        ...

    def get_average_slippage_bps(self, asset: str | None = None) -> float:
        """Average slippage in basis points, optionally filtered by asset."""
        ...

    def get_fill_history(self, asset: str | None = None,
                         limit: int = 100) -> list[ExecutionReport]:
        """Recent fill history."""
        ...

    # DB persistence
    async def save_report(self, db_pool, report: ExecutionReport) -> None: ...
```

### G. ExecutionWorker (`apps/execution_app/execution_worker.py`)

```python
class ExecutionWorker:
    """Per-asset Valkey consumer. Consumes orders:{asset}, publishes fills:{asset}."""

    def __init__(self, asset: str, order_manager: OrderManager,
                 exec_config: dict[str, Any]):
        self.asset = asset
        self.order_stream_key = f"orders:{asset}"
        self.fill_stream_key = f"fills:{asset}"
        self.group_name = "execution_app_group"
        self.consumer_name = f"execution_worker_{asset}"
        ...

    async def start(self) -> None:
        """Consume orders, execute, publish fills."""
        # Standard xreadgroup loop (same pattern as strategy_worker, risk_worker)
        # For each order:
        #   1. Decode OrderExecutionRequest
        #   2. order_manager.process_order(order)
        #   3. If result: publish ExecutionReport to fills:{asset}
        ...
```

### H. FillListener (`apps/risk_app/fill_listener.py`)

```python
class FillListener:
    """Consumes fills:{asset} and updates Risk Manager's PositionTracker + AccountState.

    Runs inside risk_app process (same event loop as RiskWorkers).
    """

    def __init__(self, asset: str, account: AccountState,
                 positions: PositionTracker):
        self.asset = asset
        self.fill_stream_key = f"fills:{asset}"
        self.group_name = "risk_app_fills_group"
        self.consumer_name = f"fill_listener_{asset}"
        ...

    async def start(self) -> None:
        """Consume fills, update positions and account state."""
        # xreadgroup loop on fills:{asset}
        # For each ExecutionReport:
        #   1. If status == FILLED and side == buy:
        #      positions.open_position(PositionState from report)
        #   2. If status == FILLED and side == sell:
        #      Close matching position, record PnL in account
        #   3. Update account.unrealized from current positions
        ...
```

### I. execution_app main.py

```python
def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all assets."""

async def _run() -> None:
    # 1. Load configs: execution.yaml, models.yaml
    # 2. Discover assets
    # 3. Determine executor mode from config (paper/live)
    # 4. Build executor (PaperExecutor or BinanceExecutor)
    # 5. Build IdempotencyStore, FillTracker, OrderManager
    # 6. Spawn one ExecutionWorker per asset
    # 7. asyncio.gather all workers

def main() -> None:
    asyncio.run(_run())
```

---

## Config: `configs/execution.yaml`

```yaml
execution:
  mode: paper   # "paper" or "live"

  paper:
    slippage_bps: 5.0
    slippage_jitter_bps: 2.0
    commission_bps: 4.0
    fill_delay_ms: 50
    partial_fill_probability: 0.0

  live:
    # API keys resolved via ConfigManager (NOT os.getenv)
    api_key_path: secrets/binance_api_key
    api_secret_path: secrets/binance_api_secret
    testnet: true
    recv_window: 5000

  order_defaults:
    default_type: market
    timeout_seconds: 30

  rate_limiting:
    orders_per_second: 5
    burst_size: 10

  idempotency:
    max_memory_keys: 10000
    persist_to_db: true

  slippage_tracking:
    enabled: true
    alert_threshold_bps: 20.0

  reconciliation:
    enabled: false
    interval_seconds: 300

  assets:
    BTCUSDT:
      rate_limit_override:
        orders_per_second: 3
    ETHUSDT: {}
    SOLUSDT: {}
    default: {}
```

---

## Stream Topology

```
orders:BTCUSDT ──► ExecutionWorker(BTCUSDT) ──► fills:BTCUSDT ──► FillListener(BTCUSDT) ──► PositionTracker + AccountState
orders:ETHUSDT ──► ExecutionWorker(ETHUSDT) ──► fills:ETHUSDT ──► FillListener(ETHUSDT) ──► PositionTracker + AccountState
orders:SOLUSDT ──► ExecutionWorker(SOLUSDT) ──► fills:SOLUSDT ──► FillListener(SOLUSDT) ──► PositionTracker + AccountState
```

Consumer groups:
- `execution_app_group` — ExecutionWorkers consume `orders:{asset}`
- `risk_app_fills_group` — FillListeners consume `fills:{asset}`

---

## Implementation Order

| Step | What | Depends On |
|---|---|---|
| 1 | Enrich `OrderExecutionRequest` schema: add `stop_loss_price`, `take_profit_price` | — |
| 2 | Update `risk_worker.py` to pass SL/TP into `OrderExecutionRequest` | Step 1 |
| 3 | New schemas: `OrderStatus`, `OrderFill`, `ExecutionReport` | — |
| 4 | `libs/execution/executor_base.py` — `BaseExecutor` ABC | Step 3 |
| 5 | `libs/execution/idempotency.py` — `IdempotencyStore` | — |
| 6 | `libs/execution/fill_tracker.py` — `FillTracker` | Step 3 |
| 7 | `libs/execution/paper_executor.py` — `PaperExecutor` | Step 4 |
| 8 | `libs/execution/binance_executor.py` — `BinanceExecutor` stub | Step 4 |
| 9 | `libs/execution/order_manager.py` — `OrderManager` | Steps 4, 5, 6 |
| 10 | `configs/execution.yaml` | — |
| 11 | `apps/execution_app/execution_worker.py` | Steps 9, 10 |
| 12 | `apps/execution_app/main.py` | Step 11 |
| 13 | `apps/risk_app/fill_listener.py` — FillListener | Steps 3, risk libs |
| 14 | Update `apps/risk_app/main.py` — spawn FillListener tasks | Step 13 |
| 15 | Tests: `tests/execution/test_*.py` | Steps 1–14 |

---

## Acceptance Criteria

1. `OrderExecutionRequest` carries `stop_loss_price` and `take_profit_price`; existing tests still pass
2. `PaperExecutor` simulates fills with configurable slippage/commission
3. `BinanceExecutor` stub implements `BaseExecutor` ABC with `NotImplementedError`
4. `OrderManager` deduplicates via `IdempotencyStore`, validates, executes, tracks fills
5. `IdempotencyStore` supports LRU eviction and DB persistence interface
6. `FillTracker` records fills, computes average slippage
7. `ExecutionWorker` consumes `orders:{asset}`, publishes `ExecutionReport` to `fills:{asset}`
8. `FillListener` consumes `fills:{asset}`, calls `PositionTracker.open_position()` / `close_position()` and `AccountState.record_trade_close()`
9. `execution_app/main.py` discovers assets, selects executor from config, spawns workers
10. `risk_app/main.py` spawns FillListener tasks per asset
11. `configs/execution.yaml` parsed by ConfigManager with per-asset overrides
12. All new code uses `bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)`
13. No `os.getenv`, no `logging.getLogger`, no cross-app imports between execution_app and risk_app (Valkey streams only)
14. Tests cover: paper executor (slippage, commission), order manager (dedup, lifecycle), fill tracker, idempotency store, execution worker

## Validation Checklist

- [ ] Existing 209 tests still pass (new `OrderExecutionRequest` fields have defaults)
- [ ] PaperExecutor: fill price includes slippage (long and short), commission calculated
- [ ] IdempotencyStore: dedup works, LRU eviction at capacity
- [ ] OrderManager: duplicate orders skipped, valid orders executed
- [ ] FillTracker: slippage bps calculation correct
- [ ] ExecutionWorker: consumes from stream, publishes fill
- [ ] FillListener: opens position on buy fill, closes on sell fill, updates account
- [ ] risk_app/main.py spawns FillListeners without breaking existing RiskWorker startup

---

## Blast Radius

| Area | Impact |
|---|---|
| `OrderExecutionRequest` schema | Two new optional fields with defaults — fully backward-compatible |
| `risk_worker.py` | 2-line change to forward SL/TP — no behavioral change |
| `risk_app/main.py` | Additional FillListener tasks spawned — no change to RiskWorker behavior |
| All other existing code | Untouched |

---

## Conventions to Follow

- Logging: `bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)`
- Config: `ConfigManager` singleton, `register_file("configs/execution.yaml")`
- Schemas: Pydantic `BaseModel` in `libs/contracts/schemas.py`
- No cross-app imports: `execution_app` imports from `libs/execution/`, never from `apps/risk_app/`
- FillListener lives in `risk_app` because it updates risk state — but uses only Valkey streams, no import from `execution_app`
- Stream keys: `orders:{asset}` (consume), `fills:{asset}` (produce/consume)
- Tests: pytest, under `tests/execution/`, no Docker/DB dependency (mock DB operations)

---

## DB Schema (Reference Only — Not Implemented Now)

```sql
-- execution_fills (for slippage tracking and audit)
CREATE TABLE IF NOT EXISTS execution_fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    asset TEXT NOT NULL,
    side TEXT NOT NULL,
    requested_size DOUBLE PRECISION NOT NULL,
    filled_size DOUBLE PRECISION NOT NULL,
    requested_price DOUBLE PRECISION NOT NULL,
    average_fill_price DOUBLE PRECISION NOT NULL,
    slippage_bps DOUBLE PRECISION NOT NULL,
    commission DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL
);
SELECT create_hypertable('execution_fills', 'timestamp', if_not_exists => TRUE);

-- idempotency_keys (for restart recovery)
CREATE TABLE IF NOT EXISTS execution_idempotency_keys (
    key TEXT PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL
);
```

---

## Residual Risks / Follow-Ups

- **Live executor:** `BinanceExecutor` is a stub. Needs API key management, listenKey WebSocket for real-time fills, and thorough integration testing before going live.
- **Position direction matching:** `FillListener` needs logic to match a sell fill to the correct open long position (by asset). For now, FIFO matching (close oldest position first).
- **Partial fills:** PaperExecutor has `partial_fill_probability` but the FillListener needs to handle partial fills correctly (don't close position until fully filled).
- **Rate limiting:** Token bucket implementation is in OrderManager. For v1, simple `asyncio.sleep` throttle is acceptable.
- **Reconciliation:** Disabled by default. When enabled, will need exchange API access to query positions and compare.
- **SL/TP exchange orders:** The current design passes SL/TP to ExecutionReport for FillListener to set on PositionState. A future enhancement could submit native exchange SL/TP orders (OCO orders on Binance).
- **Multi-leg futures:** BaseExecutor ABC is extensible — future implementations can handle multi-leg orders via additional methods.

---

This document is complete enough for the Coder Agent to implement without guessing.
