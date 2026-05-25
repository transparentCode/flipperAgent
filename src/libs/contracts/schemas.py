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


class OrderExecutionRequest(BaseModel):
    asset: str = Field(..., description="The asset symbol")
    side: str = Field(..., description="buy or sell")
    size: float = Field(..., description="Size of the order")
    order_type: str = Field(default="market", description="Type of the order")
    timestamp: float = Field(..., description="Timestamp of the order generation")
    requested_price: float = Field(..., description="Intended fill price before slippage or depth simulation")
    idempotency_key: str = Field(..., description="Unique key for idempotency")


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
