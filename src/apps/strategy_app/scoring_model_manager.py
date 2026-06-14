"""Compatibility shim for ScoringModelManager."""

from __future__ import annotations

from libs.common.config import ConfigManager

from apps.strategy_app.models.scoring_model_manager import (
    ScoringModelManager as _ScoringModelManager,
)


class ScoringModelManager(_ScoringModelManager):
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


__all__ = ["ConfigManager", "ScoringModelManager"]
