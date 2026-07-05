"""Consolidated utility helpers for trendlines-native signal extraction.

Merged from context_utils, math_utils, and temporal_utils.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Sequence

import numpy as np

from app.trendlines.boundary import BoundaryResult, Ray


# --- Context helpers ---

def volume_is_trustworthy(context: Mapping[str, Any] | None) -> bool:
    if context is None:
        return False
    for key in ("volume_is_trustworthy", "trustworthy_volume"):
        if key in context:
            return bool(context.get(key))
    return False


# --- Numeric helpers ---

def z_score(current: float, values: Sequence[float]) -> float:
    mean = float(np.mean(values))
    std = float(np.std(values))
    if std <= 0:
        return 0.0
    return (current - mean) / std


def series_acceleration(series: Sequence[float]) -> float:
    if len(series) < 2:
        return 0.0
    diffs = [series[i + 1] - series[i] for i in range(len(series) - 1)]
    return sum(diffs) / len(diffs)


# --- Temporal helpers ---

def has_matching_ray(
    target: Ray,
    candidates: List[Ray],
    slope_match_tol: float,
) -> bool:
    for candidate in candidates:
        if candidate.kernel != target.kernel:
            continue
        if abs(candidate.slope - target.slope) <= slope_match_tol:
            return True
    return False


def count_persistent_rays(
    current_rays: List[Ray],
    window: List[BoundaryResult],
    *,
    is_support: bool,
    slope_match_tol: float,
) -> int:
    count = 0
    threshold = max(len(window) // 2, 1)

    for ray in current_rays:
        appearances = 0
        for boundary_result in window:
            past_rays = (
                boundary_result.active_support_rays
                if is_support
                else boundary_result.active_resistance_rays
            )
            if has_matching_ray(ray, past_rays, slope_match_tol):
                appearances += 1
        if appearances >= threshold:
            count += 1
    return count


__all__ = [
    "count_persistent_rays",
    "has_matching_ray",
    "series_acceleration",
    "volume_is_trustworthy",
    "z_score",
]
