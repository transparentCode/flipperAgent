"""Percentile (MAD) bands uncertainty wrapper.

Ported from v1 ``app/regression/uncertainty/mad_bands.py``.
Computes Median Absolute Deviation bands in log space, returns price-space arrays.
"""
from __future__ import annotations

from typing import ClassVar, List, Tuple

import numpy as np
from numba import njit

from ..config.schema import PluginConfig, ResolvedPipelineConfig
from ..constants import MAD_GAUSSIAN_SCALE
from .base import UncertaintyWrapper, UncertaintyRegistry


@njit(cache=True, nogil=True)
def _median_in_place(values: np.ndarray) -> float:
    values.sort()
    size = len(values)
    mid = size // 2
    if size % 2 == 0:
        return 0.5 * (values[mid - 1] + values[mid])
    return values[mid]


@njit(cache=True, nogil=True)
def _calc_mad_bands(
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    slope: float,
    intercept: float,
    effective_mult: float,
    mad_scale_factor: float,
    X_full: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    valid_size = len(X_valid)
    full_size = len(X_full)

    work = np.empty(valid_size, dtype=np.float64)
    for i in range(valid_size):
        work[i] = y_valid[i] - (slope * X_valid[i] + intercept)

    residual_median = _median_in_place(work)

    for i in range(valid_size):
        work[i] = abs(work[i] - residual_median)

    mad = _median_in_place(work)

    upper = np.empty(full_size, dtype=np.float64)
    lower = np.empty(full_size, dtype=np.float64)
    mid = np.empty(full_size, dtype=np.float64)

    if mad < 1e-10:
        for i in range(full_size):
            mid_value = np.exp(slope * X_full[i] + intercept)
            upper[i] = mid_value
            lower[i] = mid_value
            mid[i] = mid_value
        return upper, lower, mid

    band_offset = mad_scale_factor * mad * effective_mult
    for i in range(full_size):
        line_log = slope * X_full[i] + intercept
        upper[i] = np.exp(line_log + band_offset)
        lower[i] = np.exp(line_log - band_offset)
        mid[i] = np.exp(line_log)

    return upper, lower, mid


@UncertaintyRegistry.register("percentile_bands")
class PercentileBands(UncertaintyWrapper):
    requires: ClassVar[List[str]] = ["method_residuals"]
    provides: ClassVar[List[str]] = ["upper_band", "lower_band", "mid_line"]

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self.band_mult: float = config.get("band_mult", 2.0)
        self.mad_scale_factor: float = config.get("mad_scale_factor", MAD_GAUSSIAN_SCALE)

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
        if np.isnan(slope) or np.isnan(intercept):
            empty = np.zeros(len(X_full))
            return empty, empty, empty

        if len(X_valid) < 3:
            empty = np.zeros(len(X_full))
            return empty, empty, empty

        effective_mult = multiplier if multiplier is not None else self.band_mult

        x_valid_arr = np.ascontiguousarray(X_valid, dtype=np.float64).reshape(-1)
        y_valid_arr = np.ascontiguousarray(y_valid, dtype=np.float64).reshape(-1)
        x_full_arr = np.ascontiguousarray(X_full, dtype=np.float64).reshape(-1)

        return _calc_mad_bands(
            x_valid_arr,
            y_valid_arr,
            float(slope),
            float(intercept),
            float(effective_mult),
            float(self.mad_scale_factor),
            x_full_arr,
        )
