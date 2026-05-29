"""Shared vectorized extraction of RegressionResult fields into numpy arrays."""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from app.regression.contracts.result import RegressionResult


def _safe_last(arr_or_scalar) -> float:
    """Extract the last element from an array or return a scalar directly."""
    if arr_or_scalar is None:
        return np.nan
    if np.isscalar(arr_or_scalar):
        return float(arr_or_scalar)
    if hasattr(arr_or_scalar, '__len__') and len(arr_or_scalar) == 0:
        return np.nan
    return float(arr_or_scalar[-1])


def extract_result_arrays(
    results: List[RegressionResult], closes: np.ndarray,
) -> Dict[str, np.ndarray]:
    """Pre-extract scalar fields from results into aligned numpy arrays.

    Runs once per fold evaluation; all 5 benchmarks index into these arrays.
    Returns dict with keys: indices, directions, direction_signs, confidence_scores,
    upper_vals, lower_vals, mid_vals, band_widths, valid_mask.
    Only includes results where is_valid=True, mid_line is not None/empty,
    and the computed index is within bounds of closes.
    """
    n_closes = len(closes)
    n_results = len(results)

    if n_results == 0:
        empty = np.array([], dtype=np.float64)
        return {
            "indices": np.array([], dtype=np.int64),
            "directions": np.array([], dtype='<U8'),
            "direction_signs": empty,
            "confidence_scores": empty,
            "upper_vals": empty,
            "lower_vals": empty,
            "mid_vals": empty,
            "band_widths": empty,
            "valid_mask": np.array([], dtype=bool),
        }

    indices = np.empty(n_results, dtype=np.int64)
    direction_signs = np.empty(n_results, dtype=np.float64)
    confidence_scores = np.empty(n_results, dtype=np.float64)
    upper_vals = np.empty(n_results, dtype=np.float64)
    lower_vals = np.empty(n_results, dtype=np.float64)
    mid_vals = np.empty(n_results, dtype=np.float64)
    band_widths = np.empty(n_results, dtype=np.float64)
    directions = []

    count = 0
    for res in results:
        if not res.is_valid:
            continue
        if res.mid_line is None:
            continue
        if hasattr(res.mid_line, '__len__') and len(res.mid_line) == 0:
            continue

        idx = res.window_used + res.bars_since_init - 1
        if idx < 0 or idx >= n_closes:
            continue

        mid_v = _safe_last(res.mid_line)
        if not np.isfinite(mid_v):
            continue

        upper_v = _safe_last(res.upper_band)
        lower_v = _safe_last(res.lower_band)

        if res.direction == "BULLISH":
            d_sign = 1.0
        elif res.direction == "BEARISH":
            d_sign = -1.0
        else:
            d_sign = 0.0

        confidence_score = float(res.confidence) * 100.0 if np.isfinite(res.confidence) else 0.0

        indices[count] = idx
        directions.append(res.direction)
        direction_signs[count] = d_sign
        confidence_scores[count] = confidence_score
        upper_vals[count] = upper_v
        lower_vals[count] = lower_v
        mid_vals[count] = mid_v
        band_widths[count] = res.band_width_avg if np.isfinite(res.band_width_avg) else 0.0
        count += 1

    dirs_arr = np.array(directions, dtype='<U8')

    # Turnover: count direction changes (ignoring NEUTRAL)
    if count > 1:
        non_neutral = dirs_arr != "NEUTRAL"
        # Only compare consecutive non-neutral directions
        both_non_neutral = non_neutral[:-1] & non_neutral[1:]
        direction_changes = int(np.sum(
            both_non_neutral & (dirs_arr[:-1] != dirs_arr[1:])
        ))
        turnover_rate = direction_changes / (count - 1)
    else:
        turnover_rate = 0.0

    return {
        "indices": indices[:count].copy(),
        "directions": dirs_arr,
        "direction_signs": direction_signs[:count].copy(),
        "confidence_scores": confidence_scores[:count].copy(),
        "upper_vals": upper_vals[:count].copy(),
        "lower_vals": lower_vals[:count].copy(),
        "mid_vals": mid_vals[:count].copy(),
        "band_widths": band_widths[:count].copy(),
        "valid_mask": np.ones(count, dtype=bool),
        "turnover_rate": np.float64(turnover_rate),
    }
