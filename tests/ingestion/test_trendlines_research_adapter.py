"""Mocked Binance bridge tests for L2-A1."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from apps.ingestion_app.adapters.trendlines_research import BinanceTrendlineResearchLoader
from apps.ingestion_app.constants import BINANCE_KLINE_PAGE_LIMIT
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
)


class FakeBinanceAdapter:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    async def get_historical_ohlcv(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if not self.pages:
            return pd.DataFrame()
        return self.pages.pop(0)


def _spec(*, cutoff_hour: int = 4):
    return TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.RESEARCH,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.BINANCE,
            event_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            knowledge_cutoff=datetime(2025, 1, 1, cutoff_hour, tzinfo=timezone.utc),
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )


def _page(hours: list[int], *, high_offset: float = 0.0, close_offset_ms: int = -1):
    rows = []
    for hour in hours:
        open_ms = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000) + hour * 3_600_000
        rows.append(
            {
                "timestamp": open_ms,
                "open": 100.0,
                "high": 101.0 + high_offset,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "close_time": open_ms + 3_600_000 + close_offset_ms,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_binance_bridge_uses_binance_native_adapter_injected_seam():
    adapter = FakeBinanceAdapter([_page([0])])
    loader = BinanceTrendlineResearchLoader(adapter=adapter)

    result = await loader.load(_spec(cutoff_hour=2))

    assert result["1h"].shape[0] == 1
    assert loader.adapter is adapter


@pytest.mark.asyncio
async def test_binance_bridge_requests_close_time():
    adapter = FakeBinanceAdapter([_page([0])])
    await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2))

    assert adapter.calls[0][1]["include_close_time"] is True


@pytest.mark.asyncio
async def test_binance_bridge_uses_named_page_limit():
    adapter = FakeBinanceAdapter([_page([0])])
    loader = BinanceTrendlineResearchLoader(adapter=adapter)
    await loader.load(_spec(cutoff_hour=2))

    assert loader.page_limit == BINANCE_KLINE_PAGE_LIMIT
    assert adapter.calls[0][1]["limit"] == BINANCE_KLINE_PAGE_LIMIT


@pytest.mark.asyncio
async def test_binance_bridge_advances_from_last_close_time():
    first = _page([0, 1])
    second = _page([2])
    adapter = FakeBinanceAdapter([first, second])
    await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=4))

    first_close = int(first.iloc[-1]["close_time"])
    assert [call[1]["since"] for call in adapter.calls[:2]] == [
        int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000),
        first_close + 1,
    ]


@pytest.mark.asyncio
async def test_binance_bridge_preserves_open_time_event_index():
    adapter = FakeBinanceAdapter([_page([0])])
    frame = (await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2)))["1h"]

    assert frame.index[0] == pd.Timestamp("2025-01-01", tz="UTC")
    assert frame.attrs["bar_timestamp_semantics"] == "open_time"


@pytest.mark.asyncio
async def test_binance_bridge_preserves_exchange_close_availability():
    adapter = FakeBinanceAdapter([_page([0])])
    frame = (await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2)))["1h"]

    assert frame["bar_available_at"].iloc[0] == pd.Timestamp("2025-01-01 00:59:59.999", tz="UTC")
    assert frame.attrs["bar_availability_source"] == "exchange_close_time"


@pytest.mark.asyncio
async def test_binance_bridge_removes_bar_unavailable_by_knowledge_cutoff():
    adapter = FakeBinanceAdapter([_page([0, 1, 2])])
    frame = (await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2)))["1h"]

    assert list(frame.index) == [
        pd.Timestamp("2025-01-01 00:00:00", tz="UTC"),
        pd.Timestamp("2025-01-01 01:00:00", tz="UTC"),
    ]


@pytest.mark.asyncio
async def test_binance_bridge_rejects_conflicting_duplicate_event_rows():
    adapter = FakeBinanceAdapter(
        [_page([0]), _page([0], high_offset=1.0, close_offset_ms=3_600_000 - 1)]
    )

    with pytest.raises(ValueError, match="Conflicting Binance duplicate"):
        await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2))
