from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.runtime.websocket import BinanceWebSocketManager
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.config import ConfigManager


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("INGESTION_RUN_WS_INTEGRATION") != "1",
    reason="set INGESTION_RUN_WS_INTEGRATION=1 to use the public Binance websocket",
)
async def test_live_btc_closed_candle_matches_binance_rest() -> None:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    config_manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        settings = load_ingestion_settings(config_manager)
    finally:
        config_manager.shutdown()
        ConfigManager.reset_singleton()

    asset = settings.assets["BTC"]
    instrument_id = "BTC-USDT-PERP"
    instrument = asset.instruments[instrument_id]
    base_timeframe = settings.base_timeframe
    base_duration = timedelta(
        seconds=settings.timeframes[base_timeframe].duration_seconds
    )
    lane = MarketLane(instrument.venue, instrument_id, base_timeframe)
    provider_symbol = instrument.provider_symbols["binance_native"]
    connection_anchor = aligned_bucket_start(
        datetime.now(UTC),
        base_duration,
        settings.calendar.alignment_origin,
    )
    manager = BinanceWebSocketManager(
        stream_url=settings.websocket.stream_url,
        queue_maxsize=settings.websocket.queue_maxsize,
    )
    rest_provider = BinanceNativeHistoricalProvider()
    stream = None

    try:
        stream = manager.stream_closed_candles(
            {lane: provider_symbol},
            base_timeframe=base_timeframe,
            timeframe_duration=base_duration,
            alignment_origin=settings.calendar.alignment_origin,
            connection_anchor=connection_anchor,
        )
        observation = await asyncio.wait_for(anext(stream), timeout=120)
        assert observation.provider_id == "binance_native"
        assert observation.provider_symbol == provider_symbol
        assert observation.transport == "websocket"
        assert observation.lane == lane
        assert observation.close_time == observation.open_time + base_duration
        assert observation.taker_buy_base is not None
        assert observation.provider_close_time is not None

        settle_at = observation.close_time + timedelta(
            seconds=settings.recovery.rest_finalization_grace_seconds
        )
        wait_seconds = (settle_at - datetime.now(UTC)).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        rest_observations = await rest_provider.fetch_closed_candles(
            lane=lane,
            provider_symbol=provider_symbol,
            timeframe_duration=base_duration,
            since=observation.open_time,
            until=observation.close_time,
            limit=1,
        )
        assert len(rest_observations) == 1
        rest_observation = rest_observations[0]

        assert rest_observation.open_time == observation.open_time
        assert rest_observation.close_time == observation.close_time
        assert rest_observation.open == observation.open
        assert rest_observation.high == observation.high
        assert rest_observation.low == observation.low
        assert rest_observation.close == observation.close
        assert rest_observation.volume == observation.volume
        assert rest_observation.taker_buy_base == observation.taker_buy_base
        assert rest_observation.provider_close_time == observation.provider_close_time
    finally:
        if stream is not None:
            await stream.aclose()
        await rest_provider.close()
