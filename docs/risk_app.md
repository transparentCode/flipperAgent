# Risk App — Technical Documentation

## 1. Overview

The **Risk App** is the position-sizing, rule enforcement, and SL/TP monitoring layer in the flipperAgent pipeline. It sits between the strategy layer and the execution layer, consuming `TradeSignal` payloads from Valkey streams, running them through a configurable rule chain and position sizer via the `RiskEngine`, and publishing `OrderExecutionRequest` payloads for execution.

**Single Responsibility:** Assess every signal for risk compliance, size the position, attach SL/TP levels, and emit execution-ready orders.

---

## 2. High-Level Design (HLD)

### 2.1 Position in Pipeline

```mermaid
flowchart LR
    subgraph Strategy App
        STW[StrategyWorker]
    end

    subgraph Risk App
        RW[RiskWorker] --> AGG[SignalAggregator]
        AGG --> RE[RiskEngine]
        RE --> SZ[PositionSizer]
        RE --> SL[StopLossCalculator]
        RE --> TP[TakeProfitCalculator]
        RE --> RC[RuleChain]
        FL[FillListener] --> PT[PositionTracker]
        FL --> AS[AccountState]
    end

    subgraph Execution App
        EX[ExecutionWorker]
    end

    STW -- "signals:{asset}:{tf}" --> RW
    STW -- "price_update:{asset}:{tf}" --> RW
    EX -- "fills:{asset}" --> FL
    RW -- "orders:{asset}" --> EX
```

### 2.2 Design Principles

| Principle | Implementation |
|---|---|
| **Decoupled via streams** | No imports from `strategy_app` or `execution_app` — Valkey streams are the only integration boundary |
| **Config-driven rules** | `risk.yaml` declares which rule classes run and in which order; registry loads them by name |
| **Registry pattern** | `RiskRuleRegistry` auto-discovers rule classes via `@RiskRuleRegistry.register()` decorators |
| **Shared state** | `AccountState` and `PositionTracker` are passed into every worker — no per-worker isolation |
| **MTF batching** | One `RiskWorker` per asset reads ALL timeframe streams and batches signals into a single `SignalAggregator.aggregate()` call |
| **Heartbeat SL/TP** | `price_update:{asset}:{tf}` streams drive SL/TP monitoring on every bar — independent of signal arrival |
| **PEL drain on boot** | Signal streams are reclaimed via `XAUTOCLAIM` at startup to reprocess any messages unacked at crash time |

### 2.3 Key Contracts

| Contract | Direction | Schema |
|---|---|---|
| **Signal input** | Valkey `XREADGROUP` from `signals:{asset}:{tf}` | `TradeSignal`: `{asset, timeframe, timestamp, direction, conviction, price, idempotency_key, metadata}` |
| **Price input** | Valkey `XREADGROUP` from `price_update:{asset}:{tf}` | `PriceUpdate`: `{asset, timeframe, timestamp, open, high, low, close, volume}` |
| **Fill input** | Valkey `XREADGROUP` from `fills:{asset}` | `ExecutionReport`: `{asset, side, filled_size, average_fill_price, status, stop_loss_price, take_profit_price, metadata}` |
| **Order output** | Valkey `XADD` to `orders:{asset}` | `OrderExecutionRequest`: `{asset, side, size, order_type, requested_price, stop_loss_price, take_profit_price, idempotency_key}` |

---

## 3. Low-Level Design (LLD)

### 3.1 Component Architecture

