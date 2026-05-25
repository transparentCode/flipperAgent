"""ModelManager — config-driven model loading and feature validation."""

from __future__ import annotations

from typing import Any

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import ConfigurationError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import FeatureVector, ModelOutput
from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry

# Ensure concrete models are registered on import.
import libs.models  # noqa: F401

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

CONFIG_FILE_MODELS = "configs/models.yaml"
CONFIG_FILE_FEATURES = "configs/features.yaml"

KEY_MODELS = "models"
KEY_FEATURES = "features"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"


class ModelManager:
    """Loads models for a specific (asset, timeframe) from ``configs/models.yaml``."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.config_mgr = ConfigManager()
        self.config_mgr.register_file(CONFIG_FILE_MODELS)
        self.config_mgr.register_file(CONFIG_FILE_FEATURES)

        self.models: list[BaseModel] = []
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
            params = model_cfg.get("params", {}) or {}
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

        for model in self.models:
            missing = model.validate_features(available_features)
            if missing:
                raise ConfigurationError(
                    f"Model '{model.meta.name}' for {self.asset}/{self.timeframe} requires "
                    f"{missing} but features.yaml only provides {sorted(available_features)}"
                )

    def _available_features_from_config(self) -> set[str]:
        """Read configured indicator names from features.yaml for this asset/timeframe."""
        features_node = self._resolve_config_node(KEY_FEATURES)
        return set(features_node.keys())

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> list[ModelOutput]:
        """Run all active models on a feature vector."""
        outputs: list[ModelOutput] = []
        for model in self.models:
            try:
                output = model.evaluate(features)
                outputs.append(output)
            except Exception as e:
                logger.error(f"Model {model.meta.name} failed: {e}", exc_info=True)
        return outputs
