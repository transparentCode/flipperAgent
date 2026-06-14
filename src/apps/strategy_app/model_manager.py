"""Compatibility shim for ModelManager."""

from __future__ import annotations

from libs.common.config import ConfigManager

from apps.strategy_app.models.model_manager import ModelManager as _ModelManager


class ModelManager(_ModelManager):
    """Backward-compatible wrapper preserving old patch points."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config_manager: ConfigManager | None = None,
    ) -> None:
        super().__init__(
            asset,
            timeframe,
            config_manager=config_manager or ConfigManager(),
        )


__all__ = ["ConfigManager", "ModelManager"]
