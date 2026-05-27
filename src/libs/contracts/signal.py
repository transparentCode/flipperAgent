"""Signal and model-strategy layer contracts."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


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


__all__ = [
    "TradeSignal", "FeatureVector", "ModelOutput", "ParamDef",
    "ScoringOutput", "SelectionCandidate", "SelectionResult",
]
