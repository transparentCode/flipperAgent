"""
Regime Optimization Module.

5-parameter Bayesian optimization for the 4-layer regime detection pipeline.

Usage
-----
    from app.regime.optimization import RegimeOptimizer, OptimizationConfig

    config = OptimizationConfig(n_trials=100, timeout_seconds=3600)
    optimizer = RegimeOptimizer(config)
    result = optimizer.optimize(df, asset="BTCUSDT", timeframe="1h")
    result.apply_to_config("app/regime/config/regime.yaml")
"""

from .models import (
    BenchmarkResults,
    OptimizationConfig,
    OptimizationResult,
    OptimizationWeights,
    SearchSpace,
    TrialResult,
    WalkForwardConfig,
)
from .optimizer import RegimeOptimizer
from .walk_forward import CombinatorialPurgedCV, WalkForwardSplit, WalkForwardValidator

__all__ = [
    "BenchmarkResults",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationWeights",
    "SearchSpace",
    "TrialResult",
    "WalkForwardConfig",
    "RegimeOptimizer",
    "WalkForwardValidator",
    "WalkForwardSplit",
    "CombinatorialPurgedCV",
]
