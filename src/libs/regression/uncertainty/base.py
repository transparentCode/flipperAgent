from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, List, Tuple

import numpy as np

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..registry import PluginRegistry

UncertaintyRegistry: PluginRegistry["UncertaintyWrapper"] = PluginRegistry("uncertainty")


class UncertaintyWrapper(ABC):
    """Base class for uncertainty/band generation plugins.

    Takes method residuals and produces price-space bands.
    """

    requires: ClassVar[List[str]] = ["method_residuals"]
    provides: ClassVar[List[str]] = ["upper_band", "lower_band", "mid_line"]
    min_warmup_bars: ClassVar[int] = 0

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    @abstractmethod
    def wrap(
        self,
        X_valid: np.ndarray,
        y_valid: np.ndarray,
        w_valid: np.ndarray,
        slope: float,
        intercept: float,
        multiplier: float,
        X_full: np.ndarray,
        pipeline_config: ResolvedPipelineConfig,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute bands.

        Returns:
            (upper_band, lower_band, mid_line) — all in price space, shape matches X_full.
        """
        ...
