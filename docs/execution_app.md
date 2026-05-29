# Execution App — Technical Documentation

## 1. Overview

The **Execution App** is the order execution and fill-reporting layer in the flipperAgent pipeline. It sits between the risk layer and the portfolio layer, consuming `OrderExecutionRequest` payloads from Valkey streams, executing them via a pluggable executor (paper or live), and publishing `ExecutionReport` fills downstream.

**Single Responsibility:** Execute every incoming order exactly once, simulate or route it to an exchange, and publish a structured fill report for downstream consumers (risk_app FillListener, portfolio_app).

---

## 2. High-Level Design (HLD)

### 2.1 Position in Pipeline

```mermaid
flowchart LR
    subgraph Risk App
        RW[RiskWorker]
    end

    subgraph Execution App
        EW[ExecutionWorker] --> OM[OrderManager]
        OM --> ID[IdempotencyStore]
        OM --> EX[Executor]
        OM --> FT[FillTracker]
    end

    subgraph Portfolio App
        PW[PortfolioWorker]
    end

    subgraph Risk App FillListener
        FL[FillListener]
    end

    RW -- "orders:{asset}" --> EW
    EW -- "fills:{asset}" --> FL
    EW -- "fills:{asset}" --> PW
```

### 2.2 Design Principles

| Principle | Implementation |
|---|---|
| **Decoupled via streams** | No imports from `risk_app` or `portfolio_app` — Valkey streams are the only boundary |
| **Exactly-once semantics** | `IdempotencyStore` LRU dedup + `persist_to_db` prevents duplicate fills on PEL replay after restart |
| **Pluggable executor** | `BaseExecutor` ABC — `PaperExecutor` for simulation, `BinanceExecutor` stub for live (not yet implemented) |
| **Shared `OrderManager`** | Single `OrderManager` instance shared across all per-asset workers — serializes execution behind an `asyncio.Lock` |
| **PEL drain on boot** | `BaseStreamConsumer.run()` calls `XAUTOCLAIM` at startup to reprocess any messages unacked at crash time |
| **Idempotency persist/load** | At startup: `IdempotencyStore.load(reader_pool)` restores previously processed keys. At shutdown: `IdempotencyStore.save(writer_pool)` persists the current set |

### 2.3 Key Contracts

| Contract | Direction | Schema |
|---|---|---|
| **Order input** | Valkey `XREADGROUP` from `orders:{asset}` | `OrderExecutionRequest`: `{asset, side, size, order_type, requested_price, stop_loss_price, take_profit_price, model_name, source_timeframe, idempotency_key}` |
| **Fill output** | Valkey `XADD` to `fills:{asset}` | `ExecutionReport`: `{order_id, asset, side, requested_size, filled_size, requested_price, average_fill_price, status, fills, slippage_bps, stop_loss_price, take_profit_price, idempotency_key, error_message, metadata}` |

---

## 3. Low-Level Design (LLD)

### 3.1 Component Architecture

```mermaid
classDiagram
    class ExecutionWorker {
        +asset: str
        +order_manager: OrderManager
        +order_stream_key: str
        +fill_stream_key: str
        +connect(redis_client)
        +start()
        +process_message(id, data)
        -_decode_order(payload) OrderExecutionRequest
        -_encode_report(report) dict
    }

    class OrderManager {
        +executor: BaseExecutor
        +idempotency_store: IdempotencyStore
        +fill_tracker: FillTracker
        -_lock: asyncio.Lock
        +process_order(order) ExecutionReport | None
        -_validate(order) str
        -_rejection_report(order, error) ExecutionReport
    }

    class IdempotencyStore {
        -_seen: OrderedDict[str, float]
        -_max_size: int
        +is_duplicate(key) bool
        +mark_processed(key, timestamp)
        +save(db_pool)
        +load(db_pool, max_size) IdempotencyStore
    }

    class PaperExecutor {
        +slippage_bps: float
        +slippage_jitter_bps: float
        +commission_bps: float
        +fill_delay_ms: float
        -_rng: random.Random
        -_positions: dict[str, dict]
        -_balance: dict[str, float]
        +execute_order(order) ExecutionReport
        +get_positions() dict
        +get_balance() dict
    }

    class FillTracker {
        -_fills: list[ExecutionReport]
        -_slippage_by_asset: defaultdict[str, list[float]]
        +record_fill(report)
        +get_average_slippage_bps(asset) float
        +get_fill_history(asset, limit) list[ExecutionReport]
        +save_report(db_pool, report)
    }

    ExecutionWorker --> OrderManager
    OrderManager --> IdempotencyStore
    OrderManager --> PaperExecutor
    OrderManager --> FillTracker
```

