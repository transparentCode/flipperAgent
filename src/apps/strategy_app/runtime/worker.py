"""StrategyWorker — Valkey consumer for feature streams, dispatches to strategy services."""

from __future__ import annotations

import asyncio
from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.stream_consumer import BaseStreamConsumer
from libs.contracts.schemas import FeatureVector, valkey_decode

from apps.strategy_app.control import StrategyControlStore, StrategyDesiredState
from apps.strategy_app.evaluation.service import StrategyEvaluationService
from apps.strategy_app.models import ModelManager, ScoringModelManager
from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
from apps.strategy_app.publishing.signals import (
    StrategySignalPublisher,
    make_signal_idempotency_key,
)
from apps.strategy_app.settings import StrategyWorkerSettings, create_strategy_config_manager
from apps.strategy_app.state import StrategyPair, StrategyPairState
from libs.models.blender.ensemble import RegimeEnsembleBlender
from libs.selection.selection_layer import SelectionLayer

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

DEFAULT_STRATEGY_WORKER_SETTINGS = StrategyWorkerSettings()


class StrategyWorker(BaseStreamConsumer):
    """Valkey consumer for ``features:{asset}:{timeframe}`` streams."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        model_manager: ModelManager | None = None,
        scoring_model_manager: ScoringModelManager | None = None,
        selection_layer: SelectionLayer | None = None,
        blender: RegimeEnsembleBlender | None = None,
        settings: StrategyWorkerSettings | None = None,
        config_manager: ConfigManager | None = None,
    ) -> None:
        config_manager = create_strategy_config_manager(config_manager or ConfigManager())
        settings = settings or StrategyWorkerSettings.from_config(config_manager)
        super().__init__(
            stream_key=f"features:{asset}:{timeframe}",
            group_name=settings.consumer_group,
            consumer_name=f"{settings.consumer_name_prefix}_{asset}_{timeframe}",
            batch_size=settings.batch_size,
            block_ms=settings.block_ms,
        )
        self.asset = asset
        self.timeframe = timeframe
        self.settings = settings
        self.feature_stream_key = self.stream_key
        self.signal_stream_key = f"signals:{asset}:{timeframe}"
        self.config_manager = config_manager
        self.model_manager = model_manager or ModelManager(
            asset,
            timeframe,
            config_manager=self.config_manager,
        )
        self.scoring_model_manager = scoring_model_manager or ScoringModelManager(
            asset,
            timeframe,
            config_manager=self.config_manager,
        )
        self.selection_layer = selection_layer or SelectionLayer(asset, timeframe)
        self.evaluation_service = StrategyEvaluationService(
            asset=asset,
            timeframe=timeframe,
            model_manager=self.model_manager,
            scoring_model_manager=self.scoring_model_manager,
            selection_layer=self.selection_layer,
            logger=logger,
            blender=blender,
        )

        self.blender: RegimeEnsembleBlender | None = blender
        if self.blender is None and settings.blender_enabled and settings.blender_config:
            try:
                self.blender = RegimeEnsembleBlender(settings.blender_config)
                logger.info(f"Regime ensemble blender enabled for {asset}/{timeframe}")
            except Exception:
                logger.debug("Blender config not found or invalid, blender disabled")
        self.evaluation_service.blender = self.blender
        self.signal_publisher = StrategySignalPublisher(
            signal_stream_key=self.signal_stream_key,
            maxlen=self.settings.signal_stream_maxlen,
            approximate=self.settings.signal_stream_approximate,
            logger=logger,
        )
        self.state_store: StrategyRuntimeStateStore | None = None
        self.control_store: StrategyControlStore | None = None

    async def connect(self, redis_client: Any) -> None:
        await super().connect(redis_client)
        self.state_store = StrategyRuntimeStateStore(redis_client)
        self.control_store = StrategyControlStore(redis_client)

    async def start(self) -> None:
        logger.info(f"Starting strategy worker for {self.asset}/{self.timeframe}")
        try:
            if await self._is_paused():
                await self._update_runtime_state(
                    state=StrategyPairState.PAUSED,
                    detail={"phase": "startup", "desired_state": StrategyDesiredState.PAUSED.value},
                )
            else:
                await self._update_runtime_state(
                    state=StrategyPairState.WARMING,
                    detail={"phase": "startup"},
                )
            self.evaluation_service.validate_feature_coverage()
            if await self._is_paused():
                await self._update_runtime_state(
                    state=StrategyPairState.PAUSED,
                    last_error=None,
                    detail={"phase": "live", "desired_state": StrategyDesiredState.PAUSED.value},
                )
            else:
                await self._update_runtime_state(
                    state=StrategyPairState.WARMING,
                    last_error=None,
                    detail={"phase": "live", "reason": "awaiting_features"},
                )
            await self.run()
        except asyncio.CancelledError:
            await self._update_runtime_state(
                state=StrategyPairState.STOPPED,
                detail={"phase": "shutdown"},
            )
            raise
        except Exception as exc:
            await self._update_runtime_state(
                state=StrategyPairState.FAILED,
                last_error=str(exc),
                detail={"phase": "startup_or_run"},
            )
            raise

    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        await self.process_features(data)

    async def process_features(self, payload: dict) -> None:
        if await self._is_paused():
            await self._update_runtime_state(
                state=StrategyPairState.PAUSED,
                detail={"phase": "paused", "desired_state": StrategyDesiredState.PAUSED.value},
            )
            return

        try:
            feature_vec = valkey_decode(payload, FeatureVector)
        except Exception as e:
            await self._update_runtime_state(
                state=StrategyPairState.DEGRADED,
                last_error=str(e),
                detail={"phase": "decode"},
            )
            logger.error(f"Failed to deserialize feature payload: {e}", exc_info=True)
            return

        try:
            result = self.evaluation_service.evaluate_feature_vector(feature_vec)
            published = await self.signal_publisher.publish_selected(
                redis_client=self.redis_client,
                feature_vec=result.feature_vector,
                selected=result.selected,
            )
            latest_signal_ts = (
                max(candidate.candidate.timestamp for candidate in result.selected)
                if published and result.selected
                else None
            )
            detail: dict[str, Any] = {
                "phase": "live",
                "selected_count": len(result.selected),
                "published_count": published,
            }
            if result.selected:
                detail["selected_models"] = [
                    candidate.candidate.model_name for candidate in result.selected
                ]
            await self._update_runtime_state(
                state=StrategyPairState.LIVE,
                last_feature_ts=float(feature_vec.timestamp),
                last_signal_ts=latest_signal_ts,
                last_error=None,
                detail=detail,
            )
        except Exception as exc:
            await self._update_runtime_state(
                state=StrategyPairState.FAILED,
                last_feature_ts=float(feature_vec.timestamp),
                last_error=str(exc),
                detail={"phase": "live"},
            )
            raise

    @staticmethod
    def _make_idempotency_key(model_name: str, asset: str, timeframe: str, timestamp: float) -> str:
        return make_signal_idempotency_key(model_name, asset, timeframe, timestamp)

    def _pair(self) -> StrategyPair:
        return StrategyPair(asset=self.asset, timeframe=self.timeframe)

    async def _update_runtime_state(
        self,
        *,
        state: StrategyPairState,
        last_feature_ts: float | None = None,
        last_signal_ts: float | None = None,
        last_error: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        if self.state_store is None:
            return
        await self.state_store.update(
            self._pair(),
            state=state,
            last_feature_ts=last_feature_ts,
            last_signal_ts=last_signal_ts,
            last_error=last_error,
            replace_last_error=last_error is None,
            detail=detail,
        )

    async def _is_paused(self) -> bool:
        if self.control_store is None:
            return False
        return await self.control_store.is_paused(self._pair())