```mermaid
classDiagram
    class RiskWorker {
        +asset: str
        +timeframes: list[str]
        +signal_stream_keys: list[str]
        +price_stream_keys: list[str]
        +order_stream_key: str
        +risk_engine: RiskEngine
        +signal_aggregator: SignalAggregator
        +account: AccountState
        +positions: PositionTracker
        +risk_config: dict
        +connect(redis_client)
        +start()
        +run()
        -_drain_signal_pel()
        -_process_signal_batch(signals)
        -_process_price_update(payload)
        -_decode_signal(payload) TradeSignal
    }

    class FillListener {
        +asset: str
        +account: AccountState
        +positions: PositionTracker
        +process_message(id, data)
        -_apply_fill(report)
        -_decode_execution_report(payload) ExecutionReport
    }

    class RiskEngine {
        +rules: list[RiskRule]
        +sizer: PositionSizer
        +sl_calc: StopLossCalculator
        +tp_calc: TakeProfitCalculator
        +assess(signal, account, positions, config) RiskAssessment
    }

    class SignalAggregator {
        +aggregate(signals, strategy, tf_weights) TradeSignal | list | None
        -_conviction_weighted(signals, weights)
        -_higher_tf_priority(signals, weights)
        -_cancel_on_conflict(signals, weights)
        -_independent(signals, weights)
    }

    class PositionSizer {
        +calculate(strategy, signal, account, config) float
        -_fixed_fractional(signal, account, config)
        -_volatility_scaled(signal, account, config)
        -_kelly(signal, account, config)
        -_equal_weight(signal, account, config)
    }

    class StopLossCalculator {
        +calculate(method, signal, config) float | None
        -_atr_based(signal, config)
        -_fixed_pct(signal, config)
        -_trailing(signal, config)
    }

    class TakeProfitCalculator {
        +calculate(method, signal, sl_price, config) float | None
        -_risk_reward(signal, sl_price, config)
        -_fixed_pct(signal, config)
        -_trailing(signal, config)
    }

    class PositionTracker {
        +positions: dict[str, list[PositionState]]
        +open_position(state)
        +close_position(asset, index) float
        +update_prices(asset, price)
        +update_trailing_stops(asset, price)
        +check_sl_tp_hlc(asset, high, low, close) list[PositionState]
        +get_position_count() int
        +get_total_exposure() float
        +save_positions(db_pool)
        +load_positions(db_pool) PositionTracker
    }

    class AccountState {
        +equity: float
        +balance: float
        +realized_pnl: float
        +unrealized_pnl: float
        +daily_pnl: float
        +current_drawdown_pct: float
        +record_trade_close(pnl, ts)
        +update_unrealized(positions)
        +check_daily_reset(ts)
        +save_snapshot(db_pool)
        +load_latest(db_pool, initial_balance) AccountState
    }

    RiskWorker --> RiskEngine
    RiskWorker --> SignalAggregator
    RiskWorker --> PositionTracker
    RiskWorker --> AccountState
    FillListener --> PositionTracker
    FillListener --> AccountState
    RiskEngine --> PositionSizer
    RiskEngine --> StopLossCalculator
    RiskEngine --> TakeProfitCalculator
```

### 3.2 File Structure

```
src/
├── apps/
│   └── risk_app/
│       ├── main.py              # Entrypoint — discovers assets, boots workers
│       ├── risk_worker.py       # Per-asset multi-stream consumer
│       ├── fill_listener.py     # Fill consumer — updates PositionTracker/AccountState
│       └── __init__.py
└── libs/
    └── risk/
        ├── engine.py             # RiskEngine — sizes, SL/TP, rule chain
        ├── sizer.py              # PositionSizer — 4 strategies
        ├── stop_loss.py          # StopLossCalculator — 3 methods
        ├── take_profit.py        # TakeProfitCalculator — 3 methods
        ├── position_tracker.py   # PositionTracker — in-memory state + DB
        ├── account_state.py      # AccountState — balance/equity/PnL/drawdown
        ├── mtf/
        │   └── aggregator.py     # SignalAggregator — 4 MTF strategies
        └── rules/
            ├── base.py           # RiskRule ABC, RiskContext, RiskRuleRegistry
            ├── max_exposure.py   # MaxExposureRule
            ├── max_positions.py  # MaxPositionsRule
            ├── max_drawdown.py   # MaxDrawdownRule
            ├── daily_loss.py     # DailyLossLimitRule
            └── cooldown.py       # CooldownAfterLossRule
```

---

## 4. Boot Sequence

