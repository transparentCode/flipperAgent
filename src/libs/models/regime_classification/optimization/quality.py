"""Regime quality scoring functions for optimization.

Computes a composite quality score from 5 metrics that measure
whether regimes are separable, stable, and informative.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import calinski_harabasz_score

from libs.models.regime_classification.optimization.constants import (
    AVG_RUN_LENGTH_NORMALIZER,
    CH_SCORE_NORMALIZER,
    FORWARD_RETURN_HORIZON_LONG,
    FORWARD_RETURN_HORIZON_SHORT,
    MIN_BARS_FOR_QUALITY,
    MIN_SAMPLES_FOR_METRIC,
    MIN_SAMPLES_PER_STATE,
    RETURN_SPREAD_NORMALIZER_BPS,
    ROLLING_VOL_WINDOW,
    WEIGHT_AVG_RUN_LENGTH,
    WEIGHT_CH_SCORE,
    WEIGHT_HURST_FWD_CORR,
    WEIGHT_RETURN_SPREAD,
    WEIGHT_VOL_CALIBRATION,
)

logger = logging.getLogger("app.optimization.regime_quality")


def compute_regime_quality(
    regime_df: pd.DataFrame,
    price_df: pd.DataFrame,
) -> dict[str, float]:
    """Compute regime quality metrics from model output and price data.

    Parameters
    ----------
    regime_df : pd.DataFrame
        Output from RegimeClassificationModel.batch_evaluate(), expanded to columns.
    price_df : pd.DataFrame
        OHLCV DataFrame with at least 'close' and 'volume' columns.

    Returns
    -------
    dict[str, float]
        Metric name -> value. Higher is better for all metrics.
    """
    metrics: dict[str, float] = {}
    n = len(regime_df)

    if n < MIN_BARS_FOR_QUALITY:
        return {"composite_quality": 0.0}

    # Forward 1-bar log returns
    returns = np.log(price_df["close"] / price_df["close"].shift(1)).values
    returns[0] = 0.0

    # Forward N-bar returns
    fwd_short = price_df["close"].pct_change(FORWARD_RETURN_HORIZON_SHORT).shift(
        -FORWARD_RETURN_HORIZON_SHORT
    ).values
    fwd_long = price_df["close"].pct_change(FORWARD_RETURN_HORIZON_LONG).shift(
        -FORWARD_RETURN_HORIZON_LONG
    ).values

    # --- 1. HMM State Separation (Calinski-Harabasz) ---
    hmm_cols = [c for c in regime_df.columns if c.startswith("hmm_p_state_")]
    unique_states: np.ndarray = np.array([])
    hard_state: np.ndarray = np.array([])

    if len(hmm_cols) >= 2:
        hard_state = regime_df[hmm_cols].values.argmax(axis=1)
        unique_states = np.unique(hard_state)

        if len(unique_states) >= 2:
            vol_change = np.log(
                price_df["volume"] / price_df["volume"].shift(1)
            ).fillna(0).values
            X = np.column_stack([returns, np.abs(returns), vol_change])
            valid = ~np.isnan(X).any(axis=1) & np.isfinite(X).all(axis=1)
            if valid.sum() > len(unique_states):
                try:
                    metrics["ch_score"] = calinski_harabasz_score(X[valid], hard_state[valid])
                except Exception:
                    metrics["ch_score"] = 0.0
            else:
                metrics["ch_score"] = 0.0
        else:
            metrics["ch_score"] = 0.0
    else:
        metrics["ch_score"] = 0.0

    # --- 2. Transition Stability (avg bars in same state) ---
    if len(hard_state) > 0 and len(unique_states) >= 2:
        state_changes = np.diff(hard_state) != 0
        runs = np.split(np.arange(len(hard_state)), np.where(state_changes)[0] + 1)
        run_lengths = [len(r) for r in runs if len(r) > 0]
        metrics["avg_run_length"] = float(np.mean(run_lengths)) if run_lengths else 1.0
        metrics["median_run_length"] = float(np.median(run_lengths)) if run_lengths else 1.0
    else:
        metrics["avg_run_length"] = 1.0
        metrics["median_run_length"] = 1.0

    # --- 3. Conditional Return Spread ---
    if len(hard_state) > 0 and len(unique_states) >= 2:
        state_returns: dict[int, float] = {}
        for s in unique_states:
            mask = hard_state == s
            if mask.sum() > MIN_SAMPLES_PER_STATE:
                state_returns[int(s)] = float(np.nanmean(returns[mask]))
        if len(state_returns) >= 2:
            spreads = []
            states_list = list(state_returns.keys())
            for i in range(len(states_list)):
                for j in range(i + 1, len(states_list)):
                    spreads.append(abs(state_returns[states_list[i]] - state_returns[states_list[j]]))
            metrics["return_spread"] = float(np.mean(spreads)) * 1e4  # in bps
        else:
            metrics["return_spread"] = 0.0
    else:
        metrics["return_spread"] = 0.0

    # --- 4. Hurst-Return Rank Correlation ---
    hurst = regime_df.get("hurst", pd.Series(np.full(n, 0.5)))
    valid_hurst = ~np.isnan(fwd_short) & ~np.isnan(hurst.values) & np.isfinite(fwd_short)
    if valid_hurst.sum() > MIN_SAMPLES_FOR_METRIC:
        rho, _ = stats.spearmanr(hurst.values[valid_hurst], np.abs(fwd_short[valid_hurst]))
        metrics["hurst_fwd_corr"] = abs(float(rho))
    else:
        metrics["hurst_fwd_corr"] = 0.0

    # --- 5. Vol Percentile Calibration ---
    vol_pct = regime_df.get("vol_percentile", pd.Series(np.full(n, 50.0)))
    fwd_vol = price_df["close"].pct_change().rolling(ROLLING_VOL_WINDOW).std().shift(
        -ROLLING_VOL_WINDOW
    ).values
    valid_vol = ~np.isnan(fwd_vol) & ~np.isnan(vol_pct.values) & np.isfinite(fwd_vol)
    if valid_vol.sum() > MIN_SAMPLES_FOR_METRIC:
        rho, _ = stats.spearmanr(vol_pct.values[valid_vol], fwd_vol[valid_vol])
        metrics["vol_calibration"] = float(rho)
    else:
        metrics["vol_calibration"] = 0.0

    # --- 6. Composite quality score ---
    metrics["composite_quality"] = (
        WEIGHT_CH_SCORE * min(metrics["ch_score"] / CH_SCORE_NORMALIZER, 1.0)
        + WEIGHT_AVG_RUN_LENGTH * min(metrics["avg_run_length"] / AVG_RUN_LENGTH_NORMALIZER, 1.0)
        + WEIGHT_RETURN_SPREAD * min(metrics["return_spread"] / RETURN_SPREAD_NORMALIZER_BPS, 1.0)
        + WEIGHT_HURST_FWD_CORR * metrics["hurst_fwd_corr"]
        + WEIGHT_VOL_CALIBRATION * max(metrics["vol_calibration"], 0.0)
    )

    return metrics
