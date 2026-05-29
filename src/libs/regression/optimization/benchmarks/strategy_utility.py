"""
Tier 5: Strategy Utility (20% weight).

position_t = (confidence_score_t / 100) * direction_sign_t
weighted_return_t = position_t * log_return_t
confidence_sharpe = mean(weighted) / std(weighted) * sqrt(8760)
sharpe_improvement = confidence_sharpe - bah_sharpe
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks._common import extract_result_arrays
from app.regression.optimization.constants import DEFAULT_BARS_PER_YEAR, EPSILON


def compute(
    results: List[RegressionResult],
    closes: np.ndarray,
    bars_per_year: float = DEFAULT_BARS_PER_YEAR,
    arrays: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, float]:
    """Compute confidence-weighted Sharpe and buy-and-hold Sharpe."""
    annualize_factor = np.sqrt(bars_per_year)
    log_returns = np.log(closes[1:] / closes[:-1])
    n = len(closes)

    if len(log_returns) > 1:
        bah_sharpe = float(
            np.mean(log_returns) / (np.std(log_returns) + EPSILON) * annualize_factor
        )
    else:
        bah_sharpe = 0.0

    if arrays is None:
        arrays = extract_result_arrays(results, closes)
    indices = arrays["indices"]
    direction_signs = arrays["direction_signs"]
    confidence_scores = arrays["confidence_scores"]

    if len(indices) == 0:
        return {
            "confidence_sharpe": 0.0,
            "bah_sharpe": bah_sharpe,
            "sharpe_improvement": -bah_sharpe,
            "max_drawdown": 1.0,
        }

    valid = (indices >= 1) & (indices < n)
    valid_indices = indices[valid]
    valid_signs = direction_signs[valid]
    valid_confidence_scores = confidence_scores[valid]

    if len(valid_indices) == 0:
        return {
            "confidence_sharpe": 0.0,
            "bah_sharpe": bah_sharpe,
            "sharpe_improvement": -bah_sharpe,
            "max_drawdown": 1.0,
        }

    lr = log_returns[valid_indices - 1]
    positions = (valid_confidence_scores / 100.0) * valid_signs
    weighted_returns = positions * lr

    if len(weighted_returns) < 10:
        return {
            "confidence_sharpe": 0.0,
            "bah_sharpe": bah_sharpe,
            "sharpe_improvement": -bah_sharpe,
            "max_drawdown": 1.0,
        }

    confidence_sharpe = float(
        np.mean(weighted_returns) / (np.std(weighted_returns) + EPSILON) * annualize_factor
    )

    # Compute Max Drawdown on equity curve (not log-cumsum)
    equity = np.exp(np.cumsum(weighted_returns))
    running_max = np.maximum.accumulate(equity)
    drawdowns = (running_max - equity) / (running_max + EPSILON)
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    return {
        "confidence_sharpe": confidence_sharpe,
        "bah_sharpe": bah_sharpe,
        "sharpe_improvement": confidence_sharpe - bah_sharpe,
        "max_drawdown": max_dd,
    }
