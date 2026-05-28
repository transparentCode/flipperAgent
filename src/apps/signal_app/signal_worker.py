from __future__ import annotations

import asyncio
from typing import Any

from apps.signal_app.feature_manager import FeatureManager
from libs.common.logging.logger_utils import bind_logger
from libs.features.engineered.manager import EngineeredFeatureManager
from libs.common.enums import SystemComponent
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import FeatureVector, PriceUpdate, valkey_encode

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


class SignalWorker(BaseStreamConsumer):
    def __init__(self, asset: str, timeframe: str, db_fetcher=None):
        super().__init__(
            stream_key=f"stream:ohlcv:{asset.lower()}:{timeframe}",
            group_name="signal_app_group",
            consumer_name=f"signal_worker_{asset}_{timeframe}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.timeframe = timeframe
        self.feature_manager = FeatureManager(asset, timeframe, db_fetcher=db_fetcher)
        self.engineered_manager = EngineeredFeatureManager(asset, timeframe)

    async def start(self):
        logger.info(f"Starting signal worker for {self.asset} {self.timeframe}...")

        # 1. Boot up requirements state. Find max lookback for priming.
        max_lookback = 1
        for ind in self.feature_manager.indicators:
            max_lookback = max(max_lookback, ind.lookback_required)

        # 2. Fetch history and prime indicators (with retry for transient errors)
        for attempt in range(3):
            try:
                history = await self.feature_manager.fetch_historical_db_records(max_lookback)
                if history:
                    self.feature_manager.prime(history)
                else:
                    logger.warning("No history returned, indicators may fail to prime.")
                break
            except Exception:
                if attempt < 2:
                    logger.warning(f"Priming attempt {attempt + 1} failed for {self.asset}:{self.timeframe}, retrying...")
                    await asyncio.sleep(1)
                else:
                    logger.error(f"Priming failed after 3 attempts for {self.asset}:{self.timeframe}")

        # 3. Listen on stream via base class consumer loop
        await self.run()

    async def process_message(self, message_id: str, payload: dict) -> None:
        # Identify when incoming streamed events flag as `bar_closed: true`
        is_closed = payload.get("bar_closed") or payload.get("is_closed")

        if is_closed in ("true", "True", "1", True):
            try:
                open_ = float(payload["open"])
                high = float(payload["high"])
                low = float(payload["low"])
                close = float(payload["close"])
                volume = float(payload["volume"])
                timestamp = float(payload["timestamp"])

                # Ensure timestamp is in milliseconds
                if timestamp < 1e12:
                    timestamp = int(timestamp * 1000)

                data_tuple = (open_, high, low, close, volume, timestamp)
                logger.debug(f"Dispatching tick {data_tuple} to FeatureManager")
                
                # Update features
                results = self.feature_manager.process_tick(data_tuple)
                logger.debug(f"Indicator results: {results}")

                # Compute engineered features from raw indicator outputs
                # Pre-fetch TV index data from Valkey hashes (O(1) per index)
                index_data: dict[str, dict[str, float]] = {}
                if self.redis_client:
                    for idx_symbol in ("BTC.D", "TOTAL2", "TOTAL3"):
                        try:
                            raw = await self.redis_client.hgetall(f"index:latest:{idx_symbol}")
                            if raw:
                                index_data[idx_symbol] = {
                                    k.decode() if isinstance(k, bytes) else k:
                                    float(v.decode() if isinstance(v, bytes) else v)
                                    for k, v in raw.items()
                                }
                        except Exception:
                            pass  # index data is optional, failures are silent

                engineered = self.engineered_manager.compute(results, {
                    "open": open_, "high": high, "low": low,
                    "close": close, "volume": volume,
                }, index_data=index_data if index_data else None)
                results.update(engineered)

                # Publish computed features to Valkey for StrategyWorker consumption
                if self.redis_client and results:
                    feature_stream = f"features:{self.asset}:{self.timeframe}"
                    fv = FeatureVector(
                        asset=self.asset,
                        timeframe=self.timeframe,
                        timestamp=timestamp,
                        features=results,
                        bar_data={"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                    )
                    await self.redis_client.xadd(feature_stream, valkey_encode(fv), maxlen=10000, approximate=True)

                # Publish lightweight price heartbeat for RiskWorker SL/TP on every bar
                if self.redis_client:
                    price_stream = f"price_update:{self.asset}:{self.timeframe}"
                    pu = PriceUpdate(
                        asset=self.asset,
                        timeframe=self.timeframe,
                        timestamp=timestamp,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=volume,
                    )
                    await self.redis_client.xadd(price_stream, valkey_encode(pu), maxlen=100, approximate=True)
                
            except Exception as e:
                logger.error(f"Failed to parse or process payload {payload}: {e}")