### 3.2 File Structure

```
src/
├── apps/
│   └── execution_app/
│       ├── main.py              # Entrypoint — builds shared components, spawns workers
│       ├── execution_worker.py  # Per-asset BaseStreamConsumer subclass
│       └── __init__.py
└── libs/
    └── execution/
        ├── executor_base.py     # BaseExecutor ABC
        ├── paper_executor.py    # PaperExecutor — slippage simulation
        ├── binance_executor.py  # BinanceExecutor stub (not yet implemented)
        ├── order_manager.py     # OrderManager — dedup, validate, execute, track
        ├── idempotency.py       # IdempotencyStore — LRU dedup with DB persistence
        └── fill_tracker.py      # FillTracker — in-memory fill history + slippage
```

---

## 4. Boot Sequence

```mermaid
sequenceDiagram
    participant main as main.py
    participant cfg as ConfigManager
    participant disc as discover_assets
    participant db as DBPoolManager
    participant ids as IdempotencyStore
    participant ew as ExecutionWorker

    main->>cfg: register_file(execution.yaml, models.yaml)
    main->>disc: discover_assets(config_mgr)
    disc-->>main: [BTCUSDT, ETHUSDT, ...]
    main->>db: init_db_pools(config_mgr)
    main->>main: build PaperExecutor (or raise NotImplementedError for live)
    alt persist_to_db = true
        main->>ids: IdempotencyStore.load(reader_pool, max_size)
        ids-->>main: store with previously processed keys
    else
        main->>ids: IdempotencyStore(max_size)
    end
    main->>main: FillTracker(), OrderManager(executor, ids, fill_tracker)
    loop per asset
        main->>ew: ExecutionWorker(asset, order_manager, exec_config)
        main->>ew: connect(redis_client)
        Note over ew: ensure_consumer_group("orders:{asset}", "execution_app_group")
        main->>ew: asyncio.create_task(worker.start())
    end
    main->>main: asyncio.gather(*tasks)
    Note over main: BaseException → cancel all tasks → re-raise
    main->>ids: IdempotencyStore.save(writer_pool) [finally block, if persist_to_db]
    main->>main: redis_client.aclose() + DBPoolManager.close_pools()
```

---

## 5. Order Processing Flow

```mermaid
sequenceDiagram
    participant rv as Valkey
    participant ew as ExecutionWorker
    participant om as OrderManager
    participant ids as IdempotencyStore
    participant ex as PaperExecutor
    participant ft as FillTracker

    rv->>ew: XREADGROUP orders:{asset} (batch_size=10, block=1000ms)
    Note over ew: PEL drain via XAUTOCLAIM at startup
    ew->>ew: valkey_decode(payload) → OrderExecutionRequest
    ew->>om: process_order(order) [asyncio.Lock acquired]
    om->>ids: is_duplicate(idempotency_key)?
    alt duplicate
        om-->>ew: None (silent skip)
    else new
        om->>om: _validate(order) — size > 0, side ∈ {buy,sell}, price > 0
        alt invalid
            om->>ft: record_fill(REJECTED report)
            om->>ids: mark_processed(key, ts)
            om-->>ew: ExecutionReport(status=REJECTED)
        else valid
            om->>ex: execute_order(order)
            ex->>ex: asyncio.sleep(fill_delay_ms / 1000)
            ex->>ex: fill_price = requested_price × (1 ± slippage_bps/10000)
            ex-->>om: ExecutionReport(status=FILLED)
            om->>ft: record_fill(report)
            om->>ids: mark_processed(key, ts)
            om-->>ew: ExecutionReport(status=FILLED)
        end
    end
    ew->>rv: XADD fills:{asset} valkey_encode(report) maxlen=5000
    ew->>rv: XACK orders:{asset} message_id (inside try — only on success)
```

