"""Historical Binance USD-M Futures REST access for research consumers.

This module intentionally contains no WebSocket or live-ingestion runtime
behavior.  The legacy ingestion package retains its own frozen runtime adapter;
research and tooling use this neutral historical boundary instead.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
from binance.um_futures import UMFutures

from libs.common.exceptions import DataIngestionError

BINANCE_KLINE_PAGE_LIMIT = 1500

_OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
_BINANCE_RAW_KLINE_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
    "ignore",
]


class BinanceNativeAdapter:
    """Fetch historical Binance USD-M Futures klines through the native client."""

    def __init__(
        self, key: str | None = None, secret: str | None = None, **kwargs: Any
    ) -> None:
        self.client = UMFutures(key=key, secret=secret, **kwargs)

    def _fetch_and_parse_klines_sync(
        self,
        symbol: str,
        timeframe: str,
        *,
        include_close_time: bool = False,
        **params: Any,
    ) -> pd.DataFrame:
        lines = self.client.klines(symbol, timeframe, **params)
        frame = pd.DataFrame(lines)
        if frame.empty:
            columns = [*_OHLCV_COLUMNS, "taker_buy_base"]
            if include_close_time:
                columns.append("close_time")
            return pd.DataFrame(columns=columns)

        frame.columns = _BINANCE_RAW_KLINE_COLUMNS
        selected_columns = [*_OHLCV_COLUMNS, "taker_buy_base_asset_volume"]
        if include_close_time:
            selected_columns.append("close_time")
        frame = frame[selected_columns].copy()
        frame.rename(
            columns={"taker_buy_base_asset_volume": "taker_buy_base"},
            inplace=True,
        )
        for column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame

    async def get_historical_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: int | None = None,
        until: int | None = None,
        limit: int | None = None,
        *,
        include_close_time: bool = False,
    ) -> pd.DataFrame:
        """Fetch historical klines while preserving the legacy research API."""
        params: dict[str, int] = {}
        if since:
            params["startTime"] = since
        if until:
            params["endTime"] = until
        if limit:
            params["limit"] = limit

        try:
            return await asyncio.to_thread(
                self._fetch_and_parse_klines_sync,
                symbol,
                timeframe,
                include_close_time=include_close_time,
                **params,
            )
        except Exception as exc:
            raise DataIngestionError(
                f"Binance API failed to fetch OHLCV for {symbol}: {exc}"
            ) from exc


__all__ = ["BINANCE_KLINE_PAGE_LIMIT", "BinanceNativeAdapter"]
