from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import pandas as pd

from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader

HistoricalBars = Sequence[tuple[float, ...]]
HistoricalFetcher = Callable[[str, str, int], Awaitable[HistoricalBars]]


class StartupPrimer:
    def __init__(self, fetcher: HistoricalFetcher) -> None:
        self.fetcher = fetcher

    async def fetch_history(
        self,
        asset: str,
        timeframe: str,
        lookback: int,
    ) -> list[tuple[float, ...]]:
        history = await self.fetcher(asset, timeframe, lookback)
        return list(history)


class TimescaleStartupHistoryFetcher:
    """Fetch signal warmup history through the shared Timescale reader."""

    def __init__(self, reader: TimescaleReader | None = None) -> None:
        self.reader = reader

    async def __call__(
        self,
        asset: str,
        timeframe: str,
        lookback: int,
    ) -> list[tuple[float, ...]]:
        reader = self.reader or TimescaleReader(DBPoolManager.get_reader_pool())
        frame = await reader.get_ohlcv_aggregated(asset, timeframe, lookback)
        return dataframe_to_bar_tuples(frame)


def dataframe_to_bar_tuples(frame: pd.DataFrame) -> list[tuple[float, ...]]:
    if frame.empty:
        return []

    rows: list[tuple[float, ...]] = []
    for _, row in frame.iterrows():
        rows.append(
            (
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
                _timestamp_to_seconds(row["timestamp"]),
                _safe_float(row.get("taker_buy_base", 0.0)),
            )
        )
    return rows


def _timestamp_to_seconds(value: Any) -> float:
    if hasattr(value, "timestamp"):
        return float(value.timestamp())
    value_float = float(value)
    return value_float / 1000.0 if value_float > 1e12 else value_float


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return default if result != result else result
