from enum import Enum

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional


class TradeSignal(BaseModel):
    asset: str = Field(..., description="The asset symbol")
    timeframe: str = Field(..., description="The timeframe")
    timestamp: float = Field(..., description="Timestamp of the signal")
    direction: int = Field(..., description="1 for long, -1 for short, 0 for flat")
    conviction: float = Field(default=1.0, description="Conviction of the signal")
    price: float = Field(..., description="The exact asset price at the time the signal was generated")
    idempotency_key: str = Field(..., description="Unique deterministic key for idempotency")
    model_name: str = Field(default="", description="Name of the model that generated this signal")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional model metadata (e.g. ATR)")


class OrderExecutionRequest(BaseModel):
    asset: str = Field(..., description="The asset symbol")
    side: str = Field(..., description="buy or sell")
    size: float = Field(..., description="Size of the order")
    order_type: str = Field(default="market", description="Type of the order")
    timestamp: float = Field(..., description="Timestamp of the order generation")
    requested_price: float = Field(..., description="Intended fill price before slippage or depth simulation")
    idempotency_key: str = Field(..., description="Unique key for idempotency")
    stop_loss_price: Optional[float] = Field(default=None, description="Stop-loss price from RiskAssessment")
    take_profit_price: Optional[float] = Field(default=None, description="Take-profit price from RiskAssessment")
    model_name: str = Field(default="", description="Model that generated the original signal")
    source_timeframe: str = Field(default="", description="Timeframe of the original signal")


# ---------------------------------------------------------------------------
# Model-Strategy Layer Contracts
# ---------------------------------------------------------------------------

class FeatureVector(BaseModel):
    """Published by SignalWorker, consumed by StrategyWorker."""
    asset: str
    timeframe: str
    timestamp: float
    features: dict[str, Any] = Field(default_factory=dict)
    bar_data: dict[str, float] = Field(default_factory=dict)


class ModelOutput(BaseModel):
    """Returned by BaseModel.evaluate()."""
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    direction: int = Field(..., description="1 long, -1 short, 0 flat")
    conviction: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParamDef(BaseModel):
    """Single hyper-parameter definition for a model."""
    type: Literal["float", "int", "categorical"]
    default: Any
    low: Optional[float] = None
    high: Optional[float] = None
    step: Optional[float] = None
    choices: Optional[list[Any]] = None


class StudyConfig(BaseModel):
    """Configuration for an Optuna optimization study."""
    model_name: str
    asset: str
    timeframe: str
    objectives: list[str] = Field(default_factory=lambda: ["sharpe"])
    directions: list[str] = Field(default_factory=lambda: ["maximize"])
    n_trials: int = 200
    sampler: str = "TPE"
    pruner: str = "MedianPruner"


class TrialResult(BaseModel):
    """Outcome of a single Optuna trial."""
    study_name: str
    trial_number: int
    params: dict[str, Any]
    values: dict[str, float]
    state: str
    duration_seconds: float
    timestamp: float


# ---------------------------------------------------------------------------
# Optimization Redesign Contracts
# ---------------------------------------------------------------------------

class ParamAuditReport(BaseModel):
    """Comparison of current vs proposed optimized params."""
    model_name: str
    asset: str
    timeframe: str
    current_params: dict[str, Any]
    proposed_params: dict[str, Any]
    current_metrics: dict[str, float]
    proposed_metrics: dict[str, float]
    deltas: dict[str, float]
    recommendation: str
    reason: str


class ScheduleEntry(BaseModel):
    """Per-model cron schedule entry."""
    cron: str = Field(..., description="Cron expression (e.g., '0 2 * * 1')")
    assets: list[str] = Field(default_factory=list)
    timeframes: list[str] = Field(default_factory=list)
    n_trials: Optional[int] = None
    write_back: bool = False


class OptimizationDefaults(BaseModel):
    """Global optimization defaults."""
    n_trials: int = 200
    write_back: bool = False


class OptimizationConfig(BaseModel):
    """Top-level optimization config matching configs/optimization.yaml."""
    defaults: OptimizationDefaults = Field(default_factory=OptimizationDefaults)
    schedules: dict[str, ScheduleEntry] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Risk Manager Contracts
# ---------------------------------------------------------------------------

class RiskVerdict(BaseModel):
    """Output of a single risk rule evaluation."""
    action: Literal["ALLOW", "MODIFY", "REJECT"]
    rule_name: str
    reason: str = ""
    adjusted_size: Optional[float] = None


class RiskAssessment(BaseModel):
    """Full risk evaluation result."""
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
    direction: int
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
    balance: float
    equity: float
    unrealized_pnl: float
    realized_pnl: float
    drawdown_pct: float
    peak_equity: float
    open_position_count: int
    daily_pnl: float


# ---------------------------------------------------------------------------
# Execution Contracts
# ---------------------------------------------------------------------------

class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderFill(BaseModel):
    fill_id: str
    asset: str
    side: str
    size: float
    fill_price: float
    commission: float = 0.0
    commission_asset: str = "USDT"
    timestamp: float
    is_maker: bool = False


class ExecutionReport(BaseModel):
    order_id: str
    idempotency_key: str
    asset: str
    side: str
    requested_size: float
    filled_size: float
    requested_price: float
    average_fill_price: float
    status: OrderStatus
    fills: list[OrderFill] = Field(default_factory=list)
    slippage_bps: float = 0.0
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    timestamp: float
    error_message: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    sharpe_ratio: float = Field(default=0.0, description="Annualized, from regular-interval returns")
    sortino_ratio: float = Field(default=0.0, description="Annualized, downside deviation")
    calmar_ratio: float = Field(default=0.0, description="Annual return / max drawdown")
    expectancy: float = Field(default=0.0, description="(win_rate * avg_win) - (loss_rate * avg_loss)")
    payoff_ratio: float = Field(default=0.0, description="avg_win / abs(avg_loss)")
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


class PortfolioSnapshot(BaseModel):
    """Full portfolio state at a point in time."""
    timestamp: float
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    open_positions: list[PositionState] = Field(default_factory=list)
    performance: PerformanceSummary | None = None
    attribution_by_asset: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_model: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_timeframe: list[PnLAttribution] = Field(default_factory=list)
