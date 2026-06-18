from __future__ import annotations

from libs.common.config import ConfigManager
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS

from apps.signal_app.models import SignalPair
from apps.signal_app.runtime_pairs import build_signal_pairs


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
        return build_signal_pairs(self.config_manager)

    def get_pair(self, asset: str, timeframe: str) -> SignalPair | None:
        normalized = SignalPair(asset=asset, timeframe=timeframe)
        for pair in self.list_pairs():
            if pair.key == normalized.key or (
                pair.asset == normalized.asset and pair.timeframe == normalized.timeframe
            ):
                return pair
        return None
