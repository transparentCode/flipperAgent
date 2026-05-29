"""
Regression v2 optimization benchmarks — 5 tiers.

Tier 1: Direction Accuracy (40%)            — direction_accuracy.py
Tier 2: Band Calibration (30%)              — band_calibration.py
Tier 3: Residual Quality (GATE)             — residual_quality.py
Tier 4: Confidence Correlation (CONSTRAINT) — confidence_correlation.py
Tier 5: Strategy Utility (20%)              — strategy_utility.py
"""

from . import (
    _common,
    band_calibration,
    confidence_correlation,
    direction_accuracy,
    residual_quality,
    strategy_utility,
)

BENCHMARK_REGISTRY = {
    "direction_accuracy": direction_accuracy,
    "band_calibration": band_calibration,
    "residual_quality": residual_quality,
    "confidence_correlation": confidence_correlation,
    "strategy_utility": strategy_utility,
}

__all__ = [
    "_common",
    "direction_accuracy",
    "band_calibration",
    "residual_quality",
    "confidence_correlation",
    "strategy_utility",
    "BENCHMARK_REGISTRY",
]
