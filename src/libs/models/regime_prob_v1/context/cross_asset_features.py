"""Vectorized cross-asset features for RegimeProbV1 external context."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def build_cross_asset_feature_frame(
    asset_close: pd.Series,
    *,
    aligned_sources: Mapping[str, pd.DataFrame],
    correlation_window: int,
    beta_window: int,
    relative_strength_period: int,
    trend_window: int,
    momentum_window: int,
    zscore_window: int,
) -> pd.DataFrame:
    """Compute cross-asset context features from aligned source frames."""
    index = asset_close.index
    frame = pd.DataFrame(index=index)
    asset_close = pd.to_numeric(asset_close, errors="coerce")
    asset_log_return = np.log(asset_close.replace(0.0, np.nan)).diff()
    asset_trend = _trend_signal(asset_close, window=trend_window)
    frame["asset_trend_context"] = asset_trend

    for source in ("BTC.D", "TOTAL2", "TOTAL3", "BTCUSDT", "ETHUSDT"):
        aligned = aligned_sources.get(source, pd.DataFrame(index=index))
        close = _numeric_series(aligned.get("close"), index=index)
        available = _bool_series(aligned.get("available"), index=index)
        clean_close = close.where(available)
        signal_prefix = _prefix(source)
        if source in {"BTC.D", "TOTAL2", "TOTAL3", "BTCUSDT", "ETHUSDT"}:
            frame[f"{signal_prefix}_trend"] = _trend_signal(clean_close, window=trend_window).fillna(0.0)
        if source == "BTC.D":
            frame["btc_d_momentum"] = _momentum_signal(
                clean_close,
                window=momentum_window,
                z_window=zscore_window,
            ).fillna(0.0)
        if source in {"BTCUSDT", "ETHUSDT", "TOTAL2", "TOTAL3"}:
            benchmark_return = np.log(clean_close.replace(0.0, np.nan)).diff()
            alias = _benchmark_alias(source)
            frame[f"asset_return_corr_{alias}"] = _rolling_corr(
                asset_log_return,
                benchmark_return,
                window=correlation_window,
            ).fillna(0.0)
            frame[f"asset_beta_{alias}"] = _rolling_beta(
                asset_log_return,
                benchmark_return,
                window=beta_window,
            ).fillna(0.0)
            frame[f"relative_strength_vs_{alias}"] = _relative_strength(
                asset_close,
                clean_close,
                period=relative_strength_period,
            ).fillna(0.0)

    frame["total3_confirmation"] = np.tanh(frame.get("total3_trend", 0.0)).astype(float)
    frame["alt_market_alignment"] = _clip(
        0.45 * np.tanh(frame.get("total3_trend", 0.0))
        + 0.20 * np.tanh(frame.get("total2_trend", 0.0))
        + 0.20 * np.tanh(-frame.get("btc_d_momentum", 0.0))
        + 0.15 * np.tanh(frame.get("relative_strength_vs_total3", 0.0)),
        lower=-1.0,
        upper=1.0,
    )
    frame["market_alignment_score"] = frame["alt_market_alignment"].astype(float)
    frame["asset_vs_total3_divergence"] = np.tanh(
        frame["asset_trend_context"] - frame.get("total3_trend", 0.0)
    ).astype(float)
    frame["asset_vs_btc_divergence"] = np.tanh(
        frame["asset_trend_context"] - frame.get("btcusdt_trend", 0.0)
    ).astype(float)
    frame["btc_d_conflict_score"] = _clip(
        frame["asset_trend_context"].clip(lower=0.0) * frame.get("btc_d_momentum", 0.0).clip(lower=0.0),
        lower=0.0,
        upper=1.0,
    )
    return frame.fillna(0.0)


def compute_breakout_confirmation_flags(
    *,
    breakout_direction: pd.Series | None,
    total3_trend: pd.Series | None,
    trend_threshold: float = 0.10,
) -> pd.DataFrame:
    """Compare local breakout direction against market trend confirmation."""
    if total3_trend is None:
        index = breakout_direction.index if breakout_direction is not None else pd.Index([])
        return pd.DataFrame(
            {
                "asset_breakout_without_market_confirmation": 0.0,
                "market_breakout_without_asset_confirmation": 0.0,
            },
            index=index,
        )

    market_side = np.where(
        pd.Series(total3_trend, copy=False).to_numpy(dtype=float) > float(trend_threshold),
        1.0,
        np.where(
            pd.Series(total3_trend, copy=False).to_numpy(dtype=float) < -float(trend_threshold),
            -1.0,
            0.0,
        ),
    )
    if breakout_direction is None:
        asset_side = np.zeros_like(market_side, dtype=float)
        index = total3_trend.index
    else:
        normalized = breakout_direction.astype(str).str.lower()
        asset_side = np.where(
            normalized.eq("up"),
            1.0,
            np.where(normalized.eq("down"), -1.0, 0.0),
        )
        index = breakout_direction.index

    return pd.DataFrame(
        {
            "asset_breakout_without_market_confirmation": (
                (asset_side != 0.0) & (market_side != asset_side)
            ).astype(float),
            "market_breakout_without_asset_confirmation": (
                (market_side != 0.0) & (asset_side != market_side)
            ).astype(float),
        },
        index=index,
    )


def _trend_signal(close: pd.Series, *, window: int) -> pd.Series:
    log_return = np.log(pd.to_numeric(close, errors="coerce").replace(0.0, np.nan)).diff()
    trend = log_return.rolling(window, min_periods=max(window // 2, 3)).sum()
    vol = log_return.rolling(window, min_periods=max(window // 2, 3)).std(ddof=0)
    return np.tanh((trend / vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)).fillna(0.0)


def _momentum_signal(close: pd.Series, *, window: int, z_window: int) -> pd.Series:
    raw = np.log(pd.to_numeric(close, errors="coerce").replace(0.0, np.nan) / close.shift(window))
    mean = raw.rolling(z_window, min_periods=max(z_window // 2, 5)).mean()
    std = raw.rolling(z_window, min_periods=max(z_window // 2, 5)).std(ddof=0).replace(0.0, np.nan)
    return ((raw - mean) / std).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(-5.0, 5.0)


def _rolling_corr(left: pd.Series, right: pd.Series, *, window: int) -> pd.Series:
    return left.rolling(window, min_periods=max(window // 2, 5)).corr(right)


def _rolling_beta(left: pd.Series, right: pd.Series, *, window: int) -> pd.Series:
    cov = left.rolling(window, min_periods=max(window // 2, 5)).cov(right)
    var = right.rolling(window, min_periods=max(window // 2, 5)).var(ddof=0).replace(0.0, np.nan)
    return (cov / var).replace([np.inf, -np.inf], np.nan)


def _relative_strength(asset_close: pd.Series, benchmark_close: pd.Series, *, period: int) -> pd.Series:
    asset_ret = np.log(asset_close / asset_close.shift(period))
    benchmark_ret = np.log(benchmark_close / benchmark_close.shift(period))
    return (asset_ret - benchmark_ret).replace([np.inf, -np.inf], np.nan).clip(-5.0, 5.0)


def _prefix(source: str) -> str:
    return source.lower().replace(".", "_")


def _benchmark_alias(source: str) -> str:
    return {
        "BTCUSDT": "btc",
        "ETHUSDT": "eth",
        "TOTAL2": "total2",
        "TOTAL3": "total3",
    }[source]


def _bool_series(values: pd.Series | None, *, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(False, index=index, dtype=bool)
    return values.reindex(index).fillna(False).astype(bool)


def _numeric_series(values: pd.Series | None, *, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(np.nan, index=index, dtype=float)
    return pd.to_numeric(values.reindex(index), errors="coerce")


def _clip(values: pd.Series | np.ndarray, *, lower: float, upper: float) -> pd.Series:
    series = pd.Series(values, copy=False)
    return series.clip(lower=lower, upper=upper)


__all__ = [
    "build_cross_asset_feature_frame",
    "compute_breakout_confirmation_flags",
]
