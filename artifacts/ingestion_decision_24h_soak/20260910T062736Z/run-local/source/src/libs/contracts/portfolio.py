"""Portfolio tracker contracts."""

from typing import Optional

from pydantic import BaseModel, Field

from libs.contracts.risk import PositionState


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
    performance: Optional[PerformanceSummary] = None
    attribution_by_asset: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_model: list[PnLAttribution] = Field(default_factory=list)
    attribution_by_timeframe: list[PnLAttribution] = Field(default_factory=list)


__all__ = [
    "ClosedTrade",
    "TradeJournalEntry",
    "PnLAttribution",
    "PerformanceSummary",
    "EquityPoint",
    "ExposurePoint",
    "BenchmarkComparison",
    "PortfolioSnapshot",
]
