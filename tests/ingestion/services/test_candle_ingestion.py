from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.ingestion_app.domain.candle import CandleObservation, CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.storage.repository import CandleCommitStatus


def _candle() -> CanonicalCandle:
    open_time = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    return CanonicalCandle(
        lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
        open_time=open_time,
        close_time=datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(10),
        taker_buy_base=None,
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )


def _observation() -> CandleObservation:
    open_time = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    return CandleObservation(
        lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
        provider_id="ccxt_binance",
        provider_symbol="BTC/USDT:USDT",
        transport="rest",
        open_time=open_time,
        close_time=datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal("100.5"),
        volume=Decimal(10),
        taker_buy_base=None,
        received_at=datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
        provider_close_time=None,
        provider_event_id="provider-event",
    )


class _Repository:
    def __init__(self) -> None:
        self.candle: CanonicalCandle | None = None
        self.event = None
        self.commit_attempts = 0

    async def commit_candle(
        self,
        candle: CanonicalCandle,
        event: object,
    ) -> CandleCommitStatus:
        self.commit_attempts += 1
        self.candle = candle
        self.event = event
        return CandleCommitStatus.INSERTED


@pytest.mark.asyncio
async def test_service_builds_event_and_delegates_commit() -> None:
    repository = _Repository()
    candle = _candle()

    status = await CandleIngestionService(repository).commit_candle(candle)

    assert status is CandleCommitStatus.INSERTED
    assert repository.candle is candle
    assert repository.event is not None
    assert json.loads(repository.event.payload_json)["instrument_id"] == "BTC-TEST-PERP"


@pytest.mark.asyncio
async def test_service_canonicalizes_observation_through_existing_commit_path() -> None:
    repository = _Repository()
    observation = _observation()

    status = await CandleIngestionService(repository).commit_observation(observation)

    assert status is CandleCommitStatus.INSERTED
    assert repository.commit_attempts == 1
    assert repository.candle is not None
    assert repository.candle.lane is observation.lane
    assert repository.candle.source_type == "provider"
    assert repository.candle.source_provider == observation.provider_id
    assert repository.candle.source_timeframe is None
    assert repository.candle.open == observation.open
    assert repository.candle.taker_buy_base is None
    assert not hasattr(repository.candle, "provider_symbol")
    assert not hasattr(repository.candle, "transport")
    assert not hasattr(repository.candle, "received_at")
    assert not hasattr(repository.candle, "provider_close_time")
    assert not hasattr(repository.candle, "provider_event_id")
