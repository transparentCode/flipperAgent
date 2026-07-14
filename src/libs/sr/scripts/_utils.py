"""Shared data utilities for SR scripts.

Provides UTC normalization, paginated data fetching via BinanceConnector,
and multi-asset data map construction for TwoStageOptimizer.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger("app.sr.scripts")

_TIMEFRAME_LOOKBACK_DAYS = {
    "1m": 30,
    "3m": 30,
    "5m": 30,
    "15m": 60,
    "30m": 60,
    "1h": 90,
    "2h": 180,
    "4h": 180,
    "6h": 180,
    "8h": 180,
    "12h": 180,
    "1d": 365,
    "3d": 730,
    "1w": 1825,
}


def get_optimal_lookback_days(timeframe: str) -> int:
    """Return the default profiling horizon for a timeframe."""
    normalized = timeframe.strip().lower()
    return _TIMEFRAME_LOOKBACK_DAYS.get(normalized, 90)


def _ensure_utc(df: pd.DataFrame) -> pd.DataFrame:
    """Localize naive index to UTC or convert tz-aware index to UTC."""
    out = df.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    return out


def _parse_date(date_str: str) -> datetime:
    """Parse YYYY-MM-DD string to datetime."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def _fetch_paginated(
    connector,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    rate_limit_sleep: float = 0.3,
) -> pd.DataFrame:
    """Fetch klines with pagination (Binance returns max 1000 per call).

    Parameters
    ----------
    connector : BinanceConnector
        Connector instance (typed loosely to avoid import at module level).
    symbol : str
        Trading pair, e.g. ``"BTCUSDT"``.
    interval : str
        Timeframe string, e.g. ``"1h"``, ``"4h"``.
    start_ms, end_ms : int
        Epoch millisecond boundaries.
    rate_limit_sleep : float
        Seconds to sleep between paginated requests (default 0.3).

    Returns
    -------
    pd.DataFrame
        Deduplicated, sorted OHLCV DataFrame (may be empty).
    """
    all_data: list[pd.DataFrame] = []
    current_start = start_ms

    while current_start < end_ms:
        df = connector.get_futures_klines(symbol, interval, current_start, end_ms)
        if df.empty:
            break
        all_data.append(df)
        last_ms = int(df.index[-1].timestamp() * 1000)
        if last_ms >= end_ms or (last_ms == current_start and len(df) == 1):
            break
        current_start = last_ms + 1
        time.sleep(rate_limit_sleep)

    if not all_data:
        return pd.DataFrame()
    full = pd.concat(all_data)
    full = full[~full.index.duplicated(keep="last")]
    full.sort_index(inplace=True)
    return full


def fetch_data(
    asset: str,
    timeframe: str,
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    quiet: bool = False,
) -> pd.DataFrame:
    """Fetch OHLCV data for a single asset/timeframe via BinanceConnector.

    If *start_date* is provided, fetches ``[start_date, end_date]`` with
    auto-pagination.  Otherwise falls back to *lookback_days* from today.
    """
    from app.connectors.BinanceConnector import BinanceConnector

    connector = BinanceConnector()

    if start_date is not None:
        start_dt = _parse_date(start_date)
        end_dt = _parse_date(end_date) if end_date else datetime.now(UTC)
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        if not quiet:
            logger.info(
                "Fetching %s %s (%s to %s)...",
                asset, timeframe, start_date, end_date or "now",
            )
    else:
        if not quiet:
            logger.info(
                "Fetching %s %s (%d days)...", asset, timeframe, lookback_days,
            )
        start_ms = int((datetime.now(UTC).timestamp() - lookback_days * 86400) * 1000)
        end_ms = int(datetime.now(UTC).timestamp() * 1000)

    df = _fetch_paginated(connector, asset, timeframe, start_ms, end_ms)
    if not df.empty:
        df = _ensure_utc(df)
    if not quiet:
        logger.info("  %d bars loaded", len(df))
    return df


