"""ScoringModelManager — config-driven loader and evaluator for ScoringModel subclasses."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import ConfigurationError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import FeatureVector
from libs.contracts.model_runtime import ResolvedModelRuntimeSpec
from libs.contracts.signal import ScoringOutput
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel

from apps.strategy_app.feature_contracts import build_available_feature_contract
from apps.strategy_app.runtime_specs import resolve_model_runtime_spec
from apps.strategy_app.settings import (
    create_strategy_config_manager,
    resolve_asset_timeframe_node,
)

import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

KEY_SCORING_MODELS = "scoring_models"
KEY_FEATURES = "features"
KEY_ENGINEERED_FEATURES = "engineered_features"


class ScoringModelManager:
    """Loads scoring models for a specific (asset, timeframe) from ``configs/models.yaml``."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config_manager: ConfigManager | None = None,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.config_mgr = create_strategy_config_manager(config_manager or ConfigManager())

        self.models: list[ScoringModel] = []
        self.runtime_specs: dict[str, ResolvedModelRuntimeSpec] = {}
        self._load_models()

    def _resolve_config_node(self, root_key: str) -> dict[str, Any]:
        return resolve_asset_timeframe_node(
            self.config_mgr,
            root_key,
            self.asset,
            self.timeframe,
        )

    def _load_models(self) -> None:
        models_node = self._resolve_config_node(KEY_SCORING_MODELS)

        for model_name, model_cfg in models_node.items():
            if not isinstance(model_cfg, dict):
                continue
            if not model_cfg.get("enabled", True):
                logger.info(f"Scoring model {model_name} disabled for {self.asset}/{self.timeframe}")
                continue
            try:
                model_cls = ModelRegistry.get(model_name)
            except KeyError:
                logger.warning(f"Scoring model '{model_name}' not found in registry, skipping.")
                continue
            self.runtime_specs[model_name] = resolve_model_runtime_spec(
                asset=self.asset,
                timeframe=self.timeframe,
                model_name=model_name,
                model_cfg=model_cfg,
                fallback_warmup_bars=getattr(model_cls.meta, "min_history_bars", 0),
            )
            params = model_cfg.get("params", {}) or {}
            model = model_cls(params)
            if not isinstance(model, ScoringModel):
                raise ConfigurationError(
                    f"Scoring model '{model_name}' for {self.asset}/{self.timeframe} "
                    f"must extend ScoringModel, got {type(model).__name__}"
                )
            self.models.append(model)
            logger.info(f"Loaded scoring model {model_name} for {self.asset}/{self.timeframe}")

    def validate_feature_coverage(self, available_features: set[str] | None = None) -> None:
        if available_features is None:
            available_features = self._available_features_from_config()

        for model in self.models:
            missing = model.validate_features(available_features)
            if missing:
                raise ConfigurationError(
                    f"Scoring model '{model.meta.name}' for {self.asset}/{self.timeframe} requires "
                    f"{missing} but features.yaml only provides {sorted(available_features)}"
                )
            missing_fields = model.validate_required_fields(available_features)
            missing_engineered_fields = sorted(
                field for field in missing_fields if field.startswith("eng_")
            )
            if missing_engineered_fields:
                raise ConfigurationError(
                    f"Scoring model '{model.meta.name}' for {self.asset}/{self.timeframe} requires "
                    f"engineered fields {missing_engineered_fields} but features.yaml engineered_features "
                    "does not configure them"
                )
            if missing_fields:
                logger.warning(
                    f"Scoring model '{model.meta.name}' for {self.asset}/{self.timeframe}: "
                    f"required_fields {missing_fields} not found in available features. "
                    f"These will be validated at runtime.",
                )

    def _available_features_from_config(self) -> set[str]:
        features_node = self._resolve_config_node(KEY_FEATURES)
        engineered_node = self._resolve_config_node(KEY_ENGINEERED_FEATURES)
        return build_available_feature_contract(features_node, engineered_node)

    def evaluate(self, features: FeatureVector) -> list[ScoringOutput]:
        outputs: list[ScoringOutput] = []
        for model in self.models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Scoring model {model.meta.name} failed: {e}", exc_info=True)
        return outputs
