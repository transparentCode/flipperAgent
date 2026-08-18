"""Public contract for the standalone structural regression estimate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class StructuralRegressionEstimate:
    """Descriptive robust structural estimate for one causal market window."""

    asset: str
    timeframe: str
    window_started_at: datetime
    timestamp: datetime
    observed_through: datetime
    source_config_hash: str
    estimator_id: str
    window_size: int
    slope_log_per_hour: float
    center_price: float
    residual_mad_log: float
    fit_quality: float
