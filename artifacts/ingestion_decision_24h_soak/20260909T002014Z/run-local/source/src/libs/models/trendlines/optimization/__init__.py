"""Trendlines Hyperparameter Optimization Framework.

5-parameter Bayesian optimization with 5-tier geometric objective
and walk-forward cross-validation.
"""

from libs.models.trendlines.optimization.models import (
    TrendlinesBenchmarkResults,
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
    TrendlinesOptimizationWeights,
    TrendlinesTrialResult,
)
from libs.models.trendlines.optimization.oscillator import (
    OscillatorOptimizationConfig,
    apply_oscillator_result,
    optimize_oscillator_trendlines,
)
from libs.models.trendlines.optimization.optimizer import TrendlinesOptimizer
from libs.models.trendlines.optimization.walk_forward import WalkForwardSplit, WalkForwardValidator

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
