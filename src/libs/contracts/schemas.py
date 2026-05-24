from pydantic import BaseModel, Field
from typing import Optional

class TradeSignal(BaseModel):
    asset: str = Field(..., description="The asset symbol")
    timeframe: str = Field(..., description="The timeframe")
    timestamp: float = Field(..., description="Timestamp of the signal")
    direction: int = Field(..., description="1 for long, -1 for short, 0 for flat")
    conviction: float = Field(default=1.0, description="Conviction of the signal")
    price: float = Field(..., description="The exact asset price at the time the signal was generated")
    idempotency_key: str = Field(..., description="Unique deterministic key for idempotency")
    
class OrderExecutionRequest(BaseModel):
    asset: str = Field(..., description="The asset symbol")
    side: str = Field(..., description="buy or sell")
    size: float = Field(..., description="Size of the order")
    order_type: str = Field(default="market", description="Type of the order")
    timestamp: float = Field(..., description="Timestamp of the order generation")
    requested_price: float = Field(..., description="Intended fill price before slippage or depth simulation")
    idempotency_key: str = Field(..., description="Unique key for idempotency")
