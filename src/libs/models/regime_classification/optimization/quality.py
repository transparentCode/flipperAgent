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

from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)

logger = logging.getLogger("app.optimization.regime_quality")


def compute_regime_quality(
    regime_df: pd.DataFrame,
    price_df: pd.DataFrame,
    settings: dict | None = None,
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
    cfg = settings or load_regime_optimization_settings()
    quality_cfg = cfg.get("quality", {})
    weights = quality_cfg.get("weights", {})
    normalizers = quality_cfg.get("normalizers", {})

    if n < int(quality_cfg.get("min_bars_for_quality", 500)):
        return {"composite_quality": 0.0}

    # Forward 1-bar log returns
    returns = np.log(price_df["close"] / price_df["close"].shift(1)).to_numpy(
        copy=True
    )
    returns[0] = 0.0

    # Forward N-bar returns
    fwd_short_horizon = int(quality_cfg.get("forward_return_horizon_short", 10))
    fwd_long_horizon = int(quality_cfg.get("forward_return_horizon_long", 20))
    fwd_short = price_df["close"].pct_change(fwd_short_horizon).shift(
        -fwd_short_horizon
    ).values
    fwd_long = price_df["close"].pct_change(fwd_long_horizon).shift(
        -fwd_long_horizon
    ).values
    _ = fwd_long  # retained for future multi-horizon diagnostics

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
            if mask.sum() > int(quality_cfg.get("min_samples_per_state", 10)):
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
    min_samples_for_metric = int(quality_cfg.get("min_samples_for_metric", 50))
    if valid_hurst.sum() > min_samples_for_metric:
        rho, _ = stats.spearmanr(hurst.values[valid_hurst], np.abs(fwd_short[valid_hurst]))
        metrics["hurst_fwd_corr"] = abs(float(rho))
    else:
        metrics["hurst_fwd_corr"] = 0.0

    # --- 5. Vol Percentile Calibration ---
    vol_pct = regime_df.get("vol_percentile", pd.Series(np.full(n, 50.0)))
    rolling_vol_window = int(quality_cfg.get("rolling_vol_window", 5))
    fwd_vol = price_df["close"].pct_change().rolling(rolling_vol_window).std().shift(
        -rolling_vol_window
    ).values
    valid_vol = ~np.isnan(fwd_vol) & ~np.isnan(vol_pct.values) & np.isfinite(fwd_vol)
    if valid_vol.sum() > min_samples_for_metric:
        rho, _ = stats.spearmanr(vol_pct.values[valid_vol], fwd_vol[valid_vol])
        metrics["vol_calibration"] = float(rho)
    else:
        metrics["vol_calibration"] = 0.0

    # --- 6. Composite quality score ---
    metrics["composite_quality"] = (
        float(weights.get("ch_score", 0.25))
        * min(metrics["ch_score"] / float(normalizers.get("ch_score", 100.0)), 1.0)
        + float(weights.get("avg_run_length", 0.20))
        * min(
            metrics["avg_run_length"]
            / float(normalizers.get("avg_run_length", 20.0)),
            1.0,
        )
        + float(weights.get("return_spread", 0.20))
        * min(
            metrics["return_spread"]
            / float(normalizers.get("return_spread_bps", 5.0)),
            1.0,
        )
        + float(weights.get("hurst_fwd_corr", 0.20)) * metrics["hurst_fwd_corr"]
        + float(weights.get("vol_calibration", 0.15))
        * max(metrics["vol_calibration"], 0.0)
    )

    return metrics
