from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.settings import load_ingestion_settings
from libs.common.config import ConfigManager

pytestmark = pytest.mark.skipif(
    os.getenv("INGESTION_RUN_PROVIDER_INTEGRATION") != "1",
    reason="set INGESTION_RUN_PROVIDER_INTEGRATION=1 to use public provider APIs",
)


@pytest.mark.asyncio
async def test_btc_1m_provider_parity_against_approved_config() -> None:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    native: BinanceNativeHistoricalProvider | None = None
    ccxt_provider: CCXTHistoricalProvider | None = None
    try:
        settings = load_ingestion_settings(manager)
        asset = settings.assets["BTC"]
        instrument_id = "BTC-USDT-PERP"
        instrument = asset.instruments[instrument_id]
        timeframe = settings.timeframes[settings.base_timeframe]
        native_provider_settings = settings.providers[instrument.live_provider]
        ccxt_provider_settings = settings.providers["ccxt_binance"]
        assert native_provider_settings.enabled is True
        assert ccxt_provider_settings.enabled is True
        assert ccxt_provider_settings.exchange_id is not None
        assert settings.base_timeframe in instrument.timeframes

        lane = MarketLane(instrument.venue, instrument_id, settings.base_timeframe)
        duration = timedelta(seconds=timeframe.duration_seconds)
        since = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
        until = since + duration * 10

        native = BinanceNativeHistoricalProvider()
        ccxt_provider = CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id=ccxt_provider_settings.exchange_id,
        )
        native_observations = await native.fetch_closed_candles(
            lane=lane,
            provider_symbol=instrument.provider_symbols[native.provider_id],
            timeframe_duration=duration,
            since=since,
            until=until,
            limit=10,
        )
        ccxt_observations = await ccxt_provider.fetch_closed_candles(
            lane=lane,
            provider_symbol=instrument.provider_symbols[ccxt_provider.provider_id],
            timeframe_duration=duration,
            since=since,
            until=until,
            limit=10,
        )

        assert native_observations
        assert ccxt_observations
        assert len(native_observations) == 10
        assert len(ccxt_observations) == 10
        assert len(native_observations) == len(ccxt_observations)
        assert [observation.open_time for observation in native_observations] == sorted(
            observation.open_time for observation in native_observations
        )
        assert [observation.open_time for observation in ccxt_observations] == sorted(
            observation.open_time for observation in ccxt_observations
        )
        assert {observation.open_time for observation in native_observations} == {
            observation.open_time for observation in ccxt_observations
        }

        ccxt_by_open_time = {
            observation.open_time: observation for observation in ccxt_observations
        }
        for native_observation in native_observations:
            ccxt_observation = ccxt_by_open_time[native_observation.open_time]
            assert native_observation.close_time == ccxt_observation.close_time
            assert native_observation.open == ccxt_observation.open
            assert native_observation.high == ccxt_observation.high
            assert native_observation.low == ccxt_observation.low
            assert native_observation.close == ccxt_observation.close
            assert native_observation.volume == ccxt_observation.volume
            assert native_observation.taker_buy_base is not None
            assert native_observation.provider_close_time is not None
            assert ccxt_observation.taker_buy_base is None
            assert ccxt_observation.provider_close_time is None
            assert since <= native_observation.open_time < until
            assert since <= ccxt_observation.open_time < until
            assert native_observation.close_time <= until
            assert ccxt_observation.close_time <= until
    finally:
        if native is not None:
            await native.close()
        if ccxt_provider is not None:
            await ccxt_provider.close()
        manager.shutdown()
        ConfigManager.reset_singleton()
