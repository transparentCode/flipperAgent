"""Risk manager contracts."""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from libs.contracts.signal import TradeSignal


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


__all__ = ["RiskVerdict", "RiskAssessment", "PositionState", "AccountSnapshot"]
