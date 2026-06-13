from __future__ import annotations

from typing import Any

from libs.features.engineered.manager import EngineeredFeatureManager


class EngineeredFeaturePipeline:
    """Thin v2 seam over reusable engineered feature logic."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        manager: EngineeredFeatureManager | None = None,
    ) -> None:
        self.asset = asset.upper()
        self.timeframe = timeframe
        self.manager = manager or EngineeredFeatureManager(self.asset, self.timeframe)

    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        *,
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, float]:
        return self.manager.compute(
            features,
            bar_data,
            index_data=index_data if index_data else None,
        )

    def validate_inputs(
        self,
        *,
        available_indicators: set[str],
        available_bar_fields: set[str],
    ) -> list[str]:
        return self.manager.validate_inputs(
            available_indicators=available_indicators,
            available_bar_fields=available_bar_fields,
        )
