from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional, Any

import numpy as np

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..contracts.result import MethodResult
from ..registry import PluginRegistry
from ..state import StateManager

MethodRegistry: PluginRegistry["RegressionMethod"] = PluginRegistry("method")


class RegressionMethod(ABC):
    """Base class for all regression method plugins.

    Subclasses declare:
        requires: what feature fields they need (e.g., "log_prices", "volume_weights")
        provides: what output fields they produce
        min_warmup_bars: minimum bars for valid output
        stateful: whether this method carries state across ticks
    """

    requires: ClassVar[List[str]] = ["log_prices"]
    provides: ClassVar[List[str]] = ["slope", "intercept", "center", "confidence", "upper", "lower"]
    min_warmup_bars: ClassVar[int] = 10
    stateful: ClassVar[bool] = False

    def __init__(self, name: str, config: PluginConfig) -> None:
        self.name = name
        self.config = config

    @abstractmethod
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray,
        pipeline_config: ResolvedPipelineConfig,
    ) -> None:
        """Fit the regression model on valid data."""
        ...

    @abstractmethod
    def get_slope(self) -> float:
        ...

    @property
    @abstractmethod
    def intercept(self) -> float:
        ...

    @property
    @abstractmethod
    def is_valid(self) -> bool:
        ...

    @abstractmethod
    def get_bands(self, X: np.ndarray, multiplier: float) -> tuple[np.ndarray, np.ndarray]:
        """Return (upper, lower) bands in the method's native band_type."""
        ...

    @abstractmethod
    def get_confidence(self) -> float:
        ...

    @property
    def band_type(self) -> str:
        return "log_mad"

    def get_metadata(self) -> Dict[str, Any]:
        return {}

    def is_warmed_up(self) -> bool:
        return True

    # ── State management (for stateful plugins) ──

    def save_state(self, state_manager: StateManager, asset: str, timeframe: str) -> None:
        """Persist internal state via state manager. No-op for stateless plugins."""
        pass

    def load_state(self, state_manager: StateManager, asset: str, timeframe: str) -> None:
        """Restore internal state from state manager. No-op for stateless plugins."""
        pass

    def reset_state(self) -> None:
        """Clear internal state for fresh initialization."""
        pass
