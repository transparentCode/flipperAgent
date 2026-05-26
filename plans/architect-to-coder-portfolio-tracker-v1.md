---
goal: Implement Portfolio Tracker as an analytics/observability layer providing equity curves, PnL attribution, performance metrics, position summaries, and trade journal — reusing existing persisted state
stage: architect-to-coder
date_created: 2026-05-26
last_updated: 2026-05-26
owner: Quant Research Architect
status: Ready
tags: [handoff, quant, portfolio, analytics, observability, metrics]
source_agent: Quant Research Architect
target_agent: Coder Agent
---

# Portfolio Tracker — Architect-to-Coder Handoff

## Objective

Build a Portfolio Tracker module that provides analytics and observability for the flipperAgent trading pipeline. It is **not** in the critical trading path — it reads from existing DB tables and Valkey streams to compute equity curves, PnL attribution, performance metrics, position summaries, and a trade journal.

The module must be usable in two modes:
1. **Live mode** — an app (`portfolio_app`) subscribes to Valkey streams and updates analytics in near real-time.
2. **Offline/backtest mode** — library code (`libs/portfolio/`) queries the DB directly and returns computed results.

---

## Locked-In Decisions

| Decision | Choice |
|---|---|
| Library location | `src/libs/portfolio/` |
| App location | `src/apps/portfolio_app/` |
| Config file | `configs/portfolio.yaml` |
| SystemComponent enum | `PORTFOLIO_TRACKER` |
| DB engine | TimescaleDB (consistent with rest of pipeline) |
| Primary data sources | `risk_account_snapshots`, `risk_positions`, `execution_fills` DB tables |
| Live stream source | `fills:{asset}` Valkey stream (read-only, own consumer group) |
| Schema reuse | Reuse `AccountSnapshot`, `PositionState`, `ExecutionReport`, `OrderFill` — do NOT duplicate |
| New schemas | `ClosedTrade`, `TradeJournalEntry`, `PnLAttribution`, `PerformanceSummary`, `EquityPoint`, `PortfolioSnapshot`, `ExposurePoint`, `BenchmarkComparison` |
| Metric computation | Pure functions operating on regular-interval return series — no side effects |
| Return series | Equity curve resampled to fixed intervals (configurable, default 1h for 24/7 crypto) before computing any ratio |
| Benchmark | BTC buy-and-hold as default benchmark; alpha, beta, information ratio computed via OLS regression |
| MAE/MFE | Track per-trade max adverse/favorable excursion for SL/TP optimization feedback |
| Exposure tracking | Net/gross exposure as % of equity tracked over time |
| No `apps/` imports | `libs/portfolio/` must NOT import from `apps/` |
| Config pattern | `ConfigManager` from `libs.common.config` — no `os.getenv()` |
| Logging pattern | `bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)` |

---

## Scope Boundaries

### In Scope
- `src/libs/portfolio/` — core analytics logic (metrics, attribution, trade journal, equity curve)
- `src/apps/portfolio_app/` — persistent Valkey consumer that updates analytics tables
- `configs/portfolio.yaml` — portfolio tracker configuration
- New Pydantic schemas in `src/libs/contracts/schemas.py`
- `src/libs/common/enums.py` — add `PORTFOLIO_TRACKER` to `SystemComponent`
- New TimescaleDB tables: `portfolio_equity_curve`, `portfolio_closed_trades`
- Tests under `tests/portfolio/`

### Explicit Non-Goals
- Dashboard / UI / REST API (future concern)
- Alerting / notification system
- Real-time WebSocket feed to external consumers
- Modifying any existing pipeline app (ingestion, signal, strategy, risk, execution) — EXCEPT Step 0 prerequisite (adding model_name/timeframe to OrderExecutionRequest)
- Modifying existing DB tables
- Alembic migrations (schema definition only)
- Optimization / parameter tuning integration
- Live P&L streaming to external systems

---

## Architecture Overview

```
                    ┌─────────────────────────────────┐
                    │        Trading Pipeline          │
                    │  Ingestion → Signal → Strategy   │
                    │  → Risk → Execution → Fill       │
                    └──────────┬──────────────────────┘
                               │
                    fills:{asset} stream
                               │
                    ┌──────────▼──────────────────────┐
                    │     portfolio_app                 │
                    │  PortfolioWorker (per asset)      │
                    │  - listens fills:{asset}          │
                    │  - builds ClosedTrade records     │
                    │  - persists to portfolio_closed_  │
                    │    trades table                   │
                    │  - snapshots equity curve points  │
                    └──────────┬──────────────────────┘
                               │
                    ┌──────────▼──────────────────────┐
                    │     libs/portfolio/               │
                    │  MetricsCalculator (pure funcs)   │
                    │  ReturnsBuilder (resample→grid)   │
                    │  BenchmarkAnalyzer (α,β,IR)       │
                    │  PnLAttributor                    │
                    │  TradeJournal                     │
                    │  EquityCurveBuilder               │
                    └─────────────────────────────────┘
```

The `portfolio_app` is an **observer** — it never publishes back to any trading stream. The `libs/portfolio/` modules are pure computation and DB query helpers usable from any context (live app, CLI, notebook, backtest harness).

---

## Affected Symbols, Modules, and Execution Flows

### New Files

```
src/libs/portfolio/
├── __init__.py
├── metrics.py             # MetricsCalculator — Sharpe, Sortino, drawdown, win rate, etc.
├── returns.py             # ReturnsBuilder — resample equity curve to fixed-interval return series
├── benchmark.py           # BenchmarkAnalyzer — alpha, beta, information ratio vs benchmark
├── attribution.py         # PnLAttributor — break down PnL by asset, model, timeframe
├── trade_journal.py       # TradeJournal — query and build trade history from DB
├── equity_curve.py        # EquityCurveBuilder — build equity time-series from snapshots

src/apps/portfolio_app/
├── __init__.py
├── main.py                # Entrypoint — discovers assets, spawns PortfolioWorkers
├── portfolio_worker.py    # Valkey consumer — listens fills:{asset}, writes closed trades + equity points

configs/portfolio.yaml

tests/portfolio/
├── __init__.py
├── test_metrics.py
├── test_returns.py
├── test_benchmark.py
├── test_attribution.py
├── test_trade_journal.py
├── test_equity_curve.py
├── test_portfolio_worker.py
```

### Modified Files