---

## 6. PaperExecutor Slippage Model

Direction-aware slippage — buys fill worse (above), sells fill worse (below):

$$\text{fill\_price} = \begin{cases}
P_{\text{req}} \times \left(1 + \frac{s_{\text{bps}} + j}{10000}\right) & \text{buy} \\
P_{\text{req}} \times \left(1 - \frac{s_{\text{bps}} + j}{10000}\right) & \text{sell}
\end{cases}$$

Where $j \sim \text{Uniform}(0, \text{jitter\_bps})$ with seeded RNG (`seed=42` by default).

Commission is deducted from balance:

$$\text{commission} = \text{size} \times \text{fill\_price} \times \frac{c_{\text{bps}}}{10000}$$

Signed slippage in the report:

$$\text{slippage\_bps} = \frac{\text{fill\_price} - P_{\text{req}}}{P_{\text{req}}} \times 10000$$

Positive = worse for buyer, negative = better for buyer (i.e., favourable slippage on sells).

### 6.1 Paper position tracking

`PaperExecutor` maintains internal `_positions` and `_balance` dicts for `get_positions()` / `get_balance()` observability:

| Side | Long open | Long close/reduce | Short open | Short reduce/close |
|---|---|---|---|---|
| **Buy** | VWAP avg_price updated | — | — | Short size reduced |
| **Sell** | — | Long size decremented (deleted if ≤1e-12) | Negative size entry created, VWAP updated | Short size decremented |

Short positions are represented as `size < 0` in `_positions[asset]`.

---

## 7. IdempotencyStore

Bounded LRU `OrderedDict` mapping `idempotency_key → timestamp`. Evicts oldest entries when `max_size` is reached (default: `10_000`).

### 7.1 Exactly-once guarantee across restarts

```mermaid
sequenceDiagram
    participant main as main.py (restart)
    participant db as DB
    participant ids as IdempotencyStore
    participant rv as Valkey PEL

    main->>db: IdempotencyStore.load(reader_pool)
    db-->>main: previously processed keys
    rv->>main: XAUTOCLAIM — reclaim unacked messages from PEL
    Note over main: Each message: ids.is_duplicate(key)?
    Note over main: YES → skip (fill already published pre-crash)
    Note over main: NO → execute + publish fill
    main->>db: IdempotencyStore.save(writer_pool) [on shutdown]
```

Without `persist_to_db: true`, PEL replay after restart would re-execute every order unacked at crash time, publishing duplicate fills to `fills:{asset}`.

---

## 8. Error Handling

| Scenario | Behaviour |
|---|---|
| Duplicate `idempotency_key` | Silently skipped — `process_order` returns `None`; no fill published |
| Invalid order (size ≤ 0, bad side, price ≤ 0) | `REJECTED` `ExecutionReport` published to `fills:{asset}`; idempotency key marked |
| Executor exception | Logged at ERROR; `REJECTED` report generated with error message; key marked |
| Message decode failure | Exception propagates up to `BaseStreamConsumer` — message stays in PEL (not acked), retried on next boot |
| Worker task crash | `BaseException` handler in `main.py` cancels all peer tasks before re-raising |
| IdempotencyStore DB load failure | Warning logged; execution continues with empty in-memory store |
| IdempotencyStore DB save failure | Warning logged on shutdown; in-flight processed keys are lost but fills were already published |
| Consumer group already exists | Silently ignored (`BUSYGROUP` swallowed by `ensure_consumer_group`) |
| `mode: live` configured | `NotImplementedError` raised at startup — app refuses to start |

