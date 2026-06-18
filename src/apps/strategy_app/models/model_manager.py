"""ModelManager — config-driven model loading and feature validation."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import ConfigurationError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel
from libs.models.legacy_adapter import LegacyScoringAdapter
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel
from libs.contracts.model_runtime import ResolvedModelRuntimeSpec

from apps.strategy_app.feature_contracts import build_available_feature_contract
from apps.strategy_app.runtime_specs import resolve_model_runtime_spec
from apps.strategy_app.settings import (
    create_strategy_config_manager,
    resolve_asset_timeframe_node,
)

import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

KEY_MODELS = "models"
KEY_FEATURES = "features"
KEY_ENGINEERED_FEATURES = "engineered_features"
_VALID_MIGRATION_MODES = {"legacy", "adapted", "scoring", "native_scoring"}


class ModelManager:
    """Loads models for a specific (asset, timeframe) from ``configs/models.yaml``."""

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

        self.models: list[BaseModel] = []
        self.adapted_models: list[LegacyScoringAdapter] = []
        self.scoring_models: list[ScoringModel] = []
        self.shadow_models: list[BaseModel] = []
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
        models_node = self._resolve_config_node(KEY_MODELS)

        for model_name, model_cfg in models_node.items():
            if not isinstance(model_cfg, dict):
                continue
            if not model_cfg.get("enabled", True):
                logger.info(f"Model {model_name} disabled for {self.asset}/{self.timeframe}")
                continue
            try:
                model_cls = ModelRegistry.get(model_name)
            except KeyError:
                logger.warning(f"Model '{model_name}' not found in registry, skipping.")
                continue

            migration_mode = model_cfg.get("migration_mode", "legacy")
            if migration_mode not in _VALID_MIGRATION_MODES:
                logger.warning(
                    f"Model '{model_name}': unrecognized migration_mode "
                    f"'{migration_mode}', defaulting to 'legacy'."
                )
                migration_mode = "legacy"

            params = model_cfg.get("params", {}) or {}

            if migration_mode == "native_scoring":
                logger.info(
                    f"Model {model_name} has migration_mode='native_scoring', "
                    f"skipping (expected in scoring_models config)."
                )
                continue

            self.runtime_specs[model_name] = resolve_model_runtime_spec(
                asset=self.asset,
                timeframe=self.timeframe,
                model_name=model_name,
                model_cfg=model_cfg,
                fallback_warmup_bars=getattr(model_cls.meta, "min_history_bars", 0),
            )

            if migration_mode == "scoring":
                instance = model_cls(params)
                if not isinstance(instance, ScoringModel):
                    logger.warning(
                        f"Model '{model_name}' has migration_mode='scoring' but "
                        f"does not extend ScoringModel. Falling back to adapted."
                    )
                    adapter = LegacyScoringAdapter(instance)
                    self.adapted_models.append(adapter)
                else:
                    self.scoring_models.append(instance)
                    logger.info(
                        f"Loaded scoring model {model_name} for "
                        f"{self.asset}/{self.timeframe}"
                    )
                continue

            if migration_mode == "adapted":
                adapted_instance = model_cls(params)
                adapter = LegacyScoringAdapter(adapted_instance)
                self.adapted_models.append(adapter)
                logger.info(
                    f"Loaded adapted model {model_name} for "
                    f"{self.asset}/{self.timeframe}"
                )

                if model_cfg.get("comparison_logging", False):
                    shadow_instance = model_cls(params)
                    self.shadow_models.append(shadow_instance)
                    logger.info(
                        f"Loaded shadow model {model_name} for "
                        f"{self.asset}/{self.timeframe} (comparison logging)"
                    )
            else:
                model = model_cls(params)
                self.models.append(model)
                logger.info(f"Loaded model {model_name} for {self.asset}/{self.timeframe}")

    def validate_feature_coverage(self, available_features: set[str] | None = None) -> None:
        if available_features is None:
            available_features = self._available_features_from_config()

        all_models: list[BaseModel] = [
            *self.models,
            *[adapter._wrapped for adapter in self.adapted_models],
            *self.scoring_models,
            *self.shadow_models,
        ]
        for model in all_models:
            missing = model.validate_features(available_features)
            if missing:
                raise ConfigurationError(
                    f"Model '{model.meta.name}' for {self.asset}/{self.timeframe} requires "
                    f"{missing} but features.yaml only provides {sorted(available_features)}"
                )
            missing_fields = model.validate_required_fields(available_features)
            missing_engineered_fields = sorted(
                field for field in missing_fields if field.startswith("eng_")
            )
            if missing_engineered_fields:
                raise ConfigurationError(
                    f"Model '{model.meta.name}' for {self.asset}/{self.timeframe} requires "
                    f"engineered fields {missing_engineered_fields} but features.yaml engineered_features "
                    "does not configure them"
                )
            if missing_fields:
                logger.warning(
                    f"Model '{model.meta.name}' for {self.asset}/{self.timeframe}: "
                    f"required_fields {missing_fields} not found in available features. "
                    f"These will be validated at runtime.",
                )

    def _available_features_from_config(self) -> set[str]:
        features_node = self._resolve_config_node(KEY_FEATURES)
        engineered_node = self._resolve_config_node(KEY_ENGINEERED_FEATURES)
        return build_available_feature_contract(features_node, engineered_node)

    def evaluate(self, features: FeatureVector) -> list[ModelOutput]:
        outputs: list[ModelOutput] = []
        for model in self.models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Model {model.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_adapted(self, features: FeatureVector) -> list[ScoringOutput]:
        outputs: list[ScoringOutput] = []
        for adapter in self.adapted_models:
            try:
                output = adapter.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Adapted model {adapter.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_scoring(self, features: FeatureVector) -> list[ScoringOutput]:
        outputs: list[ScoringOutput] = []
        for model in self.scoring_models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Scoring model {model.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_shadow(self, features: FeatureVector) -> list[ModelOutput]:
        outputs: list[ModelOutput] = []
        for model in self.shadow_models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Shadow model {model.meta.name} failed: {e}", exc_info=True)
        return outputs