| File | Change |
|---|---|
| `src/libs/contracts/schemas.py` | Add `ClosedTrade`, `TradeJournalEntry`, `PnLAttribution`, `PerformanceSummary`, `EquityPoint`, `PortfolioSnapshot`, `ExposurePoint`, `BenchmarkComparison` |
| `src/libs/common/enums.py` | Add `PORTFOLIO_TRACKER` to `SystemComponent` |
| `src/libs/contracts/schemas.py` (OrderExecutionRequest) | Add `model_name`, `source_timeframe` optional fields (Step 0 prerequisite) |
| `src/apps/risk_app/risk_worker.py` | Pass `model_name` and `timeframe` into OrderExecutionRequest (Step 0) |

### Not Changed
- All trading pipeline apps (ingestion, signal, strategy, risk, execution) — except Step 0 minor additions
- All existing `libs/` modules (risk, execution, features, models, etc.)
- All existing configs (base.yaml, risk.yaml, execution.yaml, models.yaml, features.yaml, optimization.yaml)
- All existing DB tables (risk_account_snapshots, risk_positions, execution_fills)

---

## Data Contracts / Interfaces

### 0. Step 0 Prerequisite — Propagate model_name/timeframe through execution chain

Add to `OrderExecutionRequest`:
```python
class OrderExecutionRequest(BaseModel):
    # ... existing fields ...
    model_name: str = Field(default="", description="Model that generated the original signal")
    source_timeframe: str = Field(default="", description="Timeframe of the original signal")
```

Update `RiskWorker` order construction to pass signal's model_name and timeframe:
```python
order = OrderExecutionRequest(
    # ... existing fields ...
    model_name=signal.model_name,
    source_timeframe=signal.timeframe,
)
```

Update `ExecutionWorker._decode_order()` to parse these new fields.
Update `ExecutionWorker._encode_report()` — the `ExecutionReport.metadata` dict should include `model_name` and `timeframe` from the order.

### 1. New Enum Value (`libs/common/enums.py`)

```python
class SystemComponent(str, Enum):
    # ... existing values ...
    PORTFOLIO_TRACKER = "PORTFOLIO_TRACKER"
```

### 2. New Schemas (`libs/contracts/schemas.py`)

```python
# ---------------------------------------------------------------------------
# Portfolio Tracker Contracts
# ---------------------------------------------------------------------------

class ClosedTrade(BaseModel):
    """A fully closed trade with entry and exit details."""
    trade_id: str = Field(..., description="Unique trade identifier (UUID)")
    asset: str
    direction: int = Field(..., description="1 for long, -1 for short")
    entry_price: float
    exit_price: float
    size: float
    realized_pnl: float
    realized_pnl_pct: float = Field(..., description="PnL as % of entry notional")
    commission_total: float = Field(default=0.0)
    slippage_bps: float = Field(default=0.0)
    entry_timestamp: float
    exit_timestamp: float
    duration_seconds: float
    source_model: str = Field(default="")
    source_timeframe: str = Field(default="")
    entry_order_id: str = Field(default="")
    exit_order_id: str = Field(default="")
    # MAE/MFE for SL/TP optimization
    mae_pct: float = Field(default=0.0, description="Max Adverse Excursion as % of entry notional")
    mfe_pct: float = Field(default=0.0, description="Max Favorable Excursion as % of entry notional")


class TradeJournalEntry(BaseModel):
    """Enriched view of a closed trade for journaling."""
    trade: ClosedTrade
    equity_at_entry: float = Field(default=0.0, description="Account equity when trade was opened")
    equity_at_exit: float = Field(default=0.0, description="Account equity when trade was closed")
    drawdown_at_entry_pct: float = Field(default=0.0)
    risk_reward_achieved: float = Field(default=0.0, description="Actual R:R = |PnL| / |risk taken|")


class PnLAttribution(BaseModel):
    """PnL breakdown by a grouping dimension."""
    group_key: str = Field(..., description="e.g. 'BTCUSDT', 'TrendFollowingModel', '4h'")
    group_type: str = Field(..., description="'asset', 'model', or 'timeframe'")
    total_pnl: float
    trade_count: int
    win_count: int
    loss_count: int
    avg_pnl: float
    max_win: float
    max_loss: float
    pnl_pct_of_total: float = Field(default=0.0, description="This group's share of total PnL")


class PerformanceSummary(BaseModel):
    """Aggregate performance metrics over a period."""
    start_timestamp: float
    end_timestamp: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float = Field(..., description="winning_trades / total_trades")
    total_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: float = Field(..., description="gross_profit / abs(gross_loss) or inf if no losses")
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade_duration_seconds: float
    max_drawdown_pct: float
    max_drawdown_duration_seconds: float
    sharpe_ratio: float = Field(default=0.0, description="Annualized, from equity returns")
    sortino_ratio: float = Field(default=0.0, description="Annualized, downside deviation")
    calmar_ratio: float = Field(default=0.0, description="Annual return / max drawdown")
    expectancy: float = Field(default=0.0, description="(win_rate * avg_win) - (loss_rate * avg_loss)")
    payoff_ratio: float = Field(default=0.0, description="avg_win / abs(avg_loss)")
    # Benchmark-relative metrics
    alpha: float = Field(default=0.0, description="Jensen's alpha vs benchmark")
    beta: float = Field(default=0.0, description="Portfolio beta vs benchmark")
    information_ratio: float = Field(default=0.0, description="Active return / tracking error")
    tracking_error: float = Field(default=0.0, description="Std dev of active returns, annualized")


class EquityPoint(BaseModel):
    """Single point on the equity curve time-series."""
    timestamp: float
    equity: float
    balance: float
    unrealized_pnl: float
    drawdown_pct: float
    open_position_count: int


class PortfolioSnapshot(BaseModel):
    """Full portfolio state at a point in time."""
    timestamp: float
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    open_positions: list[PositionState] = Field(default_factory=list)
    performance: PerformanceSummary | None = None
    attribution_by_asset: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_model: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_timeframe: list[PnLAttribution] = Field(default_factory=list)


class ExposurePoint(BaseModel):
    """Net/gross exposure at a point in time."""
    timestamp: float
    net_exposure_pct: float = Field(..., description="(long_notional - short_notional) / equity * 100")
    gross_exposure_pct: float = Field(..., description="(long_notional + short_notional) / equity * 100")
    long_exposure_pct: float = Field(default=0.0)
    short_exposure_pct: float = Field(default=0.0)


class BenchmarkComparison(BaseModel):
    """Strategy vs benchmark performance comparison."""
    benchmark_name: str = Field(default="BTC_BUY_HOLD")
    strategy_return_pct: float
    benchmark_return_pct: float
    alpha: float = Field(..., description="Jensen's alpha (annualized)")
    beta: float = Field(..., description="OLS regression slope")
    correlation: float = Field(default=0.0)
    information_ratio: float = Field(default=0.0)
    tracking_error: float = Field(default=0.0, description="Annualized std of active returns")
    start_timestamp: float
    end_timestamp: float
```

