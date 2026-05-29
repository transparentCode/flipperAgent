"""
Tier 1: Direction Accuracy (40% weight).

For each horizon h in [4, 12, 24]:
  fwd_return(i, h) = sum(log_returns[i+1 : i+h+1])
  correct(i) = 1 if (direction=BULLISH and fwd>0) or (direction=BEARISH and fwd<0)
  accuracy(h) = sum(correct) / count(direction != NEUTRAL)

weighted_score = sum(weight_h * accuracy_h)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks._common import extract_result_arrays


def compute(
    results: List[RegressionResult],
    closes: np.ndarray,
    horizons: Tuple[int, ...] = (4, 12, 24),
    horizon_weights: Tuple[float, ...] = (0.5, 0.3, 0.2),
    arrays: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, float]:
    """Compute direction accuracy across multiple forward horizons."""
    if arrays is None:
        arrays = extract_result_arrays(results, closes)
    indices = arrays["indices"]
    direction_signs = arrays["direction_signs"]

    if len(indices) == 0:
        return {
            "direction_accuracy_4bar": 0.0,
            "direction_accuracy_12bar": 0.0,
            "direction_accuracy_24bar": 0.0,
            "weighted_direction_score": 0.0,
        }

    log_returns = np.log(closes[1:] / closes[:-1])
    cum_lr = np.concatenate([[0.0], np.cumsum(log_returns)])

    non_neutral = direction_signs != 0.0

    accuracies = {}
    for h in horizons:
        in_bounds = (indices + h) < len(cum_lr)
        mask = non_neutral & in_bounds

        if np.sum(mask) == 0:
            accuracies[h] = 0.0
            continue

        valid_indices = indices[mask]
        valid_signs = direction_signs[mask]

        fwd = cum_lr[valid_indices + h] - cum_lr[valid_indices]
        correct = ((valid_signs > 0) & (fwd > 0)) | ((valid_signs < 0) & (fwd < 0))
        accuracies[h] = float(np.sum(correct)) / len(correct)

    weighted_score = sum(
        w * accuracies.get(h, 0.0) for h, w in zip(horizons, horizon_weights)
    )

    return {
        "direction_accuracy_4bar": accuracies.get(4, 0.0),
        "direction_accuracy_12bar": accuracies.get(12, 0.0),
        "direction_accuracy_24bar": accuracies.get(24, 0.0),
        "weighted_direction_score": weighted_score,
    }