```mermaid
sequenceDiagram
    participant main as main.py
    participant cfg as ConfigManager
    participant disc as discover_asset_timeframes
    participant db as DBPoolManager
    participant rw as RiskWorker
    participant fl as FillListener

    main->>cfg: register_file(risk.yaml, models.yaml)
    main->>disc: discover_asset_timeframes(config_mgr)
    disc-->>main: {BTC: [1m, 5m, 1h], ETH: [...]}
    main->>db: init_db_pools(config_mgr)
    main->>main: _build_risk_engine(risk_config)
    Note over main: Resolves rule names via RiskRuleRegistry.get()
    Note over main: Raises ValueError on unknown rule name
    main->>main: AccountState(initial_balance), PositionTracker()
    loop per asset
        main->>rw: RiskWorker(asset, timeframes, ...)
        main->>rw: connect(redis_client)
        Note over rw: ensure_consumer_group for all signal + price streams
        main->>rw: asyncio.create_task(worker.start())
        main->>fl: FillListener(asset, account, positions)
        main->>fl: connect(redis_client)
        main->>fl: asyncio.create_task(listener.start())
    end
    main->>main: asyncio.gather(*tasks)
    Note over main: BaseException → cancel all tasks → re-raise
```

---

## 5. Signal Processing Flow

### 5.1 Per-bar signal batch pipeline

```mermaid
sequenceDiagram
    participant rv as Valkey
    participant rw as RiskWorker
    participant agg as SignalAggregator
    participant re as RiskEngine
    participant sz as PositionSizer
    participant sl as StopLossCalculator
    participant tp as TakeProfitCalculator
    participant rules as RuleChain

    rw->>rv: XREADGROUP signals:{asset}:{tf} (all TFs, block=1000ms)
    rv-->>rw: messages
    rw->>rw: decode each message → TradeSignal
    rw->>rw: drop signals older than signal_timeout_seconds
    rw->>rw: account.check_daily_reset()
    rw->>agg: aggregate(signals, strategy, tf_weights)
    agg-->>rw: TradeSignal | list[TradeSignal] | None
    loop per aggregated signal
        rw->>re: assess(signal, account, positions, config)
        re->>sz: calculate(strategy, signal, account, config)
        sz-->>re: proposed_size
        re->>sl: calculate(method, signal, sl_config)
        sl-->>re: stop_loss_price
        re->>tp: calculate(method, signal, sl_price, tp_config)
        tp-->>re: take_profit_price
        re->>rules: evaluate(RiskContext) — REJECT short-circuits
        rules-->>re: RiskAssessment
        alt allowed
            rw->>rv: XADD orders:{asset} → OrderExecutionRequest
        else rejected
            rw->>rw: log rejection reason
        end
    end
    rw->>rv: XACK all signal messages (incl. decode failures)
```

### 5.2 MTF conflict resolution strategies

| Strategy | Behaviour | Returns |
|---|---|---|
| `conviction_weighted` | Net direction = sign(Σ direction × conviction × tf_weight). Net conviction = \|weighted_sum\| / Σ weights. | `TradeSignal \| None` |
| `higher_tf_priority` | Take the signal from the highest timeframe (lowest BARS_PER_YEAR). | `TradeSignal` |
| `cancel_on_conflict` | If any two signals disagree on direction, return None. | `TradeSignal \| None` |
| `independent` | Pass all signals through without aggregation — each assessed by RiskEngine separately. | `list[TradeSignal]` |

Default configured in `risk.yaml`: `conviction_weighted`.

### 5.3 Signal staleness filtering

Before aggregation, every signal is age-checked against wall clock:

```
if now - signal.timestamp > signal_timeout_seconds → drop
```

Stale signals (from backpressure or consumer lag) are discarded with a warning log. Configured under `risk.mtf.signal_timeout_seconds` (default: `300`).

---

## 6. Price Heartbeat / SL-TP Flow

