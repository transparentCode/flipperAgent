"""Hurst adapter for RegimeProbV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_classification.config import (
    scale_bars_for_timeframe,
    timeframe_scaled_config,
)
from libs.models.regime_classification.kernels.hurst import rolling_hurst


@dataclass(frozen=True)
class HurstAdapterConfig:
    """Configuration for the Hurst adapter."""

    lookback: int | None = None
    min_periods: int | None = None
    stability_window: int | None = None


@dataclass(frozen=True)
class HurstAdapterOutput:
    """Aligned Hurst feature frame and diagnostics."""

    frame: pd.DataFrame
    diagnostics: dict[str, Any]


def compute_hurst_features(
    df: pd.DataFrame,
    *,
    timeframe: str = "1h",
    config: HurstAdapterConfig | None = None,
) -> HurstAdapterOutput:
    """Compute point-in-time Hurst features aligned to the input index."""
    cfg = _resolve_config(timeframe, config)
    index = df.index.copy()
    neutral = _neutral_frame(index)

    if df.empty:
        return HurstAdapterOutput(frame=neutral, diagnostics={"status": "empty_input"})
    if "close" not in df.columns:
        return HurstAdapterOutput(frame=neutral, diagnostics={"status": "missing_close"})

    close = pd.to_numeric(df["close"], errors="coerce").astype(float)
    if close.isna().any() or (close <= 0).any():
        return HurstAdapterOutput(
            frame=neutral,
            diagnostics={"status": "invalid_close_series", "rows": int(len(df))},
        )

    prices = close.to_numpy(dtype=float)
    if len(prices) < cfg.min_periods + 1:
        return HurstAdapterOutput(
            frame=neutral,
            diagnostics={
                "status": "insufficient_data",
                "rows": int(len(df)),
                "min_periods": int(cfg.min_periods),
            },
        )

    hurst = rolling_hurst(
        prices,
        lookback=cfg.lookback,
        min_periods=cfg.min_periods,
    ).astype(float)
    valid = np.arange(len(df)) >= int(cfg.min_periods)
    hurst_trend_bias = np.clip((hurst - 0.5) / 0.25, 0.0, 1.0)
    hurst_mr_bias = np.clip((0.5 - hurst) / 0.25, 0.0, 1.0)
    rolling_std = (
        pd.Series(hurst, index=index)
        .rolling(window=cfg.stability_window, min_periods=2)
        .std(ddof=0)
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    hurst_stability = np.clip(1.0 - rolling_std / 0.20, 0.0, 1.0)
    hurst_trend_bias = np.where(valid, hurst_trend_bias, 0.0)
    hurst_mr_bias = np.where(valid, hurst_mr_bias, 0.0)
    hurst_stability = np.where(valid, hurst_stability, 0.0)

    frame = pd.DataFrame(
        {
            "hurst": hurst.astype(float),
            "hurst_trend_bias": hurst_trend_bias.astype(float),
            "hurst_mr_bias": hurst_mr_bias.astype(float),
            "hurst_stability": hurst_stability.astype(float),
        },
        index=index,
    )
    diagnostics = {
        "status": "ok",
        "rows": int(len(df)),
        "lookback": int(cfg.lookback),
        "min_periods": int(cfg.min_periods),
        "stability_window": int(cfg.stability_window),
        "mean_hurst": float(np.mean(hurst)),
    }
    return HurstAdapterOutput(frame=frame, diagnostics=diagnostics)


def _resolve_config(timeframe: str, config: HurstAdapterConfig | None) -> HurstAdapterConfig:
    base = timeframe_scaled_config(timeframe).hmm
    raw = config or HurstAdapterConfig()
    lookback = base.hurst_lookback if raw.lookback is None else int(raw.lookback)
    min_periods = min(50, lookback // 2) if raw.min_periods is None else int(raw.min_periods)
    stability_window = (
        scale_bars_for_timeframe(24, timeframe, floor=5)
        if raw.stability_window is None
        else int(raw.stability_window)
    )
    return HurstAdapterConfig(
        lookback=int(lookback),
        min_periods=max(int(min_periods), 2),
        stability_window=max(int(stability_window), 2),
    )


def _neutral_frame(index: pd.Index) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "hurst": np.full(len(index), 0.5, dtype=float),
            "hurst_trend_bias": np.zeros(len(index), dtype=float),
            "hurst_mr_bias": np.zeros(len(index), dtype=float),
            "hurst_stability": np.zeros(len(index), dtype=float),
        },
        index=index,
    )


__all__ = [
    "HurstAdapterConfig",
    "HurstAdapterOutput",
    "compute_hurst_features",
]
