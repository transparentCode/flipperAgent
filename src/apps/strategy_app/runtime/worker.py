"""StrategyWorker — Valkey consumer for feature streams, dispatches to strategy services."""

from __future__ import annotations

import asyncio
from typing import Any

from apps.strategy_app.control import StrategyControlStore, StrategyDesiredState
from apps.strategy_app.evaluation.service import StrategyEvaluationService
from apps.strategy_app.evaluation.view_adapter import StrategyDecisionViewAdapter
from apps.strategy_app.models import (
    ModelManager,
    ScoringModelManager,
    UnifiedModelManager,
)
from apps.strategy_app.observability.runtime_state import StrategyRuntimeStateStore
from apps.strategy_app.publishing.signals import (
    StrategyAuthorityDenied,
    StrategySignalPublisher,
    make_signal_idempotency_key,
)
from apps.strategy_app.settings import (
    StrategyWorkerSettings,
    create_strategy_config_manager,
)
from apps.strategy_app.state import StrategyPair, StrategyPairState
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.common.signal_authority import (
    SignalAuthorityStore,
    SignalRouteAuthority,
    signal_route_from_stream,
)
from libs.common.stream_consumer import BaseStreamConsumer
from libs.common.stream_keys import feature_stream_key
from libs.common.timeframes import timeframe_to_seconds
from libs.contracts.schemas import FeatureVector, valkey_decode
from libs.models.blender.ensemble import RegimeEnsembleBlender
from libs.selection.selection_layer import SelectionLayer

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

DEFAULT_STRATEGY_WORKER_SETTINGS = StrategyWorkerSettings()


