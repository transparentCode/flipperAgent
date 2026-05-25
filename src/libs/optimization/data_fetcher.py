"""Fetch historical OHLCV data from Binance for optimization.

Uses binance-futures-connector SDK directly — zero dependency on
apps/ingestion_app adapters. Avoids cross-app imports.

The ingestion app's BinanceNativeAdapter wraps the same SDK but is
tightly coupled to ingestion concerns (streaming, websocket multiplex,
ingestion-specific error types). This module provides only the
synchronous historical fetch needed for optimization.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from binance.um_futures import UMFutures

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# Binance returns 12 columns per kline row.
_RAW_KLINE_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume", "close_time",
    "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume", "ignore",
]

# Binance max limit per request.
_MAX_LIMIT = 1500


def fetch_historical_ohlcv(
    symbol: str,
    timeframe: str,
    since: int | None = None,
    until: int | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Fetch historical OHLCV from Binance Futures (synchronous, with pagination).

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. "BTCUSDT").
    timeframe : str
        Kline interval (e.g. "1h", "4h", "1d").
    since : int | None
        Start time in milliseconds (inclusive).
    until : int | None
        End time in milliseconds (inclusive).
    limit : int
        Target number of candles. If > 1500, paginated automatically.

    Returns
    -------
    pd.DataFrame
        Columns: timestamp, open, high, low, close, volume.
        Sorted by timestamp ascending, deduplicated.
    """
    config = ConfigManager()
    binance_cfg = config.get("binance", {})
    client = UMFutures(
        key=binance_cfg.get("api_key"),
        secret=binance_cfg.get("api_secret"),
    )

    all_frames: list[pd.DataFrame] = []
    fetched = 0
    cursor = since

    while fetched < limit:
        batch_limit = min(_MAX_LIMIT, limit - fetched)
        params: dict[str, Any] = {"limit": batch_limit}
        if cursor is not None:
            params["startTime"] = cursor
        if until is not None:
            params["endTime"] = until

        lines = client.klines(symbol, timeframe, **params)
        if not lines:
            break

        df = _parse_klines(lines)
        all_frames.append(df)
        fetched += len(df)

        # Advance cursor past the last returned timestamp
        last_ts = int(df["timestamp"].iloc[-1])
        if cursor is not None and last_ts <= cursor:
            break  # no progress — avoid infinite loop
        cursor = last_ts + 1

        if len(lines) < batch_limit:
            break  # Binance returned fewer than requested — no more data

    if not all_frames:
        logger.warning(f"No data returned for {symbol}/{timeframe}")
        return pd.DataFrame(columns=OHLCV_COLUMNS)

    result = pd.concat(all_frames, ignore_index=True)
    result = result.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    logger.info(f"Fetched {len(result)} candles for {symbol}/{timeframe}")
    return result


def _parse_klines(lines: list[list[Any]]) -> pd.DataFrame:
    """Parse raw Binance kline rows into a DataFrame."""
    df = pd.DataFrame(lines, columns=_RAW_KLINE_COLUMNS)
    df = df[OHLCV_COLUMNS]
    for col in OHLCV_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
