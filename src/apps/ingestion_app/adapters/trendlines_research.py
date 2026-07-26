"""Binance bridge for explicit trendline research data preparation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.constants import BINANCE_KLINE_PAGE_LIMIT
from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows.research.contracts import (
    TrendlineResearchDataMode,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
)


def _millis(value: pd.Timestamp) -> int:
    return int(value.timestamp() * 1000)


def _normalize_page(page: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if not isinstance(page, pd.DataFrame) or page.empty:
        return pd.DataFrame()
    normalized = page.copy()
    if "timestamp" in normalized.columns:
        event = pd.to_datetime(normalized.pop("timestamp"), unit="ms", utc=True)
        normalized.index = pd.DatetimeIndex(event)
    elif not isinstance(normalized.index, pd.DatetimeIndex):
        raise ValueError(f"Binance page for {timeframe} has no timestamp")
    elif normalized.index.tz is None:
        raise ValueError(f"Binance page for {timeframe} has a naive index")
    else:
        normalized.index = normalized.index.tz_convert("UTC")
    if "close_time" not in normalized.columns:
        raise ValueError("Binance research bridge requires close_time")
    close_time = pd.to_datetime(normalized.pop("close_time"), unit="ms", utc=True)
    normalized["bar_available_at"] = close_time
    normalized.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
    normalized.attrs["bar_availability_source"] = BarAvailabilitySource.EXCHANGE_CLOSE_TIME.value
    return normalized


def _deduplicate_pages(pages: list[pd.DataFrame], timeframe: str) -> pd.DataFrame:
    if not pages:
        return pd.DataFrame()
    combined = pd.concat(pages, axis=0)
    combined = combined.sort_index(kind="stable")
    duplicate_index = combined.index[combined.index.duplicated(keep=False)]
    for event_time in duplicate_index.unique():
        rows = combined.loc[[event_time]]
        if len(rows.drop_duplicates()) != 1:
            raise ValueError(f"Conflicting Binance duplicate event row for {timeframe}: {event_time}")
    result = combined[~combined.index.duplicated(keep="first")].copy()
    result.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
    result.attrs["bar_availability_source"] = BarAvailabilitySource.EXCHANGE_CLOSE_TIME.value
    return result


class BinanceTrendlineResearchLoader:
    """Fetch exact bounded Binance pages through the current native adapter."""

    def __init__(
        self,
        adapter: BinanceNativeAdapter | Any | None = None,
        *,
        page_limit: int = BINANCE_KLINE_PAGE_LIMIT,
    ) -> None:
        if isinstance(page_limit, bool) or int(page_limit) < 1:
            raise ValueError("page_limit must be positive")
        self.adapter = adapter or BinanceNativeAdapter()
        self.page_limit = int(page_limit)
        self.page_counts: dict[str, int] = {}
        self.provider_calls = 0

    async def load(self, spec: TrendlineResearchSpec) -> Mapping[str, pd.DataFrame]:
        if spec.purpose is not TrendlineResearchPurpose.RESEARCH:
            raise ValueError("Binance research data requires RESEARCH purpose")
        if spec.data.mode is not TrendlineResearchDataMode.BINANCE:
            raise ValueError("BinanceTrendlineResearchLoader requires BINANCE data mode")
        assert spec.data.event_start is not None
        assert spec.data.knowledge_cutoff is not None
        result: dict[str, pd.DataFrame] = {}
        for timeframe in spec.timeframes:
            current_start = _millis(pd.Timestamp(spec.data.event_start))
            cutoff = _millis(pd.Timestamp(spec.data.knowledge_cutoff))
            pages: list[pd.DataFrame] = []
            page_count = 0
            while current_start <= cutoff:
                self.provider_calls += 1
                page = await self.adapter.get_historical_ohlcv(
                    spec.asset,
                    timeframe,
                    since=current_start,
                    until=cutoff,
                    limit=self.page_limit,
                    include_close_time=True,
                )
                page_count += 1
                if page is None or page.empty:
                    break
                normalized = _normalize_page(page, timeframe)
                pages.append(normalized)
                last_close = normalized["bar_available_at"].iloc[-1]
                next_start = _millis(pd.Timestamp(last_close)) + 1
                if next_start <= current_start:
                    raise ValueError(f"Binance pagination did not advance for {timeframe}")
                current_start = next_start
                if next_start > cutoff:
                    break
            self.page_counts[timeframe] = page_count
            frame = _deduplicate_pages(pages, timeframe)
            if frame.empty:
                raise ValueError(f"Binance returned no complete bars for {spec.asset} {timeframe}")
            frame = frame[
                (frame.index >= pd.Timestamp(spec.data.event_start))
                & (frame["bar_available_at"] <= pd.Timestamp(spec.data.knowledge_cutoff))
            ].copy()
            frame.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
            frame.attrs["bar_availability_source"] = BarAvailabilitySource.EXCHANGE_CLOSE_TIME.value
            result[timeframe] = frame
        return result


__all__ = ["BINANCE_KLINE_PAGE_LIMIT", "BinanceTrendlineResearchLoader"]
