"""StrategyWorker — Valkey consumer for feature streams, dispatches to ModelManager."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import FeatureVector, TradeSignal
from apps.strategy_app.model_manager import ModelManager

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


class StrategyWorker:
    """Valkey consumer for ``features:{asset}:{timeframe}`` streams."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.feature_stream_key = f"features:{asset}:{timeframe}"
        self.signal_stream_key = f"signals:{asset}:{timeframe}"
        self.group_name = "strategy_app_group"
        self.consumer_name = f"strategy_worker_{asset}_{timeframe}"
        self.model_manager = ModelManager(asset, timeframe)
        self.redis_client: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, redis_client: Any) -> None:
        self.redis_client = redis_client
        try:
            await self.redis_client.xgroup_create(
                self.feature_stream_key, self.group_name, id="0", mkstream=True,
            )
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create group {self.group_name}: {e}")

    async def start(self) -> None:
        logger.info(f"Starting strategy worker for {self.asset}/{self.timeframe}")

        # Validate feature coverage at boot
        self.model_manager.validate_feature_coverage()

        if not self.redis_client:
            logger.warning("No redis client. Running in mock mode.")
            return

        logger.info(f"Listening on stream {self.feature_stream_key}")
        while True:
            try:
                response = await self.redis_client.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {self.feature_stream_key: ">"},
                    count=10,
                    block=1000,
                )
                if not response:
                    continue

                for _stream_name, messages in response:
                    for message_id, payload in messages:
                        await self.process_features(payload)
                        await self.redis_client.xack(
                            self.feature_stream_key, self.group_name, message_id,
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in strategy worker loop: {e}", exc_info=True)
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def process_features(self, payload: dict) -> None:
        """Deserialize feature payload, run models, publish signals."""
        try:
            # Decode bytes keys/values if needed
            decoded: dict[str, Any] = {}
            for k, v in payload.items():
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                val = v.decode("utf-8") if isinstance(v, bytes) else v
                decoded[key] = val

            # Reconstruct FeatureVector from flat Valkey payload
            feature_vec = FeatureVector(
                asset=decoded.get("asset", self.asset),
                timeframe=decoded.get("timeframe", self.timeframe),
                timestamp=float(decoded.get("timestamp", 0)),
                features=json.loads(decoded.get("features", "{}")),
                bar_data=json.loads(decoded.get("bar_data", "{}")),
            )
        except Exception as e:
            logger.error(f"Failed to deserialize feature payload: {e}", exc_info=True)
            return

        outputs = self.model_manager.evaluate(feature_vec)

        for output in outputs:
            if output.direction == 0:
                continue
            signal = TradeSignal(
                asset=output.asset,
                timeframe=output.timeframe,
                timestamp=output.timestamp,
                direction=output.direction,
                conviction=output.conviction,
                price=feature_vec.bar_data.get("close", 0.0),
                idempotency_key=self._make_idempotency_key(
                    output.model_name, output.asset, output.timeframe, output.timestamp,
                ),
            )

            if self.redis_client:
                await self.redis_client.xadd(
                    self.signal_stream_key,
                    signal.model_dump(),
                )
                logger.debug(f"Published signal: {signal.idempotency_key}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_idempotency_key(model_name: str, asset: str, timeframe: str, timestamp: float) -> str:
        raw = f"{model_name}:{asset}:{timeframe}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
