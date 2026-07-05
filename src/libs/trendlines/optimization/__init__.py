"""Trendlines Hyperparameter Optimization Framework.

5-parameter Bayesian optimization with 5-tier geometric objective
and walk-forward cross-validation.
"""

from app.trendlines.optimization.models import (
    TrendlinesBenchmarkResults,
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
    TrendlinesOptimizationWeights,
    TrendlinesTrialResult,
)
from app.trendlines.optimization.oscillator import (
    OscillatorOptimizationConfig,
    apply_oscillator_result,
    optimize_oscillator_trendlines,
)
from app.trendlines.optimization.optimizer import TrendlinesOptimizer
from app.trendlines.optimization.walk_forward import WalkForwardSplit, WalkForwardValidator

__all__ = [
    "OscillatorOptimizationConfig",
    "TrendlinesBenchmarkResults",
    "TrendlinesOptimizationConfig",
    "TrendlinesOptimizationResult",
    "TrendlinesOptimizationWeights",
    "TrendlinesTrialResult",
    "TrendlinesOptimizer",
    "WalkForwardSplit",
    "WalkForwardValidator",
    "apply_oscillator_result",
    "optimize_oscillator_trendlines",
]
