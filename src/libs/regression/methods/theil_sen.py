"""Volume-Weighted Theil-Sen regression method.

Ported from v1 ``app/regression/methods/theil_sen.py`` with deterministic
recent-anchor subsampling. ``max_pairs`` is the canonical config key; legacy
``samples`` is still accepted.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Dict, List

import numpy as np
from numba import njit

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..constants import MAD_GAUSSIAN_SCALE
from ..contracts.result import MethodResult
from ..methods.base import RegressionMethod, MethodRegistry

logger = logging.getLogger(__name__)


@njit(cache=True, nogil=True)
def _weighted_median(values, weights):
    total_weight = np.sum(weights)
    if total_weight <= 1e-9:
        mid = len(values) // 2
        return values[mid]

    target = total_weight / 2.0
    current_w = 0.0

    for i in range(len(values)):
        current_w += weights[i]
        if current_w >= target:
            return values[i]
    return values[-1]


@njit(cache=True, nogil=True)
def _local_step_std(y):
    if len(y) < 2:
        return 0.0

    diff_count = len(y) - 1
    mean_diff = 0.0
    for i in range(diff_count):
        mean_diff += y[i + 1] - y[i]
    mean_diff /= diff_count

    variance = 0.0
    for i in range(diff_count):
        centered = (y[i + 1] - y[i]) - mean_diff
        variance += centered * centered

    return np.sqrt(variance / diff_count)


@njit(cache=True, nogil=True)
def _calc_theil_sen_last(y, v, x, samples_per_window):
    n = len(y)
    max_possible_pairs = (n * (n - 1)) // 2
    use_subsampling = (samples_per_window > 0) and (max_possible_pairs > samples_per_window)
    n_samples = samples_per_window if use_subsampling else max_possible_pairs

    slopes = np.zeros(n_samples)
    weights = np.zeros(n_samples)
    count = 0

    if not use_subsampling:
        for i in range(n):
            for j in range(i + 1, n):
                dx = x[j] - x[i]
                if dx == 0:
                    continue
                slopes[count] = (y[j] - y[i]) / dx
                w = min(v[i], v[j])
                weights[count] = w if w > 0 else 0.0
                count += 1
    else:
        recent_count = max(1, n // 4)
        recent_start = max(1, n - recent_count)
        local_noise = _local_step_std(y)
        candidate_pairs = 0

        for jj in range(recent_start, n):
            for ii in range(jj):
                dx = x[jj] - x[ii]
                if dx == 0:
                    continue
                if np.abs(y[jj] - y[ii]) <= local_noise:
                    continue
                candidate_pairs += 1

        if candidate_pairs == 0:
            return np.nan, np.nan

        take_all_candidates = candidate_pairs <= n_samples
        candidate_idx = 0

        for jj in range(recent_start, n):
            for ii in range(jj):
                dx = x[jj] - x[ii]
                if dx == 0:
                    continue

                dy = y[jj] - y[ii]
                if np.abs(dy) <= local_noise:
                    continue

                take_pair = take_all_candidates
                if not take_all_candidates:
                    prev_bucket = (candidate_idx * n_samples) // candidate_pairs
                    next_bucket = ((candidate_idx + 1) * n_samples) // candidate_pairs
                    take_pair = next_bucket > prev_bucket

                if take_pair:
                    slopes[count] = dy / dx
                    w = min(v[ii], v[jj])
                    weights[count] = w if w > 0 else 0.0
                    count += 1
                    if count >= n_samples:
                        break

                candidate_idx += 1
            if count >= n_samples:
                break

    if count < 2:
        return np.nan, np.nan

    valid_slopes = slopes[:count]
    valid_weights = weights[:count]

    sort_idxs = np.argsort(valid_slopes)
    sorted_slopes = valid_slopes[sort_idxs]
    sorted_weights = valid_weights[sort_idxs]

    med_slope = _weighted_median(sorted_slopes, sorted_weights)

    raw_intercepts = y - med_slope * x
    i_idxs = np.argsort(raw_intercepts)
    sorted_ints = raw_intercepts[i_idxs]
    sorted_int_w = v[i_idxs]

    med_intercept = _weighted_median(sorted_ints, sorted_int_w)

    return med_slope, med_intercept


# Warm up Numba JIT
def _warmup_numba():
    _y = np.array([1.0, 2.0, 3.0])
    _x = np.array([0.0, 1.0, 2.0])
    _v = np.array([1.0, 1.0, 1.0])
    _weighted_median(np.array([1.0, 2.0, 3.0]), np.array([1.0, 1.0, 1.0]))
    _calc_theil_sen_last(_y, _v, _x, 0)


try:
    _warmup_numba()
except Exception as e:
    logger.warning("Numba JIT warmup failed: %s. First call will be slow.", e)


@MethodRegistry.register("theil_sen")
class TheilSenMethod(RegressionMethod):
    requires: ClassVar[List[str]] = ["log_prices", "weights"]
    provides: ClassVar[List[str]] = ["slope", "intercept", "center", "confidence", "upper", "lower"]
    min_warmup_bars: ClassVar[int] = 20
    stateful: ClassVar[bool] = False

    def __init__(self, name: str, config: PluginConfig) -> None:
        super().__init__(name, config)
        self.max_pairs: int = int(config.get("max_pairs", config.get("samples", 300)))
        self._slope = np.nan
        self._intercept = np.nan
        self._r_squared = 0.0
        self._raw_pseudo_r2 = 0.0
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
        if len(X) < 3:
            self._is_valid = False
            return

        y_arr = np.ascontiguousarray(y, dtype=np.float64).flatten()
        w_arr = np.ascontiguousarray(weights, dtype=np.float64).flatten()
        x_arr = np.ascontiguousarray(X, dtype=np.float64).flatten()

        self._slope, self._intercept = _calc_theil_sen_last(y_arr, w_arr, x_arr, self.max_pairs)

        if np.isnan(self._slope) or np.isnan(self._intercept):
            self._is_valid = False
            return

        fitted_y = self._intercept + self._slope * x_arr
        residuals = y_arr - fitted_y

        # Proper MAD: median(|e - median(e)|), consistent with WLS
        self._mad = float(np.median(np.abs(residuals - np.median(residuals))))
        mad_y = float(np.median(np.abs(y_arr - np.median(y_arr))))

        n = len(x_arr)
        if mad_y > 1e-9:
            self._raw_pseudo_r2 = 1.0 - (self._mad / mad_y)
            self._r_squared = max(0.0, self._raw_pseudo_r2)
            # Sample-size penalty: consistent with WLS confidence formula
            self._confidence = max(0.0, min(1.0, self._r_squared * (1.0 - 1.0 / np.sqrt(n))))
        else:
            self._raw_pseudo_r2 = 0.0
            self._r_squared = 0.0
            self._confidence = 0.0

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

        x_flat = X.flatten() if X.ndim > 1 else X
        center_log = self._slope * x_flat + self._intercept
        scaled_mad = self._mad * MAD_GAUSSIAN_SCALE * multiplier

        upper_log = center_log + scaled_mad
        lower_log = center_log - scaled_mad

        return np.exp(upper_log), np.exp(lower_log)

    def get_confidence(self) -> float:
        return self._confidence

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "pseudo_r2": self._r_squared,
            "raw_pseudo_r2": self._raw_pseudo_r2,
            "mad": self._mad,
            "max_pairs": self.max_pairs,
        }

    @property
    def band_type(self) -> str:
        return "log_mad"