def fetch_multi_asset_data(
    assets: list[str],
    timeframes: list[str],
    lookback_days: int = 90,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    quiet: bool = False,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Build a ``{asset: {tf: DataFrame}}`` data map for TwoStageOptimizer.

    Fetches OHLCV data for every (asset, timeframe) pair via
    :func:`fetch_data`.
    """
    data_map: dict[str, dict[str, pd.DataFrame]] = {}
    for asset in assets:
        data_map[asset] = {}
        for tf in timeframes:
            data_map[asset][tf] = fetch_data(
                asset, tf,
                lookback_days=lookback_days,
                start_date=start_date,
                end_date=end_date,
                quiet=quiet,
            )
    return data_map


def compute_wick_body_ratio(df: pd.DataFrame, lookback_bars: int = 1000) -> float:
    """Compute median wick-to-body ratio from OHLCV data.

    Returns
    -------
    float
        Median ratio (capped at 10 per bar). Returns 1.0 if data is empty.
    """
    if df.empty:
        return 1.0
    import numpy as np

    recent = df.tail(lookback_bars)
    body = (recent["close"] - recent["open"]).abs()
    full_range = recent["high"] - recent["low"]
    wick = full_range - body

    body_safe = body.clip(lower=full_range.median() * 0.001)
    ratios = (wick / body_safe).clip(upper=10.0)
    result = float(ratios.median())
    return result if not np.isnan(result) else 1.0


def build_characteristics(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    metadata,
    atr_period: int = 14,
) -> "AssetCharacteristics":
    """Build AssetCharacteristics from a DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data.
    asset : str
        Asset symbol.
    timeframe : str
        Timeframe string (e.g., "1h", "4h").
    metadata : AssetMetadata
        Resolved asset metadata.
    atr_period : int
        ATR period for computing characteristics.

    Returns
    -------
    AssetCharacteristics
    """
    import numpy as np
    from app.sr.models import AssetCharacteristics

    # Timeframe minutes mapping
    _TF_MINUTES = {
        "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
        "12h": 720, "1d": 1440, "3d": 4320, "1w": 10080,
    }

    price = float(df["close"].iloc[-1])

    # ATR
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.rolling(atr_period).mean().iloc[-1])
    atr_pct = atr / price if price > 0 else 0.0

    # Volume stats
    volume_mean = float(df["volume"].tail(20).mean())
    volume_kurtosis = float(df["volume"].tail(200).kurt()) if len(df) >= 200 else 3.0

    # Hurst exponent (simple R/S estimate)
    hurst = 0.5
    hurst_confidence = 0.0
    try:
        from app.indicators.regime_metrices import RegimeMetrics
        rm = RegimeMetrics()
        hurst_result = rm.compute_hurst_exponent(df["close"].values)
        hurst = float(hurst_result.get("regime_hurst_exponent", 0.5))
        hurst_confidence = float(hurst_result.get("regime_hurst_confidence", 0.0))
    except Exception:
        pass

    # Wick body ratio
    wick_ratio = compute_wick_body_ratio(df)

    # Microstructure percentiles (over last 1000 bars or available data)
    lookback_bars = min(1000, len(df))
    recent = df.tail(lookback_bars)
    recent_high = recent["high"].values
    recent_low = recent["low"].values
    recent_open = recent["open"].values
    recent_close = recent["close"].values

    full_range = recent_high - recent_low
    body = np.abs(recent_close - recent_open)
    wick = full_range - body

    # Normalize by ATR (avoid division by zero)
    atr_safe = max(atr, 1e-10)
    wick_atr = wick / atr_safe
    body_atr = body / atr_safe
    range_atr = full_range / atr_safe

    wick_p75 = float(np.percentile(wick_atr, 75)) if len(wick_atr) > 0 else 0.5
    body_p50 = float(np.percentile(body_atr, 50)) if len(body_atr) > 0 else 0.3
    range_p90 = float(np.percentile(range_atr, 90)) if len(range_atr) > 0 else 1.5

    tf_minutes = _TF_MINUTES.get(timeframe, 60)

    return AssetCharacteristics(
        metadata=metadata,
        price=price,
        atr=atr,
        atr_pct=atr_pct,
        volume_mean=volume_mean,
        volume_kurtosis=volume_kurtosis,
        hurst=hurst,
        hurst_confidence=hurst_confidence,
        wick_body_ratio=wick_ratio,
        wick_p75_atr=wick_p75,
        body_p50_atr=body_p50,
        range_p90_atr=range_p90,
        tf_minutes=tf_minutes,
        n_timeframes=1,
    )