```mermaid
sequenceDiagram
    participant rv as Valkey
    participant rw as RiskWorker
    participant pt as PositionTracker

    rw->>rv: XREADGROUP price_update:{asset}:{tf} (block=0, non-blocking)
    rv-->>rw: price messages (or empty)
    loop per price message
        rw->>pt: update_prices(asset, close)
        rw->>pt: update_trailing_stops(asset, close)
        rw->>pt: check_sl_tp_hlc(asset, high, low, close)
        pt-->>rw: list[PositionState] — positions that hit SL or TP
        loop per hit position
            rw->>rv: XADD orders:{asset} → OrderExecutionRequest (market close)
        end
        rw->>rv: XACK price message (only on success)
    end
```

`check_sl_tp_hlc` uses intrabar extremes:
- **Long SL**: triggered if `low ≤ stop_loss_price`
- **Long TP**: triggered if `high ≥ take_profit_price`
- **Short SL**: triggered if `high ≥ stop_loss_price`
- **Short TP**: triggered if `low ≤ take_profit_price`

When both SL and TP are hit on the same bar, TP takes priority.

---

## 7. Fill Listener Flow

```mermaid
sequenceDiagram
    participant rv as Valkey
    participant fl as FillListener
    participant pt as PositionTracker
    participant as as AccountState

    rv->>fl: fills:{asset} (XREADGROUP, group=risk_app_fills_group)
    fl->>fl: decode → ExecutionReport
    alt status != FILLED
        fl->>fl: skip
    else FILLED
        fl->>fl: FIFO match against opposite-direction positions
        loop matched positions
            fl->>as: record_trade_close(pnl, timestamp)
            alt fully closed
                fl->>pt: close_position(asset, index)
            else partially closed
                fl->>pt: reduce pos.size in-place
            end
        end
        alt remaining qty > 0
            fl->>pt: open_position(new PositionState)
        end
    end
    fl->>rv: XACK (inside try — only on success)
```

FillListener uses its own consumer group (`risk_app_fills_group`) independent from `portfolio_app`. Both apps receive every fill independently.

---

## 8. RiskEngine — Rule Chain

```mermaid
flowchart TD
    A[assess(signal)] --> B[PositionSizer.calculate()]
    B --> C[StopLossCalculator.calculate()]
    C --> D[TakeProfitCalculator.calculate()]
    D --> E[Build RiskContext]
    E --> F{Rule 1: evaluate}
    F -- REJECT --> Z[Return RiskAssessment allowed=False]
    F -- MODIFY --> G[Update proposed_size in context]
    F -- ALLOW --> H{Rule 2: evaluate}
    G --> H
    H -- REJECT --> Z
    H -- ... --> I{Rule N: evaluate}
    I -- ALLOW --> J[Return RiskAssessment allowed=True]
```

- `REJECT` short-circuits immediately — remaining rules are not evaluated.
- `MODIFY` updates `proposed_size` in the shared `RiskContext` — downstream rules see the adjusted size.

### 8.1 Registered rules (default order from `risk.yaml`)

| Rule | Config path | Rejects when |
|---|---|---|
| `MaxExposureRule` | `global_limits.max_total_exposure_pct` | Total notional > equity × limit |
| `MaxPositionsRule` | `global_limits.max_concurrent_positions` | Open position count ≥ limit |
| `MaxDrawdownRule` | `global_limits.max_drawdown_pct` | Current drawdown % > limit |
| `DailyLossLimitRule` | `global_limits.daily_loss_limit_pct` | Daily loss % of equity > limit |
| `CooldownAfterLossRule` | `global_limits.cooldown_after_loss_seconds` | Time since last losing trade < cooldown |

---

## 9. Position Sizing Strategies

| Strategy | Formula | Config key |
|---|---|---|
| `fixed_fractional` | `(equity × risk_pct/100) / (price × stop_pct/100)` | `position_sizing.fixed_fractional` |
| `volatility_scaled` | `(equity × target_risk_pct/100) / (ATR × atr_multiplier)` | `position_sizing.volatility_scaled` |
| `kelly` | `fraction × (win_rate − (1−win_rate)/rr) × equity / price` | `position_sizing.kelly` |
| `equal_weight` | `equity / (max_positions × price)` | `position_sizing.equal_weight` |

`volatility_scaled` and `kelly` fall back to `fixed_fractional` when required metadata (`ATR`, `win_rate`, `rr_ratio`) is absent.

