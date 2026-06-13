"""Signal and model-strategy layer contracts."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class StreamOHLCVPayload(BaseModel):
    """Pydantic validation for incoming stream:ohlcv:{symbol}:{tf} payloads.

    Published by the ingestion layer, consumed by the signal runtime worker.
    """
    exchange: str = Field(default="", description="Source exchange identifier")
    symbol: str = Field(default="", description="Trading pair symbol")
    timeframe: str = Field(default="", description="Candle timeframe")
    timestamp: float = Field(..., description="Candle open timestamp (seconds or ms)")
    open: float = Field(..., description="Open price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Close price")
    volume: float = Field(..., description="Trade volume")
    taker_buy_base: float = Field(default=0.0, description="Taker buy base volume")
    bar_closed: bool = Field(default=True, description="Whether the bar is closed")
    ingestion_timestamp: float = Field(default=0.0, description="Ingestion timestamp (ms epoch)")


class StreamFeaturePayload(BaseModel):
    """Stream transport wrapper for FeatureVector — published on features:{asset}:{tf}."""
    asset: str
    timeframe: str
    timestamp: float
    features: dict[str, Any] = Field(default_factory=dict)
    bar_data: dict[str, float] = Field(default_factory=dict)


class StreamSignalPayload(BaseModel):
    """Stream transport wrapper for TradeSignal — published on signals:{asset}:{tf}."""
    asset: str
    timeframe: str
    timestamp: float
    direction: int
    conviction: float = Field(default=1.0)
    price: float
    idempotency_key: str
    model_name: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class FeatureVector(BaseModel):
    """Published by the signal runtime worker, consumed by StrategyWorker."""
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


class ScoringOutput(BaseModel):
    """Returned by ScoringModel.evaluate() — continuous edge score."""
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    edge_score: float = Field(..., description="Continuous edge estimate, unbounded")
    conviction: float = Field(default=1.0, ge=0.0, le=1.0, description="Model self-confidence")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectionCandidate(BaseModel):
    """Unified candidate for the selection layer."""
    model_name: str
    asset: str
    timeframe: str
    timestamp: float
    direction: int
    edge_score: float
    conviction: float
    source_type: Literal["threshold", "scoring"]
    metadata: dict[str, Any] = Field(default_factory=dict)


class SelectionResult(BaseModel):
    """Output of the SelectionLayer — a ranked, filtered candidate."""
    candidate: SelectionCandidate
    rank: int
    selection_score: float = Field(..., description="Final composite selection score")
    penalties: dict[str, float] = Field(default_factory=dict, description="Applied penalties breakdown")


class PriceUpdate(BaseModel):
    """Lightweight bar price update published by the signal runtime worker on every closed bar."""
    asset: str
    timeframe: str
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


__all__ = [
    "StreamOHLCVPayload", "StreamFeaturePayload", "StreamSignalPayload",
    "TradeSignal", "FeatureVector", "ModelOutput", "ParamDef",
    "ScoringOutput", "SelectionCandidate", "SelectionResult", "PriceUpdate",
]
