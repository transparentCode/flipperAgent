"""Tier 4 — Pivot Density constraint benchmark.

Measures whether the extractor produces an optimal density of pivots per
100 bars of training data. Using density (pivots/100bars) instead of
absolute counts makes the constraint portable across timeframes and
training window sizes.

Too few pivots → not enough structure to fit lines.
Too many pivots → over-segmented, noisy lines.

Uses a tent function that peaks at 1.0 in [density_optimal_lo, density_optimal_hi]
and decays to 0 outside.
"""

from __future__ import annotations

from typing import Dict


def compute(
    n_pivots: float,
    n_bars: int,
    *,
    density_min: float = 2.0,
    density_optimal_lo: float = 8.0,
    density_optimal_hi: float = 25.0,
    min_pivot_score: float = 0.3,
) -> Dict[str, object]:
    """Compute pivot density score and constraint pass status.

    Parameters
    ----------
    n_pivots : total pivot count from the extractor.
    n_bars : number of bars in the training window (used for normalization).
    density_min : minimum density (pivots/100bars) below which score = 0.
    density_optimal_lo : lower bound of optimal density range.
    density_optimal_hi : upper bound of optimal density range.
    min_pivot_score : threshold for passing the constraint.

    Returns
    -------
    dict with keys: ``pivot_score``, ``passed_constraint``, ``density``.
    """
    density = (n_pivots / max(n_bars, 1)) * 100
    score = tent_score(
        density,
        density_min=density_min,
        density_optimal_lo=density_optimal_lo,
        density_optimal_hi=density_optimal_hi,
    )
    return {
        "pivot_score": score,
        "passed_constraint": score >= min_pivot_score,
        "density": density,
    }


def tent_score(
    density: float,
    *,
    density_min: float = 2.0,
    density_optimal_lo: float = 8.0,
    density_optimal_hi: float = 25.0,
) -> float:
    """Tent function over pivot density (pivots per 100 bars).

    0 at density_min, ramps to 1 at density_optimal_lo, flat at 1 in
    [density_optimal_lo, density_optimal_hi], decays above density_optimal_hi
    reaching 0 at 2× density_optimal_hi.
    """
    if density < density_min:
        return 0.0
    if density < density_optimal_lo:
        return (density - density_min) / max(density_optimal_lo - density_min, 1e-9)
    if density <= density_optimal_hi:
        return 1.0
    # Decay above optimal_hi — reaches 0 at 2× density_optimal_hi
    return max(0.0, 1.0 - (density - density_optimal_hi) / max(density_optimal_hi, 1e-9))


def constraint_penalty(
    pivot_score: float,
    min_score: float = 0.3,
    penalty: float = 0.3,
) -> float:
    """Multiplicative constraint penalty for pivot density.

    Returns 1.0 if pivot_score >= min_score, else ``penalty``.
    """
    if pivot_score >= min_score:
        return 1.0
    return penalty