---

## DB Tables (TimescaleDB)

### Table 1: `portfolio_equity_curve`

Stores periodic equity snapshots for time-series analysis. Populated by `PortfolioWorker` after each fill, and also queryable in batch from `risk_account_snapshots`.

```sql
CREATE TABLE IF NOT EXISTS portfolio_equity_curve (
    timestamp      DOUBLE PRECISION NOT NULL,
    equity         DOUBLE PRECISION NOT NULL,
    balance        DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL,
    drawdown_pct   DOUBLE PRECISION NOT NULL,
    open_position_count INTEGER NOT NULL DEFAULT 0,
    net_exposure_pct    DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    gross_exposure_pct  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    PRIMARY KEY (timestamp)
);

-- Convert to TimescaleDB hypertable
SELECT create_hypertable('portfolio_equity_curve', 'timestamp',
                          chunk_time_interval => 86400);
```

### Table 2: `portfolio_closed_trades`

Immutable log of every closed trade with full entry/exit details and attribution metadata.

```sql
CREATE TABLE IF NOT EXISTS portfolio_closed_trades (
    trade_id           TEXT PRIMARY KEY,
    asset              TEXT NOT NULL,
    direction          INTEGER NOT NULL,
    entry_price        DOUBLE PRECISION NOT NULL,
    exit_price         DOUBLE PRECISION NOT NULL,
    size               DOUBLE PRECISION NOT NULL,
    realized_pnl       DOUBLE PRECISION NOT NULL,
    realized_pnl_pct   DOUBLE PRECISION NOT NULL,
    commission_total   DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    slippage_bps       DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    entry_timestamp    DOUBLE PRECISION NOT NULL,
    exit_timestamp     DOUBLE PRECISION NOT NULL,
    duration_seconds   DOUBLE PRECISION NOT NULL,
    source_model       TEXT NOT NULL DEFAULT '',
    source_timeframe   TEXT NOT NULL DEFAULT '',
    entry_order_id     TEXT NOT NULL DEFAULT '',
    exit_order_id      TEXT NOT NULL DEFAULT '',
    mae_pct            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    mfe_pct            DOUBLE PRECISION NOT NULL DEFAULT 0.0
);

-- Index for attribution queries
CREATE INDEX IF NOT EXISTS idx_closed_trades_asset ON portfolio_closed_trades (asset);
CREATE INDEX IF NOT EXISTS idx_closed_trades_model ON portfolio_closed_trades (source_model);
CREATE INDEX IF NOT EXISTS idx_closed_trades_timeframe ON portfolio_closed_trades (source_timeframe);
CREATE INDEX IF NOT EXISTS idx_closed_trades_exit_ts ON portfolio_closed_trades (exit_timestamp);
```

Note: `portfolio_closed_trades` is NOT a hypertable — it's keyed by `trade_id` (UUID), not time. The `exit_timestamp` index supports time-range queries for journal and attribution.

---

## Config Structure (`configs/portfolio.yaml`)

```yaml
portfolio:
  # Equity curve snapshot interval (seconds).
  # In live mode, a snapshot is also taken on every fill.
  snapshot_interval_seconds: 300

  # Regular-interval return series (industry standard)
  returns:
    # Resample interval for return computation (seconds)
    # 3600 = 1h (recommended for 24/7 crypto markets)
    resample_interval_seconds: 3600
    # Minimum points for valid ratio computation
    min_points: 24

  # Benchmark comparison
  benchmark:
    # Benchmark asset for alpha/beta computation
    asset: BTCUSDT
    # Strategy: buy_hold (default) or custom
    strategy: buy_hold

  # Performance metrics
  metrics:
    # Risk-free rate for Sharpe/Sortino (annualized, decimal)
    risk_free_rate: 0.0
    # Trading days per year for annualization
    trading_days_per_year: 365
    # Minimum trades before computing ratios (avoids divide-by-zero noise)
    min_trades_for_ratios: 5

  # Equity curve
  equity_curve:
    # Max points to return in a single query (for memory safety)
    max_points: 10000

  # Trade journal
  trade_journal:
    # Default page size when querying closed trades
    default_page_size: 100
    max_page_size: 1000

  # Consumer group config for live mode
  consumer:
    group_name: portfolio_app_fills_group
    batch_size: 10
    block_ms: 2000
    # Periodic DB snapshot interval (seconds) independent of fills
    periodic_snapshot_seconds: 60
```

---

## Component Specifications

### A. MetricsCalculator (`libs/portfolio/metrics.py`)

Pure-function module. No state, no DB access, no side effects. All ratio metrics (Sharpe, Sortino, Calmar) operate on a **regular-interval return series** produced by `returns.py`, NOT on raw irregularly-spaced equity points. Trade-level stats operate on `ClosedTrade` lists.

```python
from __future__ import annotations

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    PerformanceSummary,
)

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def compute_performance(
    trades: list[ClosedTrade],
    returns: list[float],
    equity_curve: list[EquityPoint],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
    min_trades_for_ratios: int = 5,
) -> PerformanceSummary:
    """Compute aggregate performance metrics.

    Args:
        trades: List of closed trades for trade-level stats.
        returns: Regular-interval log returns from ReturnsBuilder.
        equity_curve: Equity points for drawdown computation.
        periods_per_year: Number of return intervals per year (8760 for hourly, 365 for daily).
    """
    ...


def compute_sharpe(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> float:
    """Annualized Sharpe ratio from regular-interval return series.

    sharpe = (mean_excess_return / std_return) * sqrt(periods_per_year)
    where excess_return = return - (risk_free_rate / periods_per_year)
    Returns 0.0 if fewer than 2 returns or zero std dev.
    """
    ...


def compute_sortino(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> float:
    """Annualized Sortino ratio from regular-interval return series.

    sortino = (mean_excess_return / downside_deviation) * sqrt(periods_per_year)
    Downside deviation uses only negative excess returns.
    Returns 0.0 if fewer than 2 returns or zero downside deviation.
    """
    ...


def compute_max_drawdown(
    equity_points: list[EquityPoint],
) -> tuple[float, float]:
    """Returns (max_drawdown_pct, max_drawdown_duration_seconds).

    max_drawdown_pct is the largest peak-to-trough decline as a percentage.
    max_drawdown_duration_seconds is the longest time spent below a prior peak.
    """
    ...


def compute_calmar(
    returns: list[float],
    equity_points: list[EquityPoint],
    periods_per_year: int = 8760,
) -> float:
    """Calmar ratio = annualized return / max drawdown pct.

    Annualized return computed from compounding regular-interval returns.
    Returns 0.0 if max drawdown is 0 or curve is too short.
    """
    ...


def compute_trade_stats(
    trades: list[ClosedTrade],
) -> dict[str, float]:
    """Compute win_rate, profit_factor, expectancy, payoff_ratio, avg_duration.

    Returns dict with keys matching PerformanceSummary field names.
    """
    ...


def compute_rolling_sharpe(
    returns: list[float],
    timestamps: list[float],
    window_periods: int,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> list[tuple[float, float]]:
    """Rolling Sharpe ratio over a sliding window.

    Returns list of (timestamp, sharpe) tuples.
    Window slides by 1 period each step.
    """
    ...
```

