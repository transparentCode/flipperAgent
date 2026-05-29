"""Weighted Least Squares regression methods.

Ported from v1 ``app/regression/methods/wls.py`` with identical math.
VWR = WLS with volume weights.
"""
from __future__ import annotations

from typing import Any, ClassVar, Dict, List

import numpy as np

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..constants import MAD_GAUSSIAN_SCALE
from ..methods.base import RegressionMethod, MethodRegistry

_VALID_WEIGHT_STRATEGIES = ("uniform", "volume_weighted")


class _WLSBase(RegressionMethod):
    """Shared WLS math for weighted least squares methods."""

    requires: ClassVar[List[str]] = ["log_prices"]
    provides: ClassVar[List[str]] = ["slope", "intercept", "center", "confidence", "upper", "lower"]
    min_warmup_bars: ClassVar[int] = 10
    stateful: ClassVar[bool] = False

    def __init__(self, name: str, config: PluginConfig, weight_strategy: str = "uniform") -> None:
        super().__init__(name, config)
        self._weight_strategy = weight_strategy
        self._slope = np.nan
        self._intercept = np.nan
        self._r_squared = 0.0
        self._raw_r_squared = 0.0
        self._confidence = 0.0
        self._mad = np.nan
        self._is_valid = False

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        weights: np.ndarray,
        pipeline_config: ResolvedPipelineConfig,
    ) -> None:
        X = np.asarray(X, dtype=np.float64).flatten()
        y = np.asarray(y, dtype=np.float64).flatten()
        weights = np.asarray(weights, dtype=np.float64).flatten()

        if len(X) < 3:
            self._is_valid = False
            return

        if self._weight_strategy == "uniform":
            w = np.ones_like(X, dtype=np.float64)
        else:
            w = weights

        W = np.sum(w)
        if W <= 0:
            self._is_valid = False
            return

        x_mean = np.sum(w * X) / W
        y_mean = np.sum(w * y) / W

        cov_xy = np.sum(w * (X - x_mean) * (y - y_mean))
        var_x = np.sum(w * (X - x_mean) ** 2)

        if var_x <= 1e-9:
            self._is_valid = False
            return

        self._slope = cov_xy / var_x
        self._intercept = y_mean - self._slope * x_mean

        y_pred = self._slope * X + self._intercept
        ss_tot = np.sum(w * (y - y_mean) ** 2)
        ss_res = np.sum(w * (y - y_pred) ** 2)

        if ss_tot > 1e-9:
            self._raw_r_squared = 1.0 - (ss_res / ss_tot)
            self._r_squared = max(0.0, self._raw_r_squared)
        else:
            self._raw_r_squared = 0.0
            self._r_squared = 0.0

        n = len(X)
        self._confidence = max(0.0, min(1.0, self._r_squared * (1.0 - 1.0 / np.sqrt(n))))

        residuals = y - y_pred
        self._mad = float(np.median(np.abs(residuals - np.median(residuals))))
        self._is_valid = True

    @property
    def is_valid(self) -> bool:
        return self._is_valid

    @property
    def intercept(self) -> float:
        return self._intercept

    def get_slope(self) -> float:
        return self._slope

    def get_bands(self, X: np.ndarray, multiplier: float) -> tuple[np.ndarray, np.ndarray]:
        if not self._is_valid or np.isnan(self._mad):
            return np.array([]), np.array([])

        x_flat = np.asarray(X, dtype=np.float64).flatten()
        center_log = self._slope * x_flat + self._intercept
        scaled_mad = self._mad * MAD_GAUSSIAN_SCALE * multiplier

        return np.exp(center_log + scaled_mad), np.exp(center_log - scaled_mad)

    def get_confidence(self) -> float:
        return self._confidence

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "r_squared": self._r_squared,
            "raw_r_squared": self._raw_r_squared,
            "mad": self._mad,
            "weight_strategy": self._weight_strategy,
        }

    @property
    def band_type(self) -> str:
        return "log_mad"


@MethodRegistry.register("vwr")
class VWRMethod(_WLSBase):
    """WLS with volume weights. Downweights low-volume manipulation candles."""

    requires: ClassVar[List[str]] = ["log_prices", "weights"]

    def __init__(self, name: str, config: PluginConfig) -> None:
        super().__init__(name, config, weight_strategy="volume_weighted")
