"""Offline data calibration for RegimeClassification frozen params.

Calibrates asset/timeframe-specific values for:
- bcpd_hazard_lambda: from empirical changepoint run-length distribution
- hmm_crisis_vol_mult: from the asset's rolling vol distribution

These are computed offline and frozen before Optuna runs.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.constants import (
    CALIBRATION_CP_MIN_DISTANCE,
    CALIBRATION_CP_MODEL,
    CALIBRATION_CP_PENALTY,
    CALIBRATION_VOL_LOOKBACK,
    CALIBRATION_VOL_QUANTILE,
)

logger = logging.getLogger("app.optimization.regime_calibration")


def calibrate_hazard_lambda(
    close: pd.Series,
    *,
    min_distance: int = CALIBRATION_CP_MIN_DISTANCE,
    penalty: str = CALIBRATION_CP_PENALTY,
    model: str = CALIBRATION_CP_MODEL,
) -> float:
    """Estimate BCPD hazard_lambda from historical changepoint run lengths.

    Uses the `ruptures` library for offline changepoint detection (PELT).
    Returns the median run length between detected changepoints, clamped
    to the hyperparameter_schema range [50, 500].

    Falls back to the default (150.0) if calibration fails.
    """
    try:
        import ruptures as rpt
    except ImportError:
        logger.warning("ruptures not installed — using default hazard_lambda=150.0")
        return 150.0

    log_returns = np.log(close / close.shift(1)).dropna().values
    if len(log_returns) < 100:
        logger.warning("Insufficient data for calibration — using default hazard_lambda=150.0")
        return 150.0

    try:
        algo = rpt.Pelt(model=model, min_size=min_distance).fit(log_returns)
        changepoints = algo.predict(pen=np.std(log_returns) * np.sqrt(np.log(len(log_returns))))

        # changepoints includes the final index — compute run lengths
        boundaries = [0] + changepoints
        run_lengths = np.diff(boundaries)
        run_lengths = run_lengths[run_lengths > 0]

        if len(run_lengths) < 3:
            logger.info("Too few changepoints detected — using default hazard_lambda=150.0")
            return 150.0

        median_rl = float(np.median(run_lengths))
        # Clamp to schema range
        clamped = max(50.0, min(500.0, median_rl))
        logger.info(
            f"Calibrated hazard_lambda: median_run_length={median_rl:.1f}, "
            f"clamped={clamped:.1f}, n_changepoints={len(changepoints)}"
        )
        return clamped

    except Exception as exc:
        logger.warning(f"Changepoint calibration failed: {exc} — using default hazard_lambda=150.0")
        return 150.0


def calibrate_crisis_vol_mult(
    close: pd.Series,
    *,
    vol_lookback: int = CALIBRATION_VOL_LOOKBACK,
    quantile: float = CALIBRATION_VOL_QUANTILE,
) -> float:
    """Derive hmm_crisis_vol_mult from the asset's rolling vol distribution.

    Computes: p95(rolling_vol) / median(rolling_vol).
    Clamped to [1.0, 5.0] range.

    Falls back to 2.0 if calibration fails.
    """
    log_returns = np.log(close / close.shift(1)).dropna()
    if len(log_returns) < vol_lookback * 2:
        logger.warning("Insufficient data for vol calibration — using default crisis_vol_mult=2.0")
        return 2.0

    rolling_vol = log_returns.rolling(vol_lookback).std().dropna()
    if rolling_vol.empty:
        return 2.0

    p_high = float(rolling_vol.quantile(quantile))
    median_vol = float(rolling_vol.median())

    if median_vol <= 0:
        return 2.0

    mult = p_high / median_vol
    clamped = max(1.0, min(5.0, mult))
    logger.info(
        f"Calibrated crisis_vol_mult: p{int(quantile*100)}={p_high:.6f}, "
        f"median={median_vol:.6f}, ratio={mult:.2f}, clamped={clamped:.2f}"
    )
    return clamped


def calibrate_frozen_overrides(close: pd.Series) -> dict[str, float]:
    """Run all calibrations and return a frozen_overrides dict.

    This dict can be passed directly to RegimeClassificationModel(frozen_overrides=...).
    """
    return {
        "bcpd_hazard_lambda": calibrate_hazard_lambda(close),
        "hmm_crisis_vol_mult": calibrate_crisis_vol_mult(close),
    }
