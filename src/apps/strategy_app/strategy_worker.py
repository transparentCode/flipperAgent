"""StrategyWorker — Valkey consumer for feature streams, dispatches to ModelManager."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import FeatureVector, TradeSignal, valkey_encode, valkey_decode
from libs.contracts.signal import ModelOutput, ScoringOutput
from apps.strategy_app.model_manager import ModelManager
from apps.strategy_app.scoring_model_manager import ScoringModelManager
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
        self.scoring_model_manager = ScoringModelManager(asset, timeframe)
        self.selection_layer = SelectionLayer(asset, timeframe)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        logger.info(f"Starting strategy worker for {self.asset}/{self.timeframe}")

        # Validate feature coverage at boot
        self.model_manager.validate_feature_coverage()
        self.scoring_model_manager.validate_feature_coverage()

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
        scoring_outputs = self.scoring_model_manager.evaluate(feature_vec)

        # Adapted legacy models (migration_mode="adapted")
        adapted_outputs = self.model_manager.evaluate_adapted(feature_vec)
        scoring_outputs.extend(adapted_outputs)

        # Shadow comparison logging
        shadow_outputs = self.model_manager.evaluate_shadow(feature_vec)
        self._log_migration_comparison(adapted_outputs, shadow_outputs)

        # Run selection layer
        selected = self.selection_layer.select(
            model_outputs=outputs,
            scoring_outputs=scoring_outputs,
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
                    "bar_high": feature_vec.bar_data.get("high", 0.0),
                    "bar_low": feature_vec.bar_data.get("low", 0.0),
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

    # ------------------------------------------------------------------
    # Migration comparison logging
    # ------------------------------------------------------------------

    def _log_migration_comparison(
        self,
        adapted: list[ScoringOutput],
        shadow: list[ModelOutput],
    ) -> None:
        """Log comparison between adapted scoring output and shadow binary output."""
        shadow_by_name = {m.model_name: m for m in shadow}
        for adapted_out in adapted:
            name = adapted_out.model_name
            shadow_out = shadow_by_name.get(name)
            if shadow_out is None:
                continue
            implied_edge = float(shadow_out.direction) * shadow_out.conviction
            match = abs(implied_edge - adapted_out.edge_score) < 1e-9
            logger.info(
                "legacy_migration_comparison",
                model_name=name,
                asset=self.asset,
                timeframe=self.timeframe,
                timestamp=adapted_out.timestamp,
                legacy_direction=shadow_out.direction,
                legacy_conviction=shadow_out.conviction,
                legacy_edge_implied=implied_edge,
                adapted_edge=adapted_out.edge_score,
                adapted_conviction=adapted_out.conviction,
                match=match,
            )
            if not match:
                logger.warning(
                    f"Migration mismatch for {name}: "
                    f"legacy={implied_edge:.6f} vs adapted={adapted_out.edge_score:.6f}"
                )
