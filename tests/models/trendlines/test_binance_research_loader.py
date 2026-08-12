"""PIT-preserving tests for the neutral Binance trendline research loader."""

from datetime import UTC, datetime

import pandas as pd
import pytest

from libs.market_data.binance_native import BINANCE_KLINE_PAGE_LIMIT
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
)
from libs.models.trendlines.workflows.research.binance import (
    BinanceTrendlineResearchLoader,
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
            event_start=datetime(2025, 1, 1, tzinfo=UTC),
            knowledge_cutoff=datetime(2025, 1, 1, cutoff_hour, tzinfo=UTC),
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )


def _page(hours: list[int], *, high_offset: float = 0.0, close_offset_ms: int = -1):
    rows = []
    for hour in hours:
        open_ms = (
            int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)
            + hour * 3_600_000
        )
        rows.append(
            {
                "timestamp": open_ms,
                "open": 100.0,
                "high": 101.0 + high_offset,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "taker_buy_base": 5.0,
                "close_time": open_ms + 3_600_000 + close_offset_ms,
            }
        )
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_loader_uses_injected_neutral_adapter() -> None:
    adapter = FakeBinanceAdapter([_page([0])])
    loader = BinanceTrendlineResearchLoader(adapter=adapter)

    result = await loader.load(_spec(cutoff_hour=2))

    assert result["1h"].shape[0] == 1
    assert loader.adapter is adapter


@pytest.mark.asyncio
async def test_loader_preserves_close_time_and_open_time_pit_semantics() -> None:
    adapter = FakeBinanceAdapter([_page([0])])
    frame = (
        await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2))
    )["1h"]

    assert frame.index[0] == pd.Timestamp("2025-01-01", tz="UTC")
    assert frame["bar_available_at"].iloc[0] == pd.Timestamp(
        "2025-01-01 00:59:59.999",
        tz="UTC",
    )
    assert frame.attrs["bar_timestamp_semantics"] == "open_time"
    assert frame.attrs["bar_availability_source"] == "exchange_close_time"


@pytest.mark.asyncio
async def test_loader_uses_named_page_limit_and_advances_from_close_time() -> None:
    first = _page([0, 1])
    second = _page([2])
    adapter = FakeBinanceAdapter([first, second])
    loader = BinanceTrendlineResearchLoader(adapter=adapter)

    await loader.load(_spec(cutoff_hour=4))

    first_close = int(first.iloc[-1]["close_time"])
    assert loader.page_limit == BINANCE_KLINE_PAGE_LIMIT
    assert [call[1]["since"] for call in adapter.calls[:2]] == [
        int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000),
        first_close + 1,
    ]
    assert all(call[1]["include_close_time"] is True for call in adapter.calls)


@pytest.mark.asyncio
async def test_loader_filters_bars_after_knowledge_cutoff() -> None:
    adapter = FakeBinanceAdapter([_page([0, 1, 2])])
    frame = (
        await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2))
    )["1h"]

    assert list(frame.index) == [
        pd.Timestamp("2025-01-01 00:00:00", tz="UTC"),
        pd.Timestamp("2025-01-01 01:00:00", tz="UTC"),
    ]


@pytest.mark.asyncio
async def test_loader_rejects_conflicting_duplicate_event_rows() -> None:
    adapter = FakeBinanceAdapter(
        [_page([0]), _page([0], high_offset=1.0, close_offset_ms=3_600_000 - 1)]
    )

    with pytest.raises(ValueError, match="Conflicting Binance duplicate"):
        await BinanceTrendlineResearchLoader(adapter=adapter).load(_spec(cutoff_hour=2))
