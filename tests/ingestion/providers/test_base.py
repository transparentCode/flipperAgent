from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    HistoricalCandleProvider,
    LiveCandleProvider,
)

LANE = MarketLane("binance", "BTC-USDT-PERP", "1m")
SINCE = datetime(2026, 1, 1, tzinfo=UTC)
UNTIL = datetime(2026, 1, 1, 1, tzinfo=UTC)


class _FakeHistoricalProvider:
    provider_id = "fake_historical"

    def __init__(self) -> None:
        self.request: tuple[object, ...] | None = None

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        self.request = (
            lane,
            provider_symbol,
            timeframe_duration,
            since,
            until,
            limit,
        )
        return ()


class _FakeLiveProvider:
    provider_id = "fake_live"

    def __init__(self) -> None:
        self.subscriptions: Mapping[MarketLane, str] | None = None
        self.request: tuple[object, ...] | None = None

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        self.subscriptions = subscriptions
        self.request = (
            base_timeframe,
            timeframe_duration,
            alignment_origin,
            connection_anchor,
        )

        async def stream() -> AsyncIterator[CandleObservation]:
            if False:
                yield None  # type: ignore[misc]

        return stream()


def test_historical_provider_contract_shape() -> None:
    provider: HistoricalCandleProvider = _FakeHistoricalProvider()

    result = asyncio.run(
        provider.fetch_closed_candles(
            lane=LANE,
            provider_symbol="BTCUSDT",
            timeframe_duration=timedelta(minutes=1),
            since=SINCE,
            until=UNTIL,
            limit=100,
        )
    )

    assert result == ()
    assert provider.provider_id == "fake_historical"
    assert provider.request == (
        LANE,
        "BTCUSDT",
        timedelta(minutes=1),
        SINCE,
        UNTIL,
        100,
    )


def test_live_provider_contract_shape() -> None:
    provider: LiveCandleProvider = _FakeLiveProvider()

    stream = provider.stream_closed_candles(
        {LANE: "BTCUSDT"},
        base_timeframe="1m",
        timeframe_duration=timedelta(minutes=1),
        alignment_origin=SINCE,
        connection_anchor=SINCE,
    )

    assert provider.provider_id == "fake_live"
    assert provider.request == (
        "1m",
        timedelta(minutes=1),
        SINCE,
        SINCE,
    )
    assert stream.__aiter__() is stream