**Implementation notes:**
- All ratio functions accept `returns: list[float]` (regular-interval log returns from `ReturnsBuilder`).
- `periods_per_year`: 8760 for hourly (365*24), 365 for daily. Driven by config `resample_interval_seconds`.
- Sharpe: `(mean(excess_returns) / std(returns)) * sqrt(periods_per_year)`.
- Sortino: same but denominator is `sqrt(mean(min(0, excess_return)^2))`.
- Calmar: `(compound_annual_return) / max_drawdown_pct`. Compound: `(final/initial)^(periods_per_year/n_periods) - 1`.
- `profit_factor = gross_profit / abs(gross_loss)`. If `gross_loss == 0`, return `float('inf')`.
- `expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)`.
- `payoff_ratio = avg_win / abs(avg_loss)`. If `avg_loss == 0`, return `float('inf')`.
- Use `math.log` for log returns, `math.sqrt` for annualization.

### A2. ReturnsBuilder (`libs/portfolio/returns.py`)

Resamples irregularly-spaced equity curve to fixed-interval return series. This is the **critical industry-standard step** that makes all ratio metrics mathematically correct.

```python
from __future__ import annotations

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import EquityPoint

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def resample_equity_curve(
    equity_points: list[EquityPoint],
    interval_seconds: int = 3600,
) -> list[EquityPoint]:
    """Resample irregular equity points to a fixed-interval time grid.

    Uses forward-fill (last observation carried forward) for intervals
    with no equity change. Drops leading intervals before first observation.

    Args:
        equity_points: Raw equity curve (irregular timestamps), sorted ASC.
        interval_seconds: Target interval (3600=hourly, 86400=daily).

    Returns: List of EquityPoint at regular intervals.
    """
    ...


def compute_log_returns(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Compute log returns from resampled (fixed-interval) equity points.

    return_i = ln(equity_i / equity_{i-1})
    Returns list of length len(resampled_points) - 1.
    Skips any interval where previous equity is <= 0.
    """
    ...


def compute_simple_returns(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Compute simple returns: (equity_i - equity_{i-1}) / equity_{i-1}.

    Returns list of length len(resampled_points) - 1.
    """
    ...


def get_return_timestamps(
    resampled_points: list[EquityPoint],
) -> list[float]:
    """Get timestamps corresponding to each return (uses the later point's timestamp).

    Returns list of length len(resampled_points) - 1.
    """
    ...
```

**Implementation notes:**
- Grid construction: `start = first_point.timestamp`, generate `start + i * interval_seconds` up to last point.
- Forward-fill: for each grid point, use the last equity point with `timestamp <= grid_time`.
- Log returns: `math.log(equity[i] / equity[i-1])`. Guard against zero/negative equity.
- This module has NO DB access — it operates on in-memory lists.

### A3. BenchmarkAnalyzer (`libs/portfolio/benchmark.py`)

Computes alpha, beta, information ratio, and tracking error vs a benchmark return series.

```python
from __future__ import annotations

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import BenchmarkComparison

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def compute_benchmark_comparison(
    strategy_returns: list[float],
    benchmark_returns: list[float],
    periods_per_year: int = 8760,
    start_timestamp: float = 0.0,
    end_timestamp: float = 0.0,
    benchmark_name: str = "BTC_BUY_HOLD",
) -> BenchmarkComparison:
    """Compare strategy returns vs benchmark returns.

    Both return series must be aligned (same length, same time grid).

    Computes:
        alpha: Jensen's alpha = mean(strategy - rf) - beta * mean(benchmark - rf)
        beta: OLS slope of strategy_returns ~ benchmark_returns
        correlation: Pearson correlation
        information_ratio: mean(active_returns) / std(active_returns) * sqrt(periods_per_year)
        tracking_error: std(active_returns) * sqrt(periods_per_year)

    Returns BenchmarkComparison with all fields.
    Returns zeroed comparison if fewer than 2 aligned returns.
    """
    ...


def build_benchmark_returns(
    benchmark_prices: list[tuple[float, float]],
    interval_seconds: int = 3600,
) -> list[float]:
    """Build benchmark return series from price data.

    Args:
        benchmark_prices: List of (timestamp, price) tuples, sorted ASC.
        interval_seconds: Same interval as strategy returns.

    Resamples to grid, computes log returns. Same logic as ReturnsBuilder
    but operates on raw prices rather than equity points.
    """
    ...
```

