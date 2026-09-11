"""Trendlines optimization benchmark modules.

Each module provides a ``compute()`` function returning a dict of metrics,
plus optional gate/constraint penalty functions.
"""

from libs.models.trendlines.optimization.benchmarks import (
    fold_stability,
    longevity,
    penetration_gate,
    pivot_density,
    touch_accuracy,
)

__all__ = [
    "fold_stability",
    "longevity",
    "penetration_gate",
    "pivot_density",
    "touch_accuracy",
]
