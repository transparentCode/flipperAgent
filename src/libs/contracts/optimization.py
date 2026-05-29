"""Optimization contracts."""

from typing import Any, Optional

from pydantic import BaseModel, Field


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


class ScreeningSummary(BaseModel):
    """Summary of Stage 1 importance screening."""
    screening_trials: int
    importance_threshold: float
    importances: dict[str, float]
    frozen_params: dict[str, Any]
    active_params: list[str]
    total_params: int
    reduced_params: int


class TwoStageResult(BaseModel):
    """Output of the two-stage automated optimization pipeline."""
    model_name: str
    asset: str
    timeframe: str
    best_params: dict[str, Any]
    deployed: bool
    rejection_reason: Optional[str] = None
    screening: ScreeningSummary
    oos_metrics: dict[str, dict[str, float]]
    default_params: dict[str, Any]
    stage2_best_score: Optional[float] = None
    stage2_n_trials: int = 0


__all__ = [
    "StudyConfig",
    "TrialResult",
    "ParamAuditReport",
    "ScheduleEntry",
    "OptimizationDefaults",
    "OptimizationConfig",
    "ScreeningSummary",
    "TwoStageResult",
]
