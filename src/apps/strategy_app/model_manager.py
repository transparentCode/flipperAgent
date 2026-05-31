"""ModelManager — config-driven model loading and feature validation."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_MODELS, CONFIG_FILE_FEATURES
from libs.common.enums import SystemComponent
from libs.common.exceptions import ConfigurationError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel
from libs.models.legacy_adapter import LegacyScoringAdapter
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel

# Ensure concrete models are registered on import.
import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

KEY_MODELS = "models"
KEY_FEATURES = "features"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"

_VALID_MIGRATION_MODES = {"legacy", "adapted", "scoring", "native_scoring"}


class ModelManager:
    """Loads models for a specific (asset, timeframe) from ``configs/models.yaml``."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.config_mgr = ConfigManager()
        self.config_mgr.register_file(CONFIG_FILE_MODELS)
        self.config_mgr.register_file(CONFIG_FILE_FEATURES)

        self.models: list[BaseModel] = []
        self.adapted_models: list[LegacyScoringAdapter] = []
        self.scoring_models: list[ScoringModel] = []
        self.shadow_models: list[BaseModel] = []
        self._load_models()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _resolve_config_node(self, root_key: str) -> dict[str, Any]:
        """Resolve config with fallback chain: asset/tf → asset/default → default/tf → default/default."""
        config = self.config_mgr.get(root_key, {})
        assets_config = config.get(KEY_ASSETS, {})

        # Asset-level node (fallback to default)
        asset_node = assets_config.get(self.asset, {})
        default_asset_node = assets_config.get(KEY_DEFAULT, {})

        # Timeframe-level nodes
        tf_node = asset_node.get(KEY_TIMEFRAMES, {}).get(self.timeframe, {})
        asset_default_tf = asset_node.get(KEY_TIMEFRAMES, {}).get(KEY_DEFAULT, {})
        default_tf_node = default_asset_node.get(KEY_TIMEFRAMES, {}).get(self.timeframe, {})
        default_default_tf = default_asset_node.get(KEY_TIMEFRAMES, {}).get(KEY_DEFAULT, {})

        # Merge with priority: specific first
        merged: dict[str, Any] = {}
        for node in (default_default_tf, default_tf_node, asset_default_tf, tf_node):
            merged.update(node)
        return merged

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
                # Adapted: wrap in LegacyScoringAdapter
                adapted_instance = model_cls(params)
                adapter = LegacyScoringAdapter(adapted_instance)
                self.adapted_models.append(adapter)
                logger.info(
                    f"Loaded adapted model {model_name} for "
                    f"{self.asset}/{self.timeframe}"
                )

                # Shadow: separate instance for comparison logging
                if model_cfg.get("comparison_logging", False):
                    shadow_instance = model_cls(params)
                    self.shadow_models.append(shadow_instance)
                    logger.info(
                        f"Loaded shadow model {model_name} for "
                        f"{self.asset}/{self.timeframe} (comparison logging)"
                    )
            else:
                # Legacy (default)
                model = model_cls(params)
                self.models.append(model)
                logger.info(f"Loaded model {model_name} for {self.asset}/{self.timeframe}")

    # ------------------------------------------------------------------
    # Feature coverage validation (called at boot)
    # ------------------------------------------------------------------

    def validate_feature_coverage(self, available_features: set[str] | None = None) -> None:
        """Validate that all required indicators are configured in features.yaml."""
        if available_features is None:
            available_features = self._available_features_from_config()

        all_models: list[BaseModel] = [
            *self.models,
            *[a._wrapped for a in self.adapted_models],
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
            if missing_fields:
                logger.warning(
                    f"Model '{model.meta.name}' for {self.asset}/{self.timeframe}: "
                    f"required_fields {missing_fields} not found in available features. "
                    f"These will be validated at runtime.",
                )

    def _available_features_from_config(self) -> set[str]:
        """Read configured indicator names from features.yaml for this asset/timeframe.

        Both the config key (e.g. ``EMA_fast``) and any explicit ``type``
        value (e.g. ``EMA``) are considered available so that models can
        declare a requirement like ``"EMA"`` satisfied by ``EMA_fast``.
        """
        features_node = self._resolve_config_node(KEY_FEATURES)
        available = set(features_node.keys())
        for key, cfg in features_node.items():
            if isinstance(cfg, dict) and "type" in cfg:
                available.add(cfg["type"])
        return available

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> list[ModelOutput]:
        """Run all active legacy-mode models on a feature vector."""
        outputs: list[ModelOutput] = []
        for model in self.models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Model {model.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_adapted(self, features: FeatureVector) -> list[ScoringOutput]:
        """Run all adapted-mode models, returning ScoringOutput."""
        outputs: list[ScoringOutput] = []
        for adapter in self.adapted_models:
            try:
                output = adapter.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Adapted model {adapter.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_scoring(self, features: FeatureVector) -> list[ScoringOutput]:
        """Run native scoring-mode models, returning ScoringOutput."""
        outputs: list[ScoringOutput] = []
        for model in self.scoring_models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Scoring model {model.meta.name} failed: {e}", exc_info=True)
        return outputs

    def evaluate_shadow(self, features: FeatureVector) -> list[ModelOutput]:
        """Run shadow models for comparison logging (not sent to SelectionLayer)."""
        outputs: list[ModelOutput] = []
        for model in self.shadow_models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Shadow model {model.meta.name} failed: {e}", exc_info=True)
        return outputs