**Implementation notes:**
- Beta via OLS: `beta = cov(strategy, benchmark) / var(benchmark)`. Use manual computation (no numpy dependency).
- Alpha (Jensen's): `alpha = mean(strategy_excess) - beta * mean(benchmark_excess)`. Annualize: `alpha * periods_per_year`.
- Information ratio: `IR = mean(active_returns) / std(active_returns) * sqrt(periods_per_year)` where `active = strategy - benchmark`.
- Tracking error: `TE = std(active_returns) * sqrt(periods_per_year)`.
- Correlation: `cov(s,b) / (std(s) * std(b))`.
- All computations use stdlib `math` + manual variance/covariance — no external dependencies.

### B. PnLAttributor (`libs/portfolio/attribution.py`)

Grouping and attribution logic over closed trades.

```python
from __future__ import annotations

from typing import Literal

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ClosedTrade, PnLAttribution

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)

GroupByDimension = Literal["asset", "model", "timeframe"]


def attribute_pnl(
    trades: list[ClosedTrade],
    group_by: GroupByDimension,
) -> list[PnLAttribution]:
    """Group closed trades by dimension and compute per-group PnL stats.

    group_by:
        "asset"     -> groups by trade.asset
        "model"     -> groups by trade.source_model
        "timeframe" -> groups by trade.source_timeframe

    Returns a list of PnLAttribution, one per unique group key,
    sorted descending by total_pnl.
    """
    ...
```

**Implementation notes:**
- Group key extraction: `{"asset": t.asset, "model": t.source_model, "timeframe": t.source_timeframe}[group_by]`.
- For each group: count wins (pnl > 0), losses (pnl <= 0), sum pnl, find max win/loss, compute avg.
- `pnl_pct_of_total`: this group's `total_pnl / sum(all groups total_pnl) * 100`. Handle zero total gracefully.

### C. TradeJournal (`libs/portfolio/trade_journal.py`)

DB query helper for closed trades. Reads from `portfolio_closed_trades` and `risk_account_snapshots` tables.

```python
from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import ClosedTrade, TradeJournalEntry

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class TradeJournal:
    """Query closed trades from DB and enrich with equity context."""

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    async def get_closed_trades(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ClosedTrade]:
        """Query portfolio_closed_trades with optional filters.

        Filters are ANDed. Results ordered by exit_timestamp DESC.
        """
        ...

    async def get_journal_entries(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeJournalEntry]:
        """Get closed trades enriched with equity context.

        For each ClosedTrade, looks up the nearest AccountSnapshot at entry
        and exit time from risk_account_snapshots to populate equity_at_entry,
        equity_at_exit, and drawdown_at_entry_pct.

        risk_reward_achieved = |realized_pnl| / |risk_taken| where risk_taken
        is |entry_price - stop_loss_price| * size if stop_loss was set, else
        uses entry notional * 0.02 as a fallback.
        """
        ...

    async def get_trade_count(
        self,
        asset: str | None = None,
        model: str | None = None,
        timeframe: str | None = None,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> int:
        """Return count of closed trades matching filters."""
        ...

    async def save_closed_trade(self, trade: ClosedTrade) -> None:
        """Persist a ClosedTrade to portfolio_closed_trades.

        Uses ON CONFLICT (trade_id) DO NOTHING for idempotency.
        """
        ...
```

**Implementation notes:**
- Build WHERE clause dynamically from non-None filters. Use parameterized queries (never f-strings for SQL values).
- For `get_journal_entries`, use a subquery or lateral join to find the nearest `risk_account_snapshots` row by timestamp for each trade's entry/exit time:
  ```sql
  SELECT * FROM risk_account_snapshots
  WHERE timestamp <= $target_ts ORDER BY timestamp DESC LIMIT 1
  ```
- If no snapshot exists near the trade time, leave `equity_at_entry`/`equity_at_exit` as 0.0.

### D. EquityCurveBuilder (`libs/portfolio/equity_curve.py`)

Builds equity time-series from DB snapshots.

```python
from __future__ import annotations

from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import EquityPoint

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class EquityCurveBuilder:
    """Build and query equity curve time-series."""

    def __init__(self, db_pool: Any) -> None:
        self.db_pool = db_pool

    async def get_equity_curve(
        self,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
        max_points: int = 10000,
    ) -> list[EquityPoint]:
        """Query portfolio_equity_curve table for equity time-series.

        If the number of rows exceeds max_points, downsample using
        TimescaleDB time_bucket or simple striding.
        Results ordered by timestamp ASC.
        """
        ...

    async def save_equity_point(self, point: EquityPoint) -> None:
        """Persist a single equity point.

        Uses ON CONFLICT (timestamp) DO UPDATE to overwrite stale snapshots.
        """
        ...

    async def build_from_account_snapshots(
        self,
        start_timestamp: float | None = None,
        end_timestamp: float | None = None,
    ) -> list[EquityPoint]:
        """Build equity curve from existing risk_account_snapshots table.

        This is the offline/backtest path — reads from risk_account_snapshots
        (already populated by AccountState.save_snapshot) and converts to
        EquityPoint objects. Does NOT write to portfolio_equity_curve.

        Useful for backtesting or when portfolio_app was not running.
        """
        ...
```

**Implementation notes:**
- `build_from_account_snapshots` maps `AccountSnapshot` DB rows to `EquityPoint` objects (the fields are a subset).
- For downsampling, prefer `SELECT * FROM portfolio_equity_curve WHERE ... ORDER BY timestamp ASC` and stride with `LIMIT max_points` using a subquery with `ROW_NUMBER()` if the count exceeds `max_points`. If TimescaleDB `time_bucket` is available, use it for cleaner downsampling.
- `save_equity_point` SQL:
  ```sql
  INSERT INTO portfolio_equity_curve
      (timestamp, equity, balance, unrealized_pnl, drawdown_pct, open_position_count)
  VALUES ($1, $2, $3, $4, $5, $6)
  ON CONFLICT (timestamp) DO UPDATE SET
      equity = EXCLUDED.equity,
      balance = EXCLUDED.balance,
      unrealized_pnl = EXCLUDED.unrealized_pnl,
      drawdown_pct = EXCLUDED.drawdown_pct,
      open_position_count = EXCLUDED.open_position_count
  ```

### E. PortfolioWorker (`apps/portfolio_app/portfolio_worker.py`)

Per-asset Valkey consumer. Listens to `fills:{asset}` with its own consumer group (separate from `risk_app`'s consumer group). Builds `ClosedTrade` records and writes equity snapshots.

```python
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    ExecutionReport,
    OrderStatus,
    PositionState,
)
from libs.portfolio.equity_curve import EquityCurveBuilder
from libs.portfolio.trade_journal import TradeJournal

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


class PortfolioWorker:
    """Consumes fills:{asset} and maintains portfolio analytics tables."""

    def __init__(
        self,
        asset: str,
        db_pool: Any,
        config_mgr: ConfigManager,
    ) -> None:
        self.asset = asset
        self.db_pool = db_pool
        self.config_mgr = config_mgr

        portfolio_cfg = config_mgr.get("portfolio", {})
        consumer_cfg = portfolio_cfg.get("consumer", {})

        self.fill_stream_key = f"fills:{asset}"
        self.group_name = consumer_cfg.get("group_name", "portfolio_app_fills_group")
        self.consumer_name = f"portfolio_worker_{asset}"
        self.batch_size = consumer_cfg.get("batch_size", 10)
        self.block_ms = consumer_cfg.get("block_ms", 2000)

        self.trade_journal = TradeJournal(db_pool)
        self.equity_builder = EquityCurveBuilder(db_pool)

        # Local position tracking (read-only mirror for building ClosedTrade records)
        # Each entry is (PositionState, mae_price, mfe_price) for MAE/MFE tracking
        self._open_positions: list[PositionState] = []
        self._position_watermarks: dict[int, dict[str, float]] = {}  # id(pos) -> {"worst_price": ..., "best_price": ...}
        self.redis_client: Any = None

    async def connect(self, redis_client: Any) -> None:
        """Store client and create consumer group."""
        self.redis_client = redis_client
        try:
            await self.redis_client.xgroup_create(
                self.fill_stream_key, self.group_name, id="0", mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create group: {e}")

    async def start(self) -> None:
        """Main loop — consume fills, build trade records, snapshot equity."""
        logger.info(f"Starting portfolio worker for {self.asset}")
        if not self.redis_client:
            logger.warning("No redis client — portfolio worker inactive")
            return

        streams = {self.fill_stream_key: ">"}

        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    streams,
                    count=self.batch_size,
                    block=self.block_ms,
                )
                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        try:
                            report = self._decode_report(payload)
                            await self._process_fill(report)
                        except Exception as e:
                            logger.error(f"Failed to process fill: {e}", exc_info=True)

                        sname = (
                            stream_name.decode("utf-8")
                            if isinstance(stream_name, bytes)
                            else stream_name
                        )
                        await self.redis_client.xack(
                            sname, self.group_name, message_id,
                        )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Portfolio worker error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _process_fill(self, report: ExecutionReport) -> None:
        """Process a single fill — update local positions, detect closes, write to DB."""
        if report.status != OrderStatus.FILLED:
            return

        if report.side == "buy":
            pos = PositionState(
                asset=report.asset,
                direction=1,
                entry_price=report.average_fill_price,
                current_price=report.average_fill_price,
                size=report.filled_size,
                unrealized_pnl=0.0,
                entry_timestamp=report.timestamp,
                source_model=report.metadata.get("model_name", ""),
                source_timeframe=report.metadata.get("timeframe", ""),
                stop_loss_price=report.stop_loss_price,
                take_profit_price=report.take_profit_price,
            )
            self._open_positions.append(pos)
            # Init MAE/MFE watermarks
            self._position_watermarks[id(pos)] = {
                "worst_price": report.average_fill_price,
                "best_price": report.average_fill_price,
            }

        elif report.side == "sell":
            # FIFO match against open longs
            matched_idx: int | None = None
            for i, pos in enumerate(self._open_positions):
                if pos.direction == 1:
                    matched_idx = i
                    break

            if matched_idx is not None:
                pos = self._open_positions.pop(matched_idx)
                watermarks = self._position_watermarks.pop(id(pos), {})
                pnl = pos.direction * (report.average_fill_price - pos.entry_price) * pos.size
                pnl_pct = (pnl / (pos.entry_price * pos.size)) * 100 if pos.entry_price * pos.size else 0.0

                # Compute MAE/MFE as % of entry notional
                notional = pos.entry_price * pos.size
                if notional > 0 and watermarks:
                    worst = watermarks.get("worst_price", pos.entry_price)
                    best = watermarks.get("best_price", pos.entry_price)
                    mae_pct = abs(min(0.0, pos.direction * (worst - pos.entry_price) / pos.entry_price)) * 100
                    mfe_pct = abs(max(0.0, pos.direction * (best - pos.entry_price) / pos.entry_price)) * 100
                else:
                    mae_pct = 0.0
                    mfe_pct = 0.0

                closed = ClosedTrade(
                    trade_id=uuid.uuid4().hex,
                    asset=report.asset,
                    direction=pos.direction,
                    entry_price=pos.entry_price,
                    exit_price=report.average_fill_price,
                    size=pos.size,
                    realized_pnl=pnl,
                    realized_pnl_pct=pnl_pct,
                    commission_total=sum(f.commission for f in report.fills),
                    slippage_bps=report.slippage_bps,
                    entry_timestamp=pos.entry_timestamp,
                    exit_timestamp=report.timestamp,
                    duration_seconds=report.timestamp - pos.entry_timestamp,
                    source_model=pos.source_model,
                    source_timeframe=pos.source_timeframe,
                    entry_order_id="",
                    exit_order_id=report.order_id,
                    mae_pct=mae_pct,
                    mfe_pct=mfe_pct,
                )
                await self.trade_journal.save_closed_trade(closed)
                logger.info(
                    f"Recorded closed trade — {report.asset} pnl={pnl:.4f}",
                )
            else:
                # Open a short
                pos = PositionState(
                    asset=report.asset,
                    direction=-1,
                    entry_price=report.average_fill_price,
                    current_price=report.average_fill_price,
                    size=report.filled_size,
                    unrealized_pnl=0.0,
                    entry_timestamp=report.timestamp,
                    source_model=report.metadata.get("model_name", ""),
                    source_timeframe=report.metadata.get("timeframe", ""),
                    stop_loss_price=report.stop_loss_price,
                    take_profit_price=report.take_profit_price,
                )
                self._open_positions.append(pos)
                self._position_watermarks[id(pos)] = {
                    "worst_price": report.average_fill_price,
                    "best_price": report.average_fill_price,
                }

        # Update MAE/MFE watermarks for all open positions
        for open_pos in self._open_positions:
            wm = self._position_watermarks.get(id(open_pos))
            if wm:
                wm["worst_price"] = min(wm["worst_price"], report.average_fill_price) if open_pos.direction == 1 else max(wm["worst_price"], report.average_fill_price)
                wm["best_price"] = max(wm["best_price"], report.average_fill_price) if open_pos.direction == 1 else min(wm["best_price"], report.average_fill_price)

        # Snapshot equity point after every fill
        await self._snapshot_equity(report.timestamp)

    async def _snapshot_equity(self, timestamp: float) -> None:
        """Read latest AccountSnapshot from DB and write an EquityPoint with exposure."""
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM risk_account_snapshots ORDER BY timestamp DESC LIMIT 1",
            )
        if not row:
            return

        # Compute net/gross exposure from local open positions
        equity = row["equity"]
        long_notional = sum(p.current_price * p.size for p in self._open_positions if p.direction == 1)
        short_notional = sum(p.current_price * p.size for p in self._open_positions if p.direction == -1)
        net_exposure_pct = ((long_notional - short_notional) / equity * 100) if equity > 0 else 0.0
        gross_exposure_pct = ((long_notional + short_notional) / equity * 100) if equity > 0 else 0.0

        point = EquityPoint(
            timestamp=timestamp,
            equity=equity,
            balance=row["balance"],
            unrealized_pnl=row["unrealized_pnl"],
            drawdown_pct=row["drawdown_pct"],
            open_position_count=row["open_position_count"],
        )
        await self.equity_builder.save_equity_point(point, net_exposure_pct, gross_exposure_pct)

    @staticmethod
    def _decode_report(payload: dict) -> ExecutionReport:
        """Decode Valkey bytes payload into ExecutionReport.

        Same pattern as FillListener._decode_execution_report().
        """
        decoded: dict[str, Any] = {}
        for k, v in payload.items():
            key = k.decode("utf-8") if isinstance(k, bytes) else k
            val = v.decode("utf-8") if isinstance(v, bytes) else v
            decoded[key] = val

        fills_raw = decoded.get("fills", "[]")
        if isinstance(fills_raw, str):
            fills_raw = json.loads(fills_raw)

        metadata_raw = decoded.get("metadata", "{}")
        if isinstance(metadata_raw, str):
            metadata_raw = json.loads(metadata_raw)

        return ExecutionReport(
            order_id=decoded["order_id"],
            idempotency_key=decoded["idempotency_key"],
            asset=decoded["asset"],
            side=decoded["side"],
            requested_size=float(decoded["requested_size"]),
            filled_size=float(decoded["filled_size"]),
            requested_price=float(decoded["requested_price"]),
            average_fill_price=float(decoded["average_fill_price"]),
            status=decoded["status"],
            fills=fills_raw,
            slippage_bps=float(decoded.get("slippage_bps", 0)),
            stop_loss_price=float(decoded["stop_loss_price"]) if decoded.get("stop_loss_price") else None,
            take_profit_price=float(decoded["take_profit_price"]) if decoded.get("take_profit_price") else None,
            timestamp=float(decoded["timestamp"]),
            error_message=decoded.get("error_message", ""),
            metadata=metadata_raw,
        )
```

### F. Main Entrypoint (`apps/portfolio_app/main.py`)

```python
from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker

CONFIG_FILE_PORTFOLIO = "configs/portfolio.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all asset symbols.

    Returns: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    """
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    return [a for a in assets_config if a != KEY_DEFAULT and isinstance(assets_config[a], dict)]


async def main() -> None:
    configure_logging()
    config_mgr = ConfigManager()

    assets = _discover_assets(config_mgr)
    logger.info(f"Portfolio tracker assets: {assets}")

    # DB pool setup (same pattern as risk_app)
    db_pool = None  # TODO: create asyncpg pool from config

    # Valkey client setup
    redis_client = None  # TODO: create redis.asyncio client from config

    workers: list[PortfolioWorker] = []
    tasks: list[asyncio.Task] = []

    for asset in assets:
        worker = PortfolioWorker(
            asset=asset,
            db_pool=db_pool,
            config_mgr=config_mgr,
        )
        await worker.connect(redis_client)
        workers.append(worker)
        tasks.append(asyncio.create_task(worker.start()))

    logger.info(f"Spawned {len(tasks)} portfolio workers")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Portfolio app shutting down")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Implementation Order

| Step | File(s) | Description |
|---|---|---|
| 0 | `src/libs/contracts/schemas.py`, `src/apps/risk_app/risk_worker.py`, `src/apps/execution_app/execution_worker.py` | **Prerequisite:** Add `model_name`, `source_timeframe` fields to `OrderExecutionRequest`. Update RiskWorker to pass them. Update ExecutionWorker decode/encode to propagate into `ExecutionReport.metadata`. Update existing tests. |
| 1 | `src/libs/common/enums.py` | Add `PORTFOLIO_TRACKER = "PORTFOLIO_TRACKER"` to `SystemComponent` |
| 2 | `src/libs/contracts/schemas.py` | Add `ClosedTrade`, `TradeJournalEntry`, `PnLAttribution`, `PerformanceSummary`, `EquityPoint`, `PortfolioSnapshot`, `ExposurePoint`, `BenchmarkComparison` |
| 3 | `configs/portfolio.yaml` | Create config file (including returns, benchmark, exposure sections) |
| 4 | `src/libs/portfolio/__init__.py` | Create empty package |
| 5 | `src/libs/portfolio/returns.py` | Implement `resample_equity_curve`, `compute_log_returns`, `compute_simple_returns`, `get_return_timestamps` |
| 6 | `src/libs/portfolio/metrics.py` | Implement `compute_performance`, `compute_sharpe`, `compute_sortino`, `compute_max_drawdown`, `compute_calmar`, `compute_trade_stats`, `compute_rolling_sharpe` — all ratio metrics consume regular-interval returns from `returns.py` |
| 7 | `src/libs/portfolio/benchmark.py` | Implement `compute_benchmark_comparison`, `build_benchmark_returns` |
| 8 | `src/libs/portfolio/attribution.py` | Implement `attribute_pnl` |
| 9 | `src/libs/portfolio/trade_journal.py` | Implement `TradeJournal` class with DB queries |
| 10 | `src/libs/portfolio/equity_curve.py` | Implement `EquityCurveBuilder` with DB queries and `build_from_account_snapshots` |
| 11 | `tests/portfolio/__init__.py` | Create test package |
| 12 | `tests/portfolio/test_returns.py` | Unit tests for resampling, log returns, edge cases |
| 13 | `tests/portfolio/test_metrics.py` | Unit tests for all metric functions using regular-interval returns |
| 14 | `tests/portfolio/test_benchmark.py` | Unit tests for alpha, beta, IR, tracking error |
| 15 | `tests/portfolio/test_attribution.py` | Unit tests for PnL attribution |
| 16 | `tests/portfolio/test_trade_journal.py` | Unit tests for TradeJournal (mock DB) |
| 17 | `tests/portfolio/test_equity_curve.py` | Unit tests for EquityCurveBuilder (mock DB) |
| 18 | `src/apps/portfolio_app/__init__.py` | Create app package |
| 19 | `src/apps/portfolio_app/portfolio_worker.py` | Implement PortfolioWorker with MAE/MFE tracking and exposure computation |
| 20 | `src/apps/portfolio_app/main.py` | Implement entrypoint |
| 21 | `tests/portfolio/test_portfolio_worker.py` | Unit tests for PortfolioWorker (mock Valkey + DB) — verify MAE/MFE, exposure |

Step 0 is a prerequisite that touches existing code (minimal changes).
Steps 1-8 are pure logic with no DB or Valkey dependency — implement and test first.
Steps 9-10 add DB interaction — test with mocked `db_pool`.
Steps 18-21 add the live consumer — test with mocked Valkey client.

---

## Acceptance Criteria

1. `resample_equity_curve()` converts irregular equity points to fixed-interval grid with forward-fill.
2. `compute_log_returns()` produces correct log returns from resampled equity points.
3. `compute_performance()` returns a valid `PerformanceSummary` with all metrics populated.
4. `compute_sharpe()` uses regular-interval returns and returns 0.0 for flat equity, positive for upward-trending, negative for downward-trending.
5. `compute_sortino()` uses only downside deviation; returns ≥ Sharpe for positive-skew return distributions.
6. `compute_max_drawdown()` correctly identifies the deepest trough and longest recovery period.
7. `compute_calmar()` returns annualized return / max drawdown.
8. `compute_rolling_sharpe()` returns windowed Sharpe values with correct timestamps.
9. `compute_benchmark_comparison()` returns alpha, beta, information ratio, tracking error, correlation.
10. `attribute_pnl()` correctly groups by asset, model, and timeframe, and `pnl_pct_of_total` sums to ~100% across groups.
11. `TradeJournal.get_closed_trades()` filters by asset, model, timeframe, and time range correctly.
12. `TradeJournal.get_journal_entries()` enriches trades with nearest equity snapshot.
13. `EquityCurveBuilder.get_equity_curve()` returns points sorted by timestamp ASC.
14. `EquityCurveBuilder.build_from_account_snapshots()` produces `EquityPoint` objects from `risk_account_snapshots` rows.
15. `PortfolioWorker` correctly builds `ClosedTrade` with MAE/MFE from FIFO-matched fill pairs.
16. `PortfolioWorker` creates equity snapshots with net/gross exposure after each fill.
17. `ClosedTrade.mae_pct` and `mfe_pct` are correctly computed from position watermarks.
18. All modules use `bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)`.
19. All config read via `ConfigManager` — no `os.getenv()`.
20. No imports from `apps/` in `libs/portfolio/`.
21. All new tests pass: `pytest tests/portfolio/ -v`.
22. Existing tests unaffected: `pytest tests/ --ignore=tests/e2e -q` shows no regressions.
23. Step 0 prerequisite: `OrderExecutionRequest` propagates `model_name` and `source_timeframe` through to `ExecutionReport.metadata`.

---

## Validation Checklist

- [ ] Equity curve is resampled to fixed intervals (default 1h) BEFORE computing any ratio metric.
- [ ] Sharpe computation uses regular-interval log returns and annualizes with `sqrt(periods_per_year)`.
- [ ] Sortino uses only downside returns for denominator.
- [ ] Max drawdown tracks peak-to-trough percentage, not absolute value.
- [ ] Win rate = winning trades / total trades (not including breakeven).
- [ ] Profit factor handles zero gross loss (returns inf).
- [ ] Trade duration computed as `exit_timestamp - entry_timestamp`.
- [ ] PnL attribution sums are consistent across group-by dimensions.
- [ ] DB queries use parameterized values, never f-string interpolation.
- [ ] `PortfolioWorker` consumer group is distinct from `risk_app`'s group.
- [ ] Equity snapshots reference `risk_account_snapshots` — no duplicate state.
- [ ] `portfolio_closed_trades` uses `ON CONFLICT DO NOTHING` for idempotency.
- [ ] Config keys match `configs/portfolio.yaml` exactly.
- [ ] No circular imports between `libs/portfolio/` and `libs/risk/`.
- [ ] Benchmark comparison uses aligned return series (same length, same grid).
- [ ] Beta computed as `cov(strategy, benchmark) / var(benchmark)` — manual (no numpy).
- [ ] MAE/MFE watermarks updated on every fill for all open positions of that asset.
- [ ] MAE/MFE: MAE tracks worst adverse move, MFE tracks best favorable move, as % of entry notional.
- [ ] Exposure: net_exposure_pct = (long_notional - short_notional) / equity * 100.
- [ ] Rolling Sharpe window slides correctly without look-ahead bias.
- [ ] Step 0: `model_name` and `source_timeframe` propagate from TradeSignal → OrderExecutionRequest → ExecutionReport.metadata.

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| `PortfolioWorker` FIFO position matching drifts from `FillListener`'s matching | Phantom trades or double-counted PnL | Both use identical FIFO logic. Mitigation: periodic reconciliation by comparing `portfolio_closed_trades` PnL sum against `AccountState.realized_pnl`. |
| `risk_account_snapshots` rows not yet persisted when `PortfolioWorker` reads | Stale equity data in equity curve | `PortfolioWorker` reads the latest row, which is "close enough" (risk_app saves frequently). Accept minor lag for v1. |
| Very high fill rate overwhelms equity curve table | Storage bloat | `snapshot_interval_seconds` in config caps snapshot frequency. Downsampling on read via `max_points`. |
| `source_model` and `source_timeframe` are empty strings from `FillListener` | Attribution by model/timeframe is useless | **Resolved by Step 0:** `OrderExecutionRequest` now carries `model_name` and `source_timeframe` fields. ExecutionWorker propagates them into `ExecutionReport.metadata`. PortfolioWorker extracts from `metadata`. |
| Backtest mode has no `portfolio_app` running | No closed trades in `portfolio_closed_trades` | Use `TradeJournal` + `EquityCurveBuilder.build_from_account_snapshots()` to compute from existing tables. Or run a one-off script that replays `execution_fills` into `portfolio_closed_trades`. |

---

## Open Questions

| # | Question | Default if Not Answered |
|---|---|---|
| 1 | Should `PortfolioWorker` also persist a periodic equity snapshot on a timer (not just on fills)? | Yes, at `periodic_snapshot_seconds` interval (config default: 60s) |
| 2 | Should `PortfolioSnapshot` support serialization to JSON for a future REST API? | No — Pydantic `.model_dump()` is sufficient for v1. REST API is a non-goal. |
| 3 | Should the `_decode_report` logic be extracted to a shared utility (it's duplicated in `FillListener`)? | Follow-up refactor — keep duplicated for v1 to avoid modifying `fill_listener.py`. |
| 4 | ~~Does `ExecutionReport.metadata` currently carry `model_name`/`timeframe`?~~ | ~~Resolved — Step 0 adds this.~~ |

---

## Blast Radius and Affected Flows

### Blast Radius: LOW

This module is **purely additive** with one minor prerequisite change:
- Step 0: `OrderExecutionRequest` gets two new optional fields (`model_name`, `source_timeframe`) with defaults — fully backward-compatible. `risk_worker.py` gets 2 lines added. `execution_worker.py` decode/encode updated to propagate metadata.
- Two existing files modified (schemas.py gets new models, enums.py gets one new value) — both are append-only changes with no effect on existing consumers.
- No existing DB table is modified.
- The `portfolio_app` reads from `fills:{asset}` with its own consumer group — it does not compete with `risk_app`'s `FillListener`.
- The `libs/portfolio/` library has no reverse dependencies at creation time.

### Affected Execution Flows: NONE

The Portfolio Tracker observes the pipeline. It does not participate in any existing execution flow. No existing flow is changed.
