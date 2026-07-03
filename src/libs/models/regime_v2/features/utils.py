"""Shared numeric helpers for RegimeV2 feature kernels."""

from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-12


def clip01(value):
    if isinstance(value, pd.Series):
        return value.clip(0.0, 1.0)
    return max(0.0, min(float(value), 1.0))


def clip11(value):
    if isinstance(value, pd.Series):
        return value.clip(-1.0, 1.0)
    return max(-1.0, min(float(value), 1.0))


def safe_div(num, den):
    return num / (den.replace(0.0, np.nan) if isinstance(den, pd.Series) else den + EPS)


def true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Percentile rank of the latest value inside each rolling window."""
    window = max(int(window), 2)

    def _pct(values: np.ndarray) -> float:
        finite = values[np.isfinite(values)]
        if len(finite) == 0:
            return 50.0
        return float((finite <= finite[-1]).mean() * 100.0)

    return series.rolling(window, min_periods=max(5, min(window, 20))).apply(_pct, raw=True).fillna(50.0)


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    window = max(int(window), 2)
    mean = series.rolling(window, min_periods=max(5, min(window, 20))).mean()
    std = series.rolling(window, min_periods=max(5, min(window, 20))).std(ddof=0)
    return ((series - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)


def signed_tanh(series: pd.Series, scale: float = 1.0) -> pd.Series:
    scale = max(float(scale), EPS)
    return pd.Series(np.tanh(series.astype(float) / scale), index=series.index)


__all__ = [
    "EPS",
    "clip01",
    "clip11",
    "rolling_percentile",
    "rolling_zscore",
    "safe_div",
    "signed_tanh",
    "true_range",
]
