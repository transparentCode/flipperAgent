"""Pure derivation functions that compute adaptive params from AssetProfile.

Every function here is pure: numbers in → numbers out. No I/O, no side effects.
These replace the hardcoded per-TF/per-asset params that were previously
sitting in trendlines.yaml.
"""

from __future__ import annotations

import math

from .asset_profile import AssetProfile


# ── TF-derived: convert wall-clock targets to bar counts ──────────────────

def derive_hold_bars(profile: AssetProfile, target_hours: float = 3.0) -> int:
    """Fakeout hold window: how many bars cover ``target_hours`` of wall-clock."""
    return max(1, math.ceil(target_hours / profile.bar_duration_hours))


def derive_volume_lookback(profile: AssetProfile, target_hours: float = 20.0) -> int:
    """Volume z-score lookback: how many bars cover ``target_hours``."""
    return max(5, math.ceil(target_hours / profile.bar_duration_hours))


def derive_min_history(profile: AssetProfile, target_hours: float = 6.0) -> int:
    """Temporal extractor minimum history depth in bars."""
    return max(2, math.ceil(target_hours / profile.bar_duration_hours))


def derive_atr_window(profile: AssetProfile, target_days: float = 14.0) -> int:
    """ATR rolling window: approximate ``target_days`` of bars."""
    bars_per_day = 1440.0 / profile.tf_minutes
    return max(5, round(target_days * bars_per_day))


def derive_consecutive_penetration_bars(profile: AssetProfile, target_hours: float = 3.0) -> int:
    """Walk-forward fitness: consecutive penetration bars before line expires."""
    return max(1, math.ceil(target_hours / profile.bar_duration_hours))


def derive_forward_lookahead_bars(profile: AssetProfile, target_hours: float = 3.0) -> int:
    """Walk-forward fitness: bars ahead to confirm touch reaction."""
    return max(1, math.ceil(target_hours / profile.bar_duration_hours))


# ── Asset-stats-derived: compute from market data properties ──────────────

def derive_parallel_tol(profile: AssetProfile) -> float:
    """Pattern extractor: slope tolerance for parallel channels.

    ATR-normalized via mean_atr/mean_price. Returns a slope-per-bar threshold
    that is scale-invariant across assets.
    """
    if profile.mean_price <= 0:
        return 0.02  # safe fallback
    return max(0.005, 0.5 * profile.mean_atr / profile.mean_price)


def derive_flat_tol(profile: AssetProfile) -> float:
    """Pattern extractor: slope tolerance for flat lines."""
    if profile.mean_price <= 0:
        return 0.01
    return max(0.002, 0.25 * profile.mean_atr / profile.mean_price)


def derive_full_confidence_touches(profile: AssetProfile, role: str = "structural") -> float:
    """Full-confidence touch normalizer.

    Uses median_touch_count from fit result if available. Otherwise uses a
    TF-based heuristic: higher-frequency TFs produce more pivots per bar.
    """
    if profile.median_touch_count > 0:
        # Aim for ~75th percentile of the observed touch distribution
        return max(3.0, profile.median_touch_count * 1.5)

    # Heuristic: more bars → higher threshold
    bars_per_day = 1440.0 / profile.tf_minutes
    if role == "pattern":
        return max(4.0, min(12.0, bars_per_day * 0.35))
    return max(3.0, min(8.0, bars_per_day * 0.25))


def derive_slope_match_tol(profile: AssetProfile) -> float:
    """Temporal extractor: slope matching tolerance for ray persistence."""
    if profile.mean_slope_abs > 0:
        return max(0.01, profile.mean_slope_abs * 0.5)
    # Fallback: ATR-scale heuristic
    if profile.mean_price > 0:
        return max(0.01, profile.mean_atr / profile.mean_price)
    return 0.05


def derive_slope_accel_threshold(profile: AssetProfile) -> float:
    """Temporal extractor: minimum combined slope acceleration to emit signal."""
    if profile.slope_diff_std > 0:
        return max(0.005, profile.slope_diff_std * 0.5)
    # Fallback
    if profile.mean_price > 0:
        return max(0.005, 0.1 * profile.mean_atr / profile.mean_price)
    return 0.01


# ── Aggregate ──────────────────────────────────────────────────────────────

def compute_all_derived(profile: AssetProfile) -> dict[str, float | int]:
    """Compute every derived param in one call. Returns a flat dict."""
    return {
        "hold_bars": derive_hold_bars(profile),
        "volume_lookback": derive_volume_lookback(profile),
        "min_history": derive_min_history(profile),
        "atr_window": derive_atr_window(profile),
        "consecutive_penetration_bars": derive_consecutive_penetration_bars(profile),
        "forward_lookahead_bars": derive_forward_lookahead_bars(profile),
        "parallel_tol": derive_parallel_tol(profile),
        "flat_tol": derive_flat_tol(profile),
        "full_confidence_touches_structural": derive_full_confidence_touches(profile, role="structural"),
        "full_confidence_touches_pattern": derive_full_confidence_touches(profile, role="pattern"),
        "slope_match_tol": derive_slope_match_tol(profile),
        "slope_accel_threshold": derive_slope_accel_threshold(profile),
    }


# ── Oscillator-space aggregate ────────────────────────────────────────────

def compute_oscillator_derived(
    tf_minutes: int,
    bar_duration_hours: float,
) -> dict[str, float | int]:
    """Compute derived params safe for oscillator-space trendlines.

    Only TF-derived params (hold_bars, atr_window, etc.) are computed —
    these depend solely on bar_duration_hours, not price-scale ratios.

    Price-ratio params (parallel_tol, flat_tol, slope_match_tol, etc.)
    get fixed oscillator-appropriate fallbacks instead.
    """
    # Minimal profile stub for TF-based derivations
    _stub = AssetProfile(
        tf_minutes=tf_minutes,
        bar_duration_hours=bar_duration_hours,
        mean_atr=1.0,   # placeholder — not used for TF derivations
        mean_price=1.0,  # placeholder — not used for TF derivations
        n_bars=100,
        median_touch_count=0.0,
        mean_slope_abs=0.0,
        slope_diff_std=0.0,
        hull_width_atr_p20=0.0,
    )

    return {
        # TF-derived: safe — only use bar_duration_hours
        "hold_bars": derive_hold_bars(_stub),
        "volume_lookback": derive_volume_lookback(_stub),
        "min_history": derive_min_history(_stub),
        "atr_window": derive_atr_window(_stub),
        "consecutive_penetration_bars": derive_consecutive_penetration_bars(_stub),
        "forward_lookahead_bars": derive_forward_lookahead_bars(_stub),
        # Fixed oscillator fallbacks — NOT derived from price ratios
        "parallel_tol": 0.05,
        "flat_tol": 0.02,
        "slope_match_tol": 0.1,
        "slope_accel_threshold": 0.02,
        "full_confidence_touches_structural": 4.0,
        "full_confidence_touches_pattern": 6.0,
    }


__all__ = [
    "compute_all_derived",
    "compute_oscillator_derived",
    "derive_atr_window",
    "derive_consecutive_penetration_bars",
    "derive_flat_tol",
    "derive_forward_lookahead_bars",
    "derive_full_confidence_touches",
    "derive_hold_bars",
    "derive_min_history",
    "derive_parallel_tol",
    "derive_slope_accel_threshold",
    "derive_slope_match_tol",
    "derive_volume_lookback",
]
