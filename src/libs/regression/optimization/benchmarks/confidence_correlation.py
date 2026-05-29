"""
Tier 4: Confidence-Outcome Correlation — CONSTRAINT (not weighted).

pairs = [(confidence_i * 100, |fwd_return(i, 12)|)]
rho = spearmanr(confidence_scores, |fwd_returns|)

CONSTRAINT: rho > min_rho (default 0.01), else penalty multiplier.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks._common import extract_result_arrays
from app.regression.optimization.constants import (
    DEFAULT_CONFIDENCE_HORIZON,
    DEFAULT_MIN_CONFIDENCE_RHO,
    MIN_SPEARMAN_SAMPLES,
)


def compute(
    results: List[RegressionResult],
    closes: np.ndarray,
    target_horizon: int = DEFAULT_CONFIDENCE_HORIZON,
    min_rho: float = DEFAULT_MIN_CONFIDENCE_RHO,
    arrays: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, float]:
    """Compute Spearman correlation between confidence scores and forward returns."""
    if arrays is None:
        arrays = extract_result_arrays(results, closes)
    indices = arrays["indices"]
    confidence_scores = arrays["confidence_scores"]

    if len(indices) == 0:
        return {
            "confidence_return_spearman": 0.0,
            "passed_confidence_constraint": False,
        }

    log_returns = np.log(closes[1:] / closes[:-1])
    cum_lr = np.concatenate([[0.0], np.cumsum(log_returns)])

    in_bounds = (indices + target_horizon) < len(cum_lr)

    if np.sum(in_bounds) < MIN_SPEARMAN_SAMPLES:
        return {
            "confidence_return_spearman": 0.0,
            "passed_confidence_constraint": False,
        }

    valid_indices = indices[in_bounds]
    valid_confidence_scores = confidence_scores[in_bounds]

    fwd_returns = cum_lr[valid_indices + target_horizon] - cum_lr[valid_indices]
    abs_fwd = np.abs(fwd_returns)

    rho = _spearman_r(valid_confidence_scores, abs_fwd)

    return {
        "confidence_return_spearman": float(rho),
        "passed_confidence_constraint": rho > min_rho,
    }


def _spearman_r(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation without scipy dependency."""
    n = len(x)
    if n < 3:
        return 0.0
    rank_x = _rankdata(x)
    rank_y = _rankdata(y)
    d = rank_x - rank_y
    return 1.0 - (6.0 * np.sum(d ** 2)) / (n * (n ** 2 - 1))


def _rankdata(arr: np.ndarray) -> np.ndarray:
    """Assign ranks (1-based, average ties) — fully vectorized."""
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty_like(arr, dtype=float)
    ranks[order] = np.arange(1, len(arr) + 1, dtype=float)

    sorted_arr = arr[order]
    change = np.concatenate([[True], sorted_arr[1:] != sorted_arr[:-1], [True]])
    boundaries = np.where(change)[0]
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        if end - start > 1:
            avg_rank = np.mean(ranks[order[start:end]])
            ranks[order[start:end]] = avg_rank
    return ranks