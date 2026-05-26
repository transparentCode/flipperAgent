"""Execution contracts."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


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


__all__ = [
    "OrderExecutionRequest",
    "OrderStatus",
    "OrderFill",
    "ExecutionReport",
]