---

## 9. Configuration Reference (`execution.yaml`)

```yaml
execution:
  mode: paper   # "paper" or "live" (live raises NotImplementedError)

  paper:
    slippage_bps: 5.0            # Base slippage applied to every fill
    slippage_jitter_bps: 2.0     # Additional random component (Uniform[0, jitter])
    commission_bps: 4.0          # Round-trip commission per fill
    fill_delay_ms: 50            # Simulated exchange latency
    partial_fill_probability: 0.0  # Not yet wired — always full fills

  live:
    api_key_path: secrets/binance_api_key
    api_secret_path: secrets/binance_api_secret
    testnet: true
    recv_window: 5000

  order_defaults:
    default_type: market
    timeout_seconds: 30

  rate_limiting:
    orders_per_second: 5         # Not yet enforced — no rate limiter wired
    burst_size: 10

  idempotency:
    max_memory_keys: 10000       # LRU eviction threshold
    persist_to_db: true          # Load on boot, save on shutdown

  slippage_tracking:
    enabled: true
    alert_threshold_bps: 20.0   # FillTracker tracks this; no alert emitted yet

  reconciliation:
    enabled: false
    interval_seconds: 300

  assets:
    BTCUSDT:
      rate_limit_override:
        orders_per_second: 3
    ETHUSDT: {}
    default: {}
```

---

## 10. API Observability

`GET /execution/fills` — latest `ExecutionReport` per asset from `fills:{asset}`.

**Response shape per asset:**

```json
{
  "BTCUSDT": {
    "stream": "fills:BTCUSDT",
    "message_id": "1234567890123-0",
    "timestamp": 1717000000.0,
    "lag_ms": 800,
    "status": "ok",
    "order_id": "a1b2c3d4e5f6",
    "side": "buy",
    "requested_size": 0.012345,
    "filled_size": 0.012345,
    "requested_price": 67450.5,
    "average_fill_price": 67453.9,
    "fill_status": "filled",
    "slippage_bps": 0.50,
    "stop_loss_price": 65800.0,
    "take_profit_price": 69200.0,
    "idempotency_key": "abc123...",
    "error_message": null
  }
}
```

`status` values: `ok`, `no_data`, `error`.

---

## 11. Known Gaps / Future Work

| Gap | Description |
|---|---|
| **`FillTracker.save_report` never called** | Fills persist only in-memory and are lost on restart. `save_report(db_pool, report)` exists but `ExecutionWorker` has no `db_pool` reference and never calls it. Requires wiring `writer_pool` into the worker. |
| **Rate limiting not enforced** | `rate_limiting.orders_per_second` is declared in config but no token bucket or semaphore is wired anywhere. A high-frequency signal storm would send uncapped orders to the exchange. |
| **`partial_fill_probability` silently ignored** | `paper.partial_fill_probability: 0.0` is in config but `PaperExecutor.__init__` does not accept it. Partial fill simulation never triggers even if set > 0. |
| **`BinanceExecutor` is a stub** | `mode: live` raises `NotImplementedError`. No live execution path exists. |
| **Fill publish atomicity** | `xadd fills:{asset}` succeeds before `xack` of the order message. On PEL re-delivery the idempotency key dedupes correctly → `process_order` returns `None` → no second `xadd`. The fill is not republished on replay. Consumers depending on exactly-once fill receipt from the stream must tolerate at-most-once delivery on the fill side. |
| **No `/execution/status` endpoint** | No endpoint exposes `PaperExecutor.get_positions()` or `get_balance()`, or per-asset fill counts and average slippage from `FillTracker`. |
