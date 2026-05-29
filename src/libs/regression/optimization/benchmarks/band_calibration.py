"""
Tier 2: Band Calibration (30% weight).

coverage = count(lower <= close <= upper) / N   (target: ~95% for 2sigma)
width_stability = CV(band_width_avg over time)  (lower = better)
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from app.regression.contracts.result import RegressionResult
from app.regression.optimization.benchmarks._common import extract_result_arrays
from app.regression.optimization.constants import DEFAULT_TARGET_COVERAGE


def compute(
    results: List[RegressionResult],
    closes: np.ndarray,
    target_coverage: float = DEFAULT_TARGET_COVERAGE,
    arrays: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, float]:
    """Compute band coverage and width stability."""
    if not results:
        return {"band_coverage_pct": 0.0, "band_width_stability": 1.0}

    if arrays is None:
        arrays = extract_result_arrays(results, closes)
    indices = arrays["indices"]
    upper_vals = arrays["upper_vals"]
    lower_vals = arrays["lower_vals"]
    bw = arrays["band_widths"]

    if len(indices) == 0:
        return {"band_coverage_pct": 0.0, "band_width_stability": 1.0}

    band_valid = np.isfinite(upper_vals) & np.isfinite(lower_vals)
    if np.sum(band_valid) == 0:
        return {"band_coverage_pct": 0.0, "band_width_stability": 1.0}

    valid_indices = indices[band_valid]
    valid_upper = upper_vals[band_valid]
    valid_lower = lower_vals[band_valid]
    valid_bw = bw[band_valid]

    prices = closes[valid_indices]
    inside = (prices >= valid_lower) & (prices <= valid_upper)
    raw_coverage = float(np.sum(inside)) / len(inside)

    # Score: 1.0 when coverage == target, drops linearly with deviation
    coverage = max(0.0, 1.0 - abs(raw_coverage - target_coverage) / target_coverage)

    if len(valid_bw) > 1:
        bw_mean = np.mean(valid_bw)
        width_stability = float(np.std(valid_bw) / (bw_mean + 1e-10))
    else:
        width_stability = 1.0

    return {
        "band_coverage_pct": coverage,
        "band_width_stability": width_stability,
    }

