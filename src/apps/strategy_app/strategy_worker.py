"""StrategyWorker — Valkey consumer for feature streams, dispatches to ModelManager."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import FeatureVector, TradeSignal, valkey_encode, valkey_decode
from apps.strategy_app.model_manager import ModelManager
from libs.selection.selection_layer import SelectionLayer

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


class StrategyWorker(BaseStreamConsumer):
    """Valkey consumer for ``features:{asset}:{timeframe}`` streams."""

    def __init__(self, asset: str, timeframe: str) -> None:
        super().__init__(
            stream_key=f"features:{asset}:{timeframe}",
            group_name="strategy_app_group",
            consumer_name=f"strategy_worker_{asset}_{timeframe}",
            batch_size=10,
            block_ms=1000,
        )
        self.asset = asset
        self.timeframe = timeframe
        self.feature_stream_key = self.stream_key
        self.signal_stream_key = f"signals:{asset}:{timeframe}"
        self.model_manager = ModelManager(asset, timeframe)
        self.selection_layer = SelectionLayer(asset, timeframe)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        logger.info(f"Starting strategy worker for {self.asset}/{self.timeframe}")

        # Validate feature coverage at boot
        self.model_manager.validate_feature_coverage()

        # Delegate to base class consumer loop
        await self.run()

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        """Delegate to process_features for each message."""
        await self.process_features(data)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    async def process_features(self, payload: dict) -> None:
        """Deserialize feature payload, run models, publish signals."""
        try:
            feature_vec = valkey_decode(payload, FeatureVector)
        except Exception as e:
            logger.error(f"Failed to deserialize feature payload: {e}", exc_info=True)
            return

        outputs = self.model_manager.evaluate(feature_vec)

        # Run selection layer (no scoring outputs in Phase 1)
        selected = self.selection_layer.select(
            model_outputs=outputs,
            scoring_outputs=None,
            feature_vec=feature_vec,
        )

        for result in selected:
            candidate = result.candidate
            signal = TradeSignal(
                asset=candidate.asset,
                timeframe=candidate.timeframe,
                timestamp=candidate.timestamp,
                direction=candidate.direction,
                conviction=candidate.conviction,
                price=feature_vec.bar_data.get("close", 0.0),
                idempotency_key=self._make_idempotency_key(
                    candidate.model_name, candidate.asset,
                    candidate.timeframe, candidate.timestamp,
                ),
                model_name=candidate.model_name,
                metadata={
                    **candidate.metadata,
                    "selection_rank": result.rank,
                    "selection_score": result.selection_score,
                    "selection_penalties": result.penalties,
                },
            )

            if self.redis_client:
                await self.redis_client.xadd(
                    self.signal_stream_key,
                    valkey_encode(signal),
                    maxlen=5000,
                    approximate=True,
                )
                logger.debug(f"Published signal: {signal.idempotency_key}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_idempotency_key(model_name: str, asset: str, timeframe: str, timestamp: float) -> str:
        raw = f"{model_name}:{asset}:{timeframe}:{timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
