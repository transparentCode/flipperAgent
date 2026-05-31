"""Execution contracts."""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Convert a value to float, handling None and the string ``"None"``."""
    if val is None or val == "None":
        return default
    return float(val)


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
    close_reason: str = Field(default="", description="Why this close was triggered: 'tp1', 'tp2', 'tp3', 'sl', 'signal', or ''")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Passthrough metadata for downstream consumers")


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
    "decode_execution_report",
]


def decode_execution_report(payload: dict) -> ExecutionReport:
    """Shared decoder for Valkey flat-map payloads → ExecutionReport.

    Handles Binance quirks where some numeric fields arrive as the string
    ``"None"`` by coercing them to ``0.0`` before Pydantic validation.
    """
    from libs.contracts.serialization import valkey_decode

    # Pre-fix numeric fields that Binance may send as literal "None".
    _NUMERIC_FIELDS = (
        "requested_size", "filled_size", "requested_price",
        "average_fill_price", "slippage_bps", "timestamp",
    )
    coerced: dict[str, Any] = {}
    for k, v in payload.items():
        key = k.decode("utf-8") if isinstance(k, bytes) else k
        val = v.decode("utf-8") if isinstance(v, bytes) else v
        if key in _NUMERIC_FIELDS:
            coerced[key] = str(_safe_float(val))
        else:
            coerced[key] = val
    return valkey_decode(coerced, ExecutionReport)
