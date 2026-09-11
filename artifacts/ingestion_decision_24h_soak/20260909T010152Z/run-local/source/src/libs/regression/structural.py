"""Standalone exact structural log-price regression estimator."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config.schema import ResolvedPipelineConfig
from .contracts.structural import StructuralRegressionEstimate
from .temporal import market_time_bounds, normalize_timestamps, timeframe_seconds

STRUCTURAL_ESTIMATOR_ID = "theil_sen_log_price_all_pairs_v1"
_MACHINE_EPSILON = np.finfo(np.float64).eps


def _fit_all_pairs_theil_sen(
    elapsed_hours: np.ndarray, log_prices: np.ndarray
) -> tuple[float, float]:
    """Fit an unweighted Theil-Sen line using every ordered pair."""
    n = len(log_prices)
    if n < 2:
        raise ValueError("structural regression requires at least two observations")

    first, second = np.triu_indices(n, k=1)
    pair_delta_x = elapsed_hours[second] - elapsed_hours[first]
    pair_slopes = (log_prices[second] - log_prices[first]) / pair_delta_x
    if not np.all(np.isfinite(pair_slopes)):
        raise ValueError("structural regression pair slopes must be finite")

    slope = float(np.median(pair_slopes))
    intercept = float(np.median(log_prices - slope * elapsed_hours))
    if not np.isfinite(slope) or not np.isfinite(intercept):
        raise ValueError("structural regression fit must be finite")
    return slope, intercept


def _fit_quality(log_prices: np.ndarray, residuals: np.ndarray) -> tuple[float, float]:
    residual_mad_log = float(
        np.median(np.abs(residuals - np.median(residuals)))
    )
    price_mad_log = float(
        np.median(np.abs(log_prices - np.median(log_prices)))
    )

    if price_mad_log <= _MACHINE_EPSILON:
        fit_quality = 1.0 if residual_mad_log <= _MACHINE_EPSILON else 0.0
    else:
        fit_quality = float(
            np.clip(1.0 - residual_mad_log / price_mad_log, 0.0, 1.0)
        )
    return residual_mad_log, fit_quality


def compute_structural_estimate(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    config: ResolvedPipelineConfig,
) -> StructuralRegressionEstimate:
    """Compute the causal exact structural estimate for the final window."""
    if config.asset != asset:
        raise ValueError(
            f"structural config asset mismatch: {config.asset!r} != {asset!r}"
        )
    if config.timeframe != timeframe:
        raise ValueError(
            "structural config timeframe mismatch: "
            f"{config.timeframe!r} != {timeframe!r}"
        )

    window = int(config.window_size)
    if window < 2:
        raise ValueError("structural regression window_size must be at least 2")
    if len(df) < window:
        raise ValueError(
            f"structural regression requires {window} rows; received {len(df)}"
        )

    selected = df.iloc[-window:]
    normalized_timestamps = normalize_timestamps(selected.index)
    close = selected["close"].to_numpy(dtype=np.float64, copy=False)
    if not np.all(np.isfinite(close)):
        raise ValueError("structural regression close values must be finite")
    if np.any(close <= 0.0):
        raise ValueError("structural regression close values must be positive")

    elapsed_hours = (
        normalized_timestamps - normalized_timestamps[0]
    ) / np.timedelta64(1, "h")
    elapsed_hours = np.asarray(elapsed_hours, dtype=np.float64)
    log_prices = np.log(close)
    if not np.all(np.isfinite(log_prices)):
        raise ValueError("structural regression log prices must be finite")

    slope, intercept = _fit_all_pairs_theil_sen(elapsed_hours, log_prices)
    fitted_log_prices = intercept + slope * elapsed_hours
    residuals = log_prices - fitted_log_prices
    residual_mad_log, fit_quality = _fit_quality(log_prices, residuals)
    if not np.isfinite(residual_mad_log) or not np.isfinite(fit_quality):
        raise ValueError("structural regression quality metrics must be finite")

    center_log = float(fitted_log_prices[-1])
    if not np.isfinite(center_log):
        raise ValueError("structural regression center must be finite")
    center_price = float(np.exp(center_log))
    if not np.isfinite(center_price) or center_price <= 0.0:
        raise ValueError("structural regression center price must be finite")

    timeframe_seconds_value = timeframe_seconds(timeframe)
    window_started_at, timestamp, observed_through = market_time_bounds(
        normalized_timestamps, timeframe_seconds_value
    )
    return StructuralRegressionEstimate(
        asset=asset,
        timeframe=timeframe,
        window_started_at=window_started_at,
        timestamp=timestamp,
        observed_through=observed_through,
        source_config_hash=config.config_hash,
        estimator_id=STRUCTURAL_ESTIMATOR_ID,
        window_size=window,
        slope_log_per_hour=slope,
        center_price=center_price,
        residual_mad_log=residual_mad_log,
        fit_quality=fit_quality,
    )
