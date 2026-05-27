from typing import Any

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES
from libs.common.logging.logger_utils import bind_logger
from libs.features.engineered.base import EngineeredFeature
from libs.features.engineered.registry import EngineeredFeatureRegistry

# Ensure feature registrations are triggered
import libs.features.engineered.features  # noqa: F401

logger = bind_logger(__name__)


class EngineeredFeatureManager:
    """Computes engineered features from raw indicator outputs."""

    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self._features: list[EngineeredFeature] = []
        self._state: dict[str, dict[str, Any]] = {}
        self._initialize()

    def _initialize(self) -> None:
        """Load engineered features from config."""
        config_mgr = ConfigManager()
        config_mgr.register_file(CONFIG_FILE_FEATURES)
        eng_config = config_mgr.get("engineered_features", {})

        # Same fallback chain as FeatureManager:
        # asset/tf → asset/default → default/tf → default/default
        assets_config = eng_config.get("assets", {})
        asset_node = assets_config.get(self.asset, assets_config.get("default", {}))
        tf_node = asset_node.get("timeframes", {}).get(
            self.timeframe, asset_node.get("timeframes", {}).get("default", {})
        )

        if not tf_node:
            logger.info(
                f"No engineered_features config for {self.asset}/{self.timeframe}, "
                "no engineered features loaded."
            )
            return

        for feat_name, feat_params in tf_node.items():
            if isinstance(feat_params, dict) and not feat_params.get("enabled", True):
                continue
            try:
                feat_cls = EngineeredFeatureRegistry.get(feat_name)
                self._features.append(feat_cls())
                self._state[feat_name] = {}
                logger.info(
                    f"Loaded engineered feature '{feat_name}' for "
                    f"{self.asset}/{self.timeframe}"
                )
            except KeyError:
                logger.warning(
                    f"Engineered feature '{feat_name}' not found in registry, skipping."
                )

    def validate_inputs(
        self,
        available_indicators: set[str],
        available_bar_fields: set[str],
    ) -> list[str]:
        """Return list of missing dependencies."""
        missing = []
        for feat in self._features:
            for ind in feat.required_indicators:
                if ind not in available_indicators:
                    missing.append(f"{feat.name} requires indicator '{ind}'")
            for bf in feat.required_bar_fields:
                if bf not in available_bar_fields:
                    missing.append(f"{feat.name} requires bar field '{bf}'")
        return missing

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
    ) -> dict[str, float]:
        """Compute all configured engineered features.

        Args:
            features: Raw indicator outputs (from FeatureManager.process_tick)
            bar_data: OHLCV data

        Returns:
            Dict mapping engineered feature name → float value.
            Keys are prefixed with 'eng_' to distinguish from raw indicators.
        """
        results: dict[str, float] = {}
        for feat in self._features:
            try:
                value = feat.compute(features, bar_data, self._state[feat.name])
                if value is not None:
                    results[f"eng_{feat.name}"] = value
            except Exception as e:
                logger.error(
                    f"Engineered feature '{feat.name}' failed: {e}", exc_info=True
                )
        return results