---

## 10. Stop-Loss and Take-Profit Methods

### Stop-loss methods

| Method | Formula | Notes |
|---|---|---|
| `atr_based` | Long: `price − ATR × multiplier` / Short: `price + ATR × multiplier` | Falls back to None if ATR missing |
| `fixed_pct` | Long: `price × (1 − pct/100)` / Short: `price × (1 + pct/100)` | Always produces a value |
| `trailing` | Same initial formula as `atr_based`; PositionTracker updates it per bar | Trailing updates via `update_trailing_stops()` |

### Take-profit methods

| Method | Formula | Notes |
|---|---|---|
| `risk_reward` | `sl_distance × ratio` from entry | Requires a valid SL price; returns None if SL is None |
| `fixed_pct` | Long: `price × (1 + pct/100)` / Short: `price × (1 − pct/100)` | Always produces a value |
| `trailing` | Same initial formula as ATR-based; PositionTracker updates it per bar | |

---

## 11. Configuration Reference (`risk.yaml`)

```yaml
risk:
  account:
    initial_balance: 10000      # Starting paper balance (USDT)
    currency: USDT
    leverage_limit: 5.0

  global_limits:
    max_total_exposure_pct: 80  # % of equity
    max_concurrent_positions: 10
    max_drawdown_pct: 15        # % from peak equity
    daily_loss_limit_pct: 5     # % of equity
    cooldown_after_loss_seconds: 0

  rules:                        # Evaluated in order; first REJECT wins
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
    default_method: fixed_pct
    risk_reward:
      ratio: 2.0
    fixed_pct:
      pct: 1.5
    trailing:
      atr_multiplier: 3.0

  mtf:
    default_conflict_resolution: conviction_weighted
    signal_timeout_seconds: 300  # Drop signals older than this (wall clock)
    timeframe_weights:
      1m: 0.25
      5m: 0.5
      15m: 0.75
      1h: 1.0
      4h: 1.5
      1d: 2.0
```

---

## 12. Error Handling

| Scenario | Behaviour |
|---|---|
| Price update processing exception | Logged at ERROR level; message stays in PEL (not acked) — retried on next boot via `XAUTOCLAIM` |
| Signal decode failure | Logged at ERROR level; message acked (corrupt bytes are unrecoverable) |
| Signal too old (`> signal_timeout_seconds`) | Warning logged; signal dropped before aggregation |
| MTF aggregation cancels (conflict/neutral) | Debug logged; no order published |
| Signal REJECTED by rule | Info logged with rule name + reason; no order published |
| Unknown sizing strategy | Warning logged; falls back to `fixed_fractional` |
| ATR missing for `volatility_scaled` sizing | Debug logged; falls back to `fixed_fractional` |
| SL price None for `risk_reward` TP | None returned; no take-profit attached to order |
| Boot with unknown rule name in config | Raises `ValueError` — app refuses to start |
| Worker or listener task crash | `BaseException` handler cancels all peer tasks before re-raising; `redis_client.aclose()` + `DBPoolManager.close_pools()` always called in `finally` |
| Consumer group already exists | Silently ignored (`BUSYGROUP` exception swallowed by `ensure_consumer_group`) |

---

## 13. Known Gaps / Future Work

| Gap | Description |
|---|---|
| **State not recovered on restart** | `AccountState` and `PositionTracker` always initialize fresh. `load_positions()` and `AccountState.load_latest()` exist but are not called at startup. After crash/redeploy: open positions are invisible to risk rules, SL/TP won't fire, daily PnL resets to zero. Requires deliberate recovery strategy before enabling in production. |
| **No `/risk/status` API endpoint** | Unlike `ingestion_app` and `signal_app`, there is no observability endpoint for current positions, account equity, or drawdown. |
| **`AccountState.update_unrealized` not called periodically** | Unrealized PnL is only updated when fills arrive. Between fills, `equity` and `current_drawdown_pct` may be stale, causing `MaxDrawdownRule` and `DailyLossLimitRule` to evaluate against outdated figures. |
