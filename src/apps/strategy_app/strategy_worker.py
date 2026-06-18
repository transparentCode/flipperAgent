"""Compatibility shim for StrategyWorker."""

from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

from apps.strategy_app.evaluation.migration import log_migration_comparison
from apps.strategy_app.model_manager import ModelManager
from apps.strategy_app.runtime.worker import StrategyWorker as _RuntimeStrategyWorker
from apps.strategy_app.scoring_model_manager import ScoringModelManager
from apps.strategy_app.settings import StrategyWorkerSettings, create_strategy_config_manager
from libs.models.blender.ensemble import RegimeEnsembleBlender
from libs.selection.selection_layer import SelectionLayer

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


class StrategyWorker(_RuntimeStrategyWorker):
    """Backward-compatible StrategyWorker import surface."""

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
        trigger_timeframe: str | None = None,
        trigger_mode: str = "on_bar_close",
        base_timeframe: str = "1m",
        allowed_model_names: list[str] | None = None,
    ) -> None:
        config_manager = create_strategy_config_manager(config_manager or ConfigManager())
        settings = settings or StrategyWorkerSettings.from_config(config_manager)
        model_manager = model_manager or ModelManager(
            asset,
            timeframe,
            config_manager=config_manager,
        )
        scoring_model_manager = scoring_model_manager or ScoringModelManager(
            asset,
            timeframe,
            config_manager=config_manager,
        )
        selection_layer = selection_layer or SelectionLayer(asset, timeframe)
        if blender is None and settings.blender_enabled and settings.blender_config:
            try:
                blender = RegimeEnsembleBlender(settings.blender_config)
            except Exception:
                blender = None
        super().__init__(
            asset,
            timeframe,
            model_manager=model_manager,
            scoring_model_manager=scoring_model_manager,
            selection_layer=selection_layer,
            blender=blender,
            settings=settings,
            config_manager=config_manager,
            trigger_timeframe=trigger_timeframe,
            trigger_mode=trigger_mode,
            base_timeframe=base_timeframe,
            allowed_model_names=allowed_model_names,
        )

    def _log_migration_comparison(
        self,
        adapted: list[object],
        shadow: list[object],
    ) -> None:
        log_migration_comparison(
            logger,
            asset=self.asset,
            timeframe=self.timeframe,
            adapted=adapted,
            shadow=shadow,
        )
