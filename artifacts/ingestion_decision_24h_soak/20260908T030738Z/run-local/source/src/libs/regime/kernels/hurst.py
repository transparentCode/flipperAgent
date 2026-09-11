"""
Online Hurst Exponent Estimator.
================================
Rolling R/S (Rescaled Range) Hurst exponent for regime classification.

H > 0.5 → trending / persistent
H ≈ 0.5 → random walk
H < 0.5 → mean-reverting / anti-persistent

Used as an additional HMM feature to improve trending vs non-trending
classification, especially for non-crypto assets (FX, stocks) where
log_return + log_vol alone is insufficient.

Non-hindsight: each value uses only data up to the current bar.
"""

from __future__ import annotations

import numpy as np


def rolling_hurst(
    prices: np.ndarray,
    lookback: int = 100,
    min_periods: int = 50,
) -> np.ndarray:
    """
    Compute rolling Hurst exponent via Rescaled Range (R/S) analysis.

    Vectorized: builds all full-length windows at once via stride tricks,
    then batches the R/S computation across all windows simultaneously
    with numpy ops. Only the first ~min_periods early bars fall back to
    a scalar loop (at most lookback - min_periods iterations).

    Parameters
    ----------
    prices    : 1-D array of close prices
    lookback  : window size for R/S computation
    min_periods : minimum periods before emitting a value (else 0.5)

    Returns
    -------
    hurst : 1-D array same length as prices, values in ~[0, 1]
    """
    n = len(prices)
    hurst = np.full(n, 0.5)

    if n < min_periods + 1:
        return hurst

    log_ret = np.diff(np.log(prices + 1e-10))  # length n-1
    T = len(log_ret)

    # Sub-window sizes: powers of 2 up to lookback // 2
    sizes = []
    s = 8
    while s <= lookback // 2:
        sizes.append(s)
        s *= 2
    if len(sizes) < 2:
        return hurst

    # ------------------------------------------------------------------
    # Fast path: fully-populated windows (exactly lookback bars each)
    # ------------------------------------------------------------------
    if T >= lookback:
        n_windows = T - lookback + 1

        # Build (n_windows, lookback) sliding window view via stride tricks,
        # then copy to C-contiguous layout so downstream reshapes work.
        stride = log_ret.strides[0]
        _view = np.lib.stride_tricks.as_strided(
            log_ret,
            shape=(n_windows, lookback),
            strides=(stride, stride),
        )
        windows = np.array(_view)  # (n_windows, lookback) — contiguous copy

        K = len(sizes)
        log_x = np.log(np.array(sizes, dtype=np.float64))  # (K,)
        log_rs_mat = np.full((K, n_windows), np.nan)       # (K, N)

        for k, sz in enumerate(sizes):
            n_chunks = lookback // sz
            usable = n_chunks * sz

            # Reshape to (n_windows, n_chunks, sz) — all chunks for all windows
            w = windows[:, :usable].reshape(n_windows, n_chunks, sz)

            # Linear detrending: remove linear trend per chunk to reduce
            # false persistence from price drift (standard R/S best practice)
            t_axis = np.arange(sz, dtype=np.float64)
            t_mean = t_axis.mean()
            t_var = ((t_axis - t_mean) ** 2).sum()
            if t_var > 1e-10:
                # Vectorised linear detrend: slope = cov(t, w) / var(t)
                w_mean = w.mean(axis=2, keepdims=True)               # (N, C, 1)
                slope = ((t_axis - t_mean) * (w - w_mean)).sum(axis=2, keepdims=True) / t_var
                w_detrended = w - (slope * (t_axis - t_mean) + w_mean)
            else:
                w_detrended = w - w.mean(axis=2, keepdims=True)

            cumdev = np.cumsum(w_detrended, axis=2)                  # (N, C, S)
            R = cumdev.max(axis=2) - cumdev.min(axis=2)              # (N, C)
            S = w.std(axis=2, ddof=1)                                # (N, C)

            rs = np.where(S > 1e-10, R / S, np.nan)                 # (N, C)
            mean_rs = np.nanmean(rs, axis=1)                         # (N,)
            log_rs_mat[k] = np.where(mean_rs > 0, np.log(mean_rs), np.nan)

        # Count valid sizes per window; fill rare NaN with per-size median
        valid_sizes = np.isfinite(log_rs_mat).sum(axis=0)       # (N,)
        for k in range(K):
            bad = ~np.isfinite(log_rs_mat[k])
            if bad.any():
                fill = float(np.nanmedian(log_rs_mat[k]))
                log_rs_mat[k, bad] = fill if np.isfinite(fill) else 0.0

        # Vectorised OLS: H = cov(log_x, log_rs) / var(log_x) per window
        x_c = log_x - log_x.mean()                              # (K,)
        ss_xx = (x_c ** 2).sum()

        if ss_xx > 1e-10:
            y_c = log_rs_mat - log_rs_mat.mean(axis=0)          # (K, N)
            h_vals = (x_c[:, np.newaxis] * y_c).sum(axis=0) / ss_xx  # (N,)
            h_vals = np.clip(h_vals, 0.01, 0.99)
            h_vals = np.where(
                (valid_sizes >= 2) & np.isfinite(h_vals),
                h_vals,
                0.5,
            )
            # Window index w maps to price index w + lookback
            hurst[lookback : lookback + n_windows] = h_vals

    # ------------------------------------------------------------------
    # Slow path: partial windows for early bars (< lookback bars available)
    # At most (lookback - min_periods) iterations — ~50 for default params.
    # ------------------------------------------------------------------
    for i in range(min_periods, min(lookback - 1, T)):
        window = log_ret[: i + 1]
        hurst[i + 1] = _rs_hurst(window)

    return hurst


def _rs_hurst(returns: np.ndarray) -> float:
    """
    Single-window R/S Hurst exponent.

    Uses sub-windows of sizes [8, 16, 32, ...] up to len(returns) / 2.
    Fits log(R/S) vs log(n) via OLS to estimate H.
    """
    n = len(returns)
    if n < 16:
        return 0.5

    sizes = []
    s = 8
    while s <= n // 2:
        sizes.append(s)
        s *= 2
    if len(sizes) < 2:
        return 0.5

    log_sizes = []
    log_rs = []

    for size in sizes:
        n_chunks = n // size
        if n_chunks < 1:
            continue
        rs_values = []
        for chunk_idx in range(n_chunks):
            chunk = returns[chunk_idx * size : (chunk_idx + 1) * size]
            mean = chunk.mean()
            dev = chunk - mean
            cumdev = np.cumsum(dev)
            r = cumdev.max() - cumdev.min()
            s = chunk.std(ddof=1)
            if s > 1e-10:
                rs_values.append(r / s)
        if rs_values:
            log_sizes.append(np.log(size))
            log_rs.append(np.log(np.mean(rs_values)))

    if len(log_sizes) < 2:
        return 0.5

    # OLS: log(R/S) = H * log(n) + c
    x = np.array(log_sizes)
    y = np.array(log_rs)
    x_mean = x.mean()
    y_mean = y.mean()
    ss_xx = ((x - x_mean) ** 2).sum()
    if ss_xx < 1e-10:
        return 0.5
    h = float(((x - x_mean) * (y - y_mean)).sum() / ss_xx)

    return max(0.01, min(0.99, h))
