from abc import ABC, abstractmethod
from typing import Any


class EngineeredFeature(ABC):
    """Base class for composite features computed from raw indicator outputs."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = params or {}

    @property
    def depends_on_engineered(self) -> bool:
        """Return True if this feature reads other eng_* values from features dict."""
        return False

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique feature name used as the key in FeatureVector.features."""
        ...

    @property
    @abstractmethod
    def required_indicators(self) -> list[str]:
        """List of raw indicator keys this feature needs from FeatureVector.features."""
        ...

    @property
    @abstractmethod
    def required_bar_fields(self) -> list[str]:
        """List of bar_data fields needed (e.g. ['close', 'volume'])."""
        ...

    @abstractmethod
    def compute(
        self,
        features: dict[str, Any],
        bar_data: dict[str, float],
        state: dict[str, Any],
        index_data: dict[str, dict[str, float]] | None = None,
    ) -> float | None:
        """Compute the engineered feature value.

        Args:
            features: Raw indicator outputs from FeatureManager
            bar_data: OHLCV bar data
            state: Mutable per-feature state dict for rolling computations.
                   The manager maintains one state dict per feature instance.
            index_data: Optional cross-sectional index data from TradingView
                        (e.g. BTC.D, TOTAL2, TOTAL3 latest values).

        Returns:
            float value, or None if insufficient data.
        """
        ...
