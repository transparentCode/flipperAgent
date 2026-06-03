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
    # Multi-TP fields
    tp_levels: list[float] = Field(default_factory=list)
    tp_portions: list[float] = Field(default_factory=list)
    trail_to_breakeven: bool = False


class PositionState(BaseModel):
    """Tracks a single open position."""
    asset: str
    direction: int
    entry_price: float
    current_price: float
    size: float
    original_size: float = 0.0
    unrealized_pnl: float
    entry_timestamp: float
    source_model: str
    source_timeframe: str
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    # Multi-TP fields
    tp_levels: list[float] = Field(default_factory=list)
    tp_portions: list[float] = Field(default_factory=list)
    tp_levels_hit: list[bool] = Field(default_factory=list)
    original_stop_loss: Optional[float] = None
    trail_to_breakeven: bool = False
    pending_close_reason: str = ""
    pending_close_requested_at: float = 0.0


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