class StrategyWorker(BaseStreamConsumer):
    """Valkey consumer for projected or direct feature streams."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        model_manager: ModelManager | None = None,
        scoring_model_manager: ScoringModelManager | None = None,
        unified_model_manager: UnifiedModelManager | None = None,
        selection_layer: SelectionLayer | None = None,
        blender: RegimeEnsembleBlender | None = None,
        settings: StrategyWorkerSettings | None = None,
        config_manager: ConfigManager | None = None,
        trigger_timeframe: str | None = None,
        trigger_mode: str = "on_bar_close",
        base_timeframe: str = "1m",
        allowed_model_names: list[str] | None = None,
        authority_store: SignalAuthorityStore | None = None,
    ) -> None:
        config_manager = create_strategy_config_manager(
            config_manager or ConfigManager()
        )
        settings = settings or StrategyWorkerSettings.from_config(config_manager)
        self.asset = asset
        self.timeframe = timeframe
        self.decision_timeframe = timeframe
        self.trigger_timeframe = trigger_timeframe or timeframe
        self.trigger_mode = trigger_mode
        self.base_timeframe = base_timeframe
        self.allowed_model_names = set(allowed_model_names or [])
        self.view_adapter = StrategyDecisionViewAdapter(
            decision_timeframe=self.decision_timeframe,
            trigger_timeframe=self.trigger_timeframe,
            trigger_mode=self.trigger_mode,
            base_timeframe=self.base_timeframe,
        )
        super().__init__(
            stream_key=feature_stream_key(
                asset,
                self.decision_timeframe,
                trigger_timeframe=self.trigger_timeframe,
            ),
            group_name=settings.consumer_group,
            consumer_name=_consumer_name(
                settings.consumer_name_prefix,
                asset,
                decision_timeframe=self.decision_timeframe,
                trigger_timeframe=self.trigger_timeframe,
            ),
            batch_size=settings.batch_size,
            block_ms=settings.block_ms,
        )
        self.settings = settings
        self.feature_stream_key = self.stream_key
        self.signal_stream_key = f"signals:{asset}:{self.decision_timeframe}"
        self.config_manager = config_manager
        self.authority_store = authority_store
        self._authority_record: SignalRouteAuthority | None = None
        self.model_manager = model_manager or ModelManager(
            asset,
            self.decision_timeframe,
            config_manager=self.config_manager,
        )
        self.scoring_model_manager = scoring_model_manager or ScoringModelManager(
            asset,
            self.decision_timeframe,
            config_manager=self.config_manager,
        )
        self.unified_model_manager = unified_model_manager or UnifiedModelManager(
            asset,
            self.decision_timeframe,
            config_manager=self.config_manager,
            bridge_legacy_roots=False,
        )
        self.selection_layer = selection_layer or SelectionLayer(
            asset, self.decision_timeframe
        )
        self.evaluation_service = StrategyEvaluationService(
            asset=asset,
            timeframe=self.decision_timeframe,
            model_manager=self.model_manager,
            scoring_model_manager=self.scoring_model_manager,
            unified_model_manager=self.unified_model_manager,
            selection_layer=self.selection_layer,
            logger=logger,
            blender=blender,
        )

        self.blender: RegimeEnsembleBlender | None = blender
        if (
            self.blender is None
            and settings.blender_enabled
            and settings.blender_config
        ):
            try:
                self.blender = RegimeEnsembleBlender(settings.blender_config)
                logger.info(
                    f"Regime ensemble blender enabled for {asset}/{self.decision_timeframe}"
                )
            except Exception:  # noqa: BLE001
                logger.debug("Blender config not found or invalid, blender disabled")
        self.evaluation_service.blender = self.blender
        self.signal_publisher = StrategySignalPublisher(
            signal_stream_key=self.signal_stream_key,
            maxlen=self.settings.signal_stream_maxlen,
            approximate=self.settings.signal_stream_approximate,
            logger=logger,
            authority_store=self.authority_store,
        )
        self.state_store: StrategyRuntimeStateStore | None = None
        self.control_store: StrategyControlStore | None = None

    async def connect(self, redis_client: Any) -> None:
        await super().connect(redis_client)
        if (
            self.authority_store is None
            and self.settings.signal_authority_enforced
            and _is_real_valkey_client(redis_client)
        ):
            self.authority_store = SignalAuthorityStore(redis_client)
            self.signal_publisher.authority_store = self.authority_store
        self.state_store = StrategyRuntimeStateStore(redis_client)
        self.control_store = StrategyControlStore(redis_client)

    async def start(self) -> None:
        logger.info(f"Starting strategy worker for {self.asset}/{self.timeframe}")
        try:
            await self._capture_authority()
            if await self._is_paused():
                await self._update_runtime_state(
                    state=StrategyPairState.PAUSED,
                    detail={
                        "phase": "startup",
                        "desired_state": StrategyDesiredState.PAUSED.value,
                    },
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
                    detail={
                        "phase": "live",
                        "desired_state": StrategyDesiredState.PAUSED.value,
                    },
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
        try:
            feature_vec = valkey_decode(payload, FeatureVector)
        except Exception as e:
            await self._update_runtime_state(
                state=StrategyPairState.DEGRADED,
                last_error=str(e),
                detail={"phase": "decode"},
            )
            logger.exception("Failed to deserialize feature payload")
            return

        try:
            (
                authority_epoch,
                authority_boundary_ms,
                effect_cutoff_ms,
            ) = await self._validate_authority_for_feature(feature_vec)
            if await self._is_paused():
                await self._update_runtime_state(
                    state=StrategyPairState.PAUSED,
                    detail={
                        "phase": "paused",
                        "desired_state": StrategyDesiredState.PAUSED.value,
                    },
                )
                return
            decision_view = self.view_adapter.adapt(feature_vec)
            result = self.evaluation_service.evaluate_feature_vector_routed(
                decision_view.feature_vector,
                allowed_model_names=self.allowed_model_names or None,
                runtime_metadata=decision_view.runtime_metadata,
            )
            published = await self.signal_publisher.publish_selected(
                redis_client=self.redis_client,
                feature_vec=result.feature_vector,
                selected=result.selected,
                authority_epoch=authority_epoch,
                authority_boundary_ms=authority_boundary_ms,
                effect_cutoff_ms=effect_cutoff_ms,
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

    async def _capture_authority(self) -> None:
        if self.authority_store is None:
            return
        route = signal_route_from_stream(self.signal_stream_key)
        if not self.authority_store.manages(route):
            return
        self._authority_record = await self.authority_store.assert_owner(
            route, "strategy"
        )

    async def _validate_authority_for_feature(
        self, feature_vec: FeatureVector
    ) -> tuple[int | None, int | None, int | None]:
        if self.authority_store is None:
            return None, None, None
        route = signal_route_from_stream(self.signal_stream_key)
        if not self.authority_store.manages(route):
            return None, None, None
        record = self._authority_record
        if record is None:
            await self._capture_authority()
            record = self._authority_record
        if record is None:
            raise RuntimeError(f"missing strategy authority record for {route}")
        timestamp = feature_vec.timestamp
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise StrategyAuthorityDenied(
                "managed FeatureVector timestamp must be numeric"
            )
        if not float(timestamp).is_integer() or timestamp <= 0:
            raise StrategyAuthorityDenied(
                "managed FeatureVector timestamp must be an epoch-millisecond integer"
            )
        effect_cutoff_ms = int(timestamp) + (
            timeframe_to_seconds(self.decision_timeframe) * 1000
        )
        await self.authority_store.assert_write(
            route=route,
            expected_owner="strategy",
            expected_epoch=record.epoch,
            expected_boundary_ms=record.boundary_ms,
            effect_cutoff_ms=effect_cutoff_ms,
        )
        return record.epoch, record.boundary_ms, effect_cutoff_ms

    @staticmethod
    def _make_idempotency_key(
        model_name: str, asset: str, timeframe: str, timestamp: float
    ) -> str:
        return make_signal_idempotency_key(model_name, asset, timeframe, timestamp)

    def _pair(self) -> StrategyPair:
        return StrategyPair(
            asset=self.asset,
            timeframe=self.decision_timeframe,
            trigger_timeframe=self.trigger_timeframe,
            base_timeframe=self.base_timeframe,
            trigger_mode=self.trigger_mode,
            model_names=sorted(self.allowed_model_names),
        )

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


def _consumer_name(
    prefix: str,
    asset: str,
    *,
    decision_timeframe: str,
    trigger_timeframe: str,
) -> str:
    if decision_timeframe == trigger_timeframe:
        return f"{prefix}_{asset}_{decision_timeframe}"
    return f"{prefix}_{asset}_{decision_timeframe}__{trigger_timeframe}"


def _is_real_valkey_client(client: Any) -> bool:
    """Avoid treating permissive test doubles as production authority clients."""

    module_name = type(client).__module__
    return module_name.startswith(("valkey.", "redis."))
