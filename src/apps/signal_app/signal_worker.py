import asyncio
import json
from typing import Optional
from apps.signal_app.feature_manager import FeatureManager
from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)

class SignalWorker:
    def __init__(self, asset: str, timeframe: str, db_fetcher=None):
        self.asset = asset
        self.timeframe = timeframe
        self.stream_key = f"stream:ohlcv:{asset.lower()}:{timeframe}"
        self.group_name = "signal_app_group"
        self.consumer_name = f"signal_worker_{asset}_{timeframe}"
        self.feature_manager = FeatureManager(asset, timeframe, db_fetcher=db_fetcher)
        self.redis_client = None  # To be injected or instantiated

    async def connect(self, redis_client):
        self.redis_client = redis_client
        # Ensure group exists
        try:
            await self.redis_client.xgroup_create(self.stream_key, self.group_name, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create group {self.group_name} on {self.stream_key}: {e}")

    async def start(self):
        logger.info(f"Starting signal worker for {self.asset} {self.timeframe}...")

        # 1. Boot up requirements state. Find max lookback for priming.
        max_lookback = 1
        for ind in self.feature_manager.indicators:
            max_lookback = max(max_lookback, ind.lookback_required)

        # 2. Fetch history
        history = await self.feature_manager.fetch_historical_db_records(max_lookback)
        
        # 3. Prime indicators
        if history:
            self.feature_manager.prime(history)
        else:
            logger.warning("No history returned, indicators may fail to prime.")

        # 4. Listen on stream
        if not self.redis_client:
            logger.warning("No redis client provided. Running in mock mode.")
            return

        logger.info(f"Listening to stream {self.stream_key} via XREADGROUP...")
        while True:
            try:
                # Block for up to 1 second
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {self.stream_key: ">"},
                    count=10,
                    block=1000
                )

                if not response:
                    continue

                for stream_name, messages in response:
                    for message_id, payload in messages:
                        await self.process_message(message_id, payload)
                        # Acknowledge message
                        await self.redis_client.xack(self.stream_key, self.group_name, message_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in signal worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def process_message(self, message_id: str, payload: dict):
        # Identify when incoming streamed events flag as `bar_closed: true`
        is_closed = (
            payload.get(b"bar_closed") or payload.get("bar_closed")
            or payload.get(b"is_closed") or payload.get("is_closed")
        )
        
        # We need to treat bytes vs str gracefully depending on valkey client decoding
        if isinstance(is_closed, bytes):
            is_closed = is_closed.decode("utf-8")
            
        if is_closed in ("true", "True", "1", True):
            try:
                # Extract values, assuming they might be bytes
                def _get_float(key: str) -> float:
                    val = payload.get(key.encode("utf-8")) or payload.get(key)
                    return float(val)
                    
                open_ = _get_float("open")
                high = _get_float("high")
                low = _get_float("low")
                close = _get_float("close")
                volume = _get_float("volume")
                timestamp = _get_float("timestamp")

                data_tuple = (high, low, close, volume, timestamp)
                logger.debug(f"Dispatching tick {data_tuple} to FeatureManager")
                
                # Update features
                results = self.feature_manager.process_tick(data_tuple)
                logger.debug(f"Indicator results: {results}")

                # Publish computed features to Valkey for StrategyWorker consumption
                if self.redis_client and results:
                    feature_stream = f"features:{self.asset}:{self.timeframe}"
                    feature_payload = {
                        "asset": self.asset,
                        "timeframe": self.timeframe,
                        "timestamp": str(timestamp),
                        "features": json.dumps(results),
                        "bar_data": json.dumps({"open": open_, "high": high, "low": low, "close": close, "volume": volume}),
                    }
                    await self.redis_client.xadd(feature_stream, feature_payload, maxlen=10000, approximate=True)
                
            except Exception as e:
                logger.error(f"Failed to parse or process payload {payload}: {e}")

