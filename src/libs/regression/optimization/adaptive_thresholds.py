"""
Data-driven constraint thresholds derived from asset OHLCV.

Instead of manually tuning min_direction_floor, min_sharpe_floor, coverage_cap,
derive them per-asset per-timeframe from the actual price series statistical
properties (Hurst exponent, rolling Sharpe distribution, empirical band coverage).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.regression.optimization.constants import BARS_PER_YEAR, DEFAULT_BARS_PER_YEAR

logger = logging.getLogger("app.regression.optimization")


@dataclass
class DerivedThresholds:
    """Constraint thresholds derived from OHLCV data."""
    min_direction_floor: float
    min_sharpe_floor: float
    coverage_cap: float
    # Diagnostic fields for logging / auditability
    hurst_exponent: float
    hurst_cv: float              # CV of rolling Hurst — high = regime-mixed
    hurst_estimator: str         # which method was used
    bah_sharpe_5pct: float
    empirical_2sigma_coverage: float


def derive_thresholds(
    df: pd.DataFrame,
    timeframe: str,
    direction_floor_range: tuple[float, float] = (0.40, 0.55),
    sharpe_floor_min: float = -5.0,
    coverage_cap_max: float = 0.95,
) -> DerivedThresholds:
    """
    Derive MOTPE constraint thresholds from asset OHLCV data.

    Args:
        df: OHLCV DataFrame with 'close' column.
        timeframe: e.g. '1h', '4h', '1d'.
        direction_floor_range: (min, max) clamp for derived direction floor.
        sharpe_floor_min: absolute minimum for sharpe floor.
        coverage_cap_max: absolute maximum for coverage cap.

    Returns:
        DerivedThresholds with per-asset per-tf constraint values.
    """
    closes = df["close"].values.astype(float)
    returns = pd.Series(closes).pct_change().dropna().values
    bars_per_year = BARS_PER_YEAR.get(timeframe, DEFAULT_BARS_PER_YEAR)

    # 1. Direction floor from Hurst exponent (R/S estimator)
    hurst = _hurst_rs(returns)
    hurst_cv = _rolling_hurst_cv(returns)

    # H=0.50 → random walk → floor=0.45 (don't expect above random)
    # H=0.60 → trending  → floor=0.50 (directional signal exists)
    # H=0.40 → mean-rev  → floor=0.42 (predictable but differently)
    # Linear map: floor = 0.35 + 0.25*H, clamped to range
    raw_dir_floor = 0.35 + 0.25 * hurst

    # Soften floor when Hurst is unstable (high CV = regime-mixed data)
    # CV > 0.15 → the Hurst estimate is unreliable, pull floor toward range midpoint
    if hurst_cv > 0.15:
        midpoint = sum(direction_floor_range) / 2
        softening = min((hurst_cv - 0.15) / 0.15, 1.0)  # 0→1 as CV goes 0.15→0.30
        raw_dir_floor = raw_dir_floor * (1 - softening) + midpoint * softening

    direction_floor = float(np.clip(raw_dir_floor, *direction_floor_range))

    # 2. Sharpe floor from rolling BAH Sharpe distribution
    bah_sharpe_5pct = _rolling_sharpe_percentile(returns, bars_per_year, percentile=5)
    # Use 5th percentile as floor — what's the worst this asset naturally does
    sharpe_floor = max(bah_sharpe_5pct, sharpe_floor_min)

    # 3. Coverage cap from empirical Bollinger coverage at 2σ
    empirical_cov = _empirical_bollinger_coverage(closes, window=100, n_sigma=2.0)
    # Cap slightly below empirical (98% of it) — don't reward trivially achieved coverage
    coverage_cap = min(empirical_cov * 0.98, coverage_cap_max)
    # Floor at 0.70 — below this is pathological data
    coverage_cap = max(coverage_cap, 0.70)

    result = DerivedThresholds(
        min_direction_floor=round(direction_floor, 4),
        min_sharpe_floor=round(sharpe_floor, 4),
        coverage_cap=round(coverage_cap, 4),
        hurst_exponent=round(hurst, 4),
        hurst_cv=round(hurst_cv, 4),
        hurst_estimator="R/S",
        bah_sharpe_5pct=round(bah_sharpe_5pct, 4),
        empirical_2sigma_coverage=round(empirical_cov, 4),
    )

    logger.info(
        f"Derived thresholds (estimator={result.hurst_estimator}): "
        f"direction_floor={result.min_direction_floor} "
        f"(H={result.hurst_exponent}, CV={result.hurst_cv}), "
        f"sharpe_floor={result.min_sharpe_floor} (BAH_5pct={result.bah_sharpe_5pct}), "
        f"coverage_cap={result.coverage_cap} (empirical_2σ={result.empirical_2sigma_coverage})"
    )

    return result


def _hurst_rs(returns: np.ndarray, max_lags: int = 20) -> float:
    """
    Rescaled range (R/S) Hurst exponent estimate.

    H > 0.5: trending (persistent)
    H ≈ 0.5: random walk
    H < 0.5: mean-reverting (anti-persistent)
    """
    n = len(returns)
    if n < 100:
        return 0.50  # Insufficient data — assume random walk

    lags = range(10, min(max_lags + 1, n // 4))
    rs_values = []
    lag_values = []

    for lag in lags:
        n_chunks = n // lag
        if n_chunks < 2:
            continue

        rs_chunk = []
        for i in range(n_chunks):
            chunk = returns[i * lag : (i + 1) * lag]
            mean_chunk = np.mean(chunk)
            cumdev = np.cumsum(chunk - mean_chunk)
            r = np.max(cumdev) - np.min(cumdev)
            s = np.std(chunk, ddof=1)
            if s > 1e-10:
                rs_chunk.append(r / s)

        if rs_chunk:
            rs_values.append(np.mean(rs_chunk))
            lag_values.append(lag)

    if len(rs_values) < 3:
        return 0.50

    # log-log regression: log(R/S) = H * log(lag) + c
    log_lags = np.log(lag_values)
    log_rs = np.log(rs_values)

    # Simple OLS
    n_pts = len(log_lags)
    sum_x = np.sum(log_lags)
    sum_y = np.sum(log_rs)
    sum_xy = np.sum(log_lags * log_rs)
    sum_x2 = np.sum(log_lags ** 2)

    denom = n_pts * sum_x2 - sum_x ** 2
    if abs(denom) < 1e-10:
        return 0.50

    hurst = float((n_pts * sum_xy - sum_x * sum_y) / denom)
    return float(np.clip(hurst, 0.0, 1.0))


def _rolling_hurst_cv(returns: np.ndarray, n_windows: int = 5) -> float:
    """
    Compute coefficient of variation of Hurst estimates across sub-windows.

    High CV (>0.15) indicates regime-mixed data where the aggregate Hurst
    is unreliable. Used to soften the direction floor.
    """
    n = len(returns)
    window_size = n // n_windows
    if window_size < 200:
        return 0.0  # Not enough data for meaningful sub-window analysis

    hurst_values = []
    for i in range(n_windows):
        start = i * window_size
        end = start + window_size
        h = _hurst_rs(returns[start:end])
        hurst_values.append(h)

    if len(hurst_values) < 3:
        return 0.0

    mean_h = np.mean(hurst_values)
    if abs(mean_h) < 1e-10:
        return 1.0

    cv = float(np.std(hurst_values, ddof=1) / abs(mean_h))
    return cv


def _rolling_sharpe_percentile(
    returns: np.ndarray,
    bars_per_year: float,
    percentile: int = 5,
    window_fraction: float = 0.25,
) -> float:
    """Compute the Nth percentile of rolling annualized Sharpe ratios."""
    ann_factor = np.sqrt(bars_per_year)
    window = max(int(bars_per_year * window_fraction), 50)

    if len(returns) < window + 10:
        # Not enough data — return conservative estimate
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        if std_r < 1e-10:
            return 0.0
        return float((mean_r / std_r) * ann_factor - 2.0)  # BAH - 2 sigma

    ret_series = pd.Series(returns)
    rolling_mean = ret_series.rolling(window).mean()
    rolling_std = ret_series.rolling(window).std(ddof=1)

    # Avoid division by zero
    valid = rolling_std > 1e-10
    rolling_sharpe = pd.Series(np.nan, index=ret_series.index)
    rolling_sharpe[valid] = (rolling_mean[valid] / rolling_std[valid]) * ann_factor

    sharpe_values = rolling_sharpe.dropna().values
    if len(sharpe_values) < 10:
        return -2.0

    return float(np.percentile(sharpe_values, percentile))


def _empirical_bollinger_coverage(
    closes: np.ndarray,
    window: int = 100,
    n_sigma: float = 2.0,
) -> float:
    """Compute empirical coverage of Bollinger bands at n_sigma."""
    if len(closes) < window + 10:
        return 0.95  # Insufficient data — assume normal

    close_series = pd.Series(closes)
    ma = close_series.rolling(window).mean()
    std = close_series.rolling(window).std(ddof=1)

    upper = ma + n_sigma * std
    lower = ma - n_sigma * std

    valid = ma.notna()
    if valid.sum() < 10:
        return 0.95

    inside = (close_series[valid] >= lower[valid]) & (close_series[valid] <= upper[valid])
    return float(inside.mean())
