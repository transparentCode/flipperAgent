from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS

from apps.signal_app.models import SignalPair


class SignalPairCatalog:
    """Resolves effective signal asset/timeframe pairs from config.

    This intentionally mirrors the current config-driven runtime behavior while
    leaving room for a runtime registry in a later phase.
    """

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.config_manager.register_file(CONFIG_FILE_MODELS)
        self.config_manager.register_file(CONFIG_FILE_FEATURES)

    def list_pairs(self) -> list[SignalPair]:
        models_config = self.config_manager.get("models", {})
        assets_config = models_config.get("assets", {})
        pairs: list[SignalPair] = []

        for asset, asset_config in assets_config.items():
            if asset == "default" or not isinstance(asset_config, dict):
                continue
            timeframes = asset_config.get("timeframes", {})
            if not isinstance(timeframes, dict):
                continue
            for timeframe in timeframes:
                if timeframe == "default":
                    continue
                pairs.append(SignalPair(asset=asset, timeframe=timeframe))

        return pairs

    def get_pair(self, asset: str, timeframe: str) -> SignalPair | None:
        normalized = SignalPair(asset=asset, timeframe=timeframe)
        for pair in self.list_pairs():
            if pair.key == normalized.key:
                return pair
        return None

