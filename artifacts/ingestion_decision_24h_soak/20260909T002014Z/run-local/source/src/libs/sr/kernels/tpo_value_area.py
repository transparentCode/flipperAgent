"""
TPO Value Area Kernel
=====================
Rolling time-price opportunity (TPO) value-area detection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.kernels.volume_poc import _extract_value_area
from app.sr.models import CandidateLevel


@register_kernel("tpo_value_area")
class TPOValueAreaKernel(BaseSRKernel):
    """
    Rolling time-acceptance profile kernel.

    Config params (via ``KernelConfig.kernel_params``):
      * ``tpo_window_bars`` — rolling lookback window (default 120)
      * ``tpo_value_area_pct`` — value area fraction (default 0.68)
      * ``min_bars`` — minimum data bars before evaluation
    """

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        window_bars = max(1, int(params.get("tpo_window_bars", 120)))
        min_bars = max(1, int(params.get("min_bars", min(20, window_bars))))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        highs_arr = df["high"].to_numpy(dtype=float, copy=False)
        lows_arr = df["low"].to_numpy(dtype=float, copy=False)
        closes_arr = df["close"].to_numpy(dtype=float, copy=False)

        value_area_pct = float(params.get("tpo_value_area_pct", 0.68))
        value_area_pct = min(max(value_area_pct, 0.01), 0.99)

        if getattr(config, "_is_walk_forward_fold", False):
            candidate_start = int(params.get("start_index", 0))
            candidate_end = int(params.get("end_index", len(df)))
        else:
            candidate_end = len(df)
            candidate_start = candidate_end - 1 if candidate_end > 0 else 0

        candidates: List[CandidateLevel] = []
        candidate_indices = np.arange(candidate_start, candidate_end)
        for i in candidate_indices:
            start_idx = max(0, i + 1 - window_bars)
            highs = highs_arr[start_idx: i + 1]
            lows = lows_arr[start_idx: i + 1]
            closes = closes_arr[start_idx: i + 1]

            active_window = len(highs)
            if active_window < min_bars:
                continue

            profile = _build_time_profile(highs, lows, _derived_num_bins(active_window))
            poc, vah, val = _extract_value_area(profile, value_area_pct)
            if poc is None:
                continue

            bins = profile["bins"]
            acceptance = profile["volumes"]
            max_acceptance = max(float(acceptance.max()), 1e-9)
            last_close = float(closes[-1])
            detection_ts = self._to_datetime(df.index[i], fallback_index=int(i))

            poc_idx = int(np.argmax(acceptance))
            poc_lower = float(bins[poc_idx])
            poc_upper = float(bins[poc_idx + 1])
            candidates.append(
                CandidateLevel(
                    center_price=float(poc),
                    lower_bound=poc_lower,
                    upper_bound=poc_upper,
                    level_type=LevelType.SUPPORT if poc <= last_close else LevelType.RESISTANCE,
                    kernel_name="tpo_value_area",
                    timeframe=config.timeframe,
                    raw_score=1.0,
                    metadata={
                        "tpo_type": "poc",
                        "window_bars": active_window,
                        "naked": _is_level_naked(highs, lows, poc_lower, poc_upper),
                    },
                    timestamp=detection_ts,
                    atr_at_detection=atr,
                )
            )

            if vah is not None:
                vah_idx = _bin_index_for_price(bins, vah)
                vah_lower, vah_upper = _bin_bounds(bins, vah_idx)
                candidates.append(
                    CandidateLevel(
                        center_price=float(vah),
                        lower_bound=vah_lower,
                        upper_bound=vah_upper,
                        level_type=LevelType.RESISTANCE,
                        kernel_name="tpo_value_area",
                        timeframe=config.timeframe,
                        raw_score=float(min(1.0, acceptance[vah_idx] / max_acceptance)),
                        metadata={
                            "tpo_type": "vah",
                            "window_bars": active_window,
                            "naked": _is_level_naked(highs, lows, vah_lower, vah_upper),
                        },
                        timestamp=detection_ts,
                        atr_at_detection=atr,
                    )
                )

            if val is not None:
                val_idx = _bin_index_for_price(bins, val)
                val_lower, val_upper = _bin_bounds(bins, val_idx)
                candidates.append(
                    CandidateLevel(
                        center_price=float(val),
                        lower_bound=val_lower,
                        upper_bound=val_upper,
                        level_type=LevelType.SUPPORT,
                        kernel_name="tpo_value_area",
                        timeframe=config.timeframe,
                        raw_score=float(min(1.0, acceptance[val_idx] / max_acceptance)),
                        metadata={
                            "tpo_type": "val",
                            "window_bars": active_window,
                            "naked": _is_level_naked(highs, lows, val_lower, val_upper),
                        },
                        timestamp=detection_ts,
                        atr_at_detection=atr,
                    )
                )

        return candidates


def _last_window(values: np.ndarray, window_bars: int) -> np.ndarray:
    if len(values) <= window_bars:
        return values
    return np.lib.stride_tricks.sliding_window_view(values, window_bars)[-1]


def _derived_num_bins(window_bars: int) -> int:
    return int(np.clip(round(np.sqrt(window_bars) * 4.0), 20, 80))


def _build_time_profile(
    highs: np.ndarray,
    lows: np.ndarray,
    num_bins: int,
) -> Dict[str, Any]:
    if len(highs) == 0:
        return {
            "bins": np.array([]),
            "bin_centers": np.array([]),
            "volumes": np.array([]),
            "total_volume": 0.0,
        }

    price_min = float(np.min(lows))
    price_max = float(np.max(highs))
    if price_min == price_max:
        price_max = price_min * 1.001

    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    lo_idx = np.searchsorted(bins, lows, side="right").astype(np.int64) - 1
    hi_idx = np.searchsorted(bins, highs, side="left").astype(np.int64)
    lo_idx = np.maximum(lo_idx, 0)
    hi_idx = np.minimum(hi_idx, num_bins)
    hi_idx = np.where(hi_idx <= lo_idx, lo_idx + 1, hi_idx)

    valid = (lo_idx < num_bins) & (hi_idx > lo_idx)
    acceptance = np.zeros(num_bins, dtype=float)
    if np.any(valid):
        lo_idx = lo_idx[valid]
        hi_idx = hi_idx[valid]
        weights = np.ones_like(lo_idx, dtype=float) / (hi_idx - lo_idx)
        diff = (
            np.bincount(lo_idx, weights=weights, minlength=num_bins + 1)
            - np.bincount(hi_idx, weights=weights, minlength=num_bins + 1)
        )
        acceptance = np.cumsum(diff[:-1])

    return {
        "bins": bins,
        "bin_centers": bin_centers,
        "volumes": acceptance,
        "total_volume": float(acceptance.sum()),
    }


def _bin_index_for_price(bins: np.ndarray, price: float) -> int:
    return int(np.clip(np.searchsorted(bins, price, side="right") - 1, 0, len(bins) - 2))


def _bin_bounds(bins: np.ndarray, index: int) -> Tuple[float, float]:
    bounded_index = int(np.clip(index, 0, len(bins) - 2))
    return float(bins[bounded_index]), float(bins[bounded_index + 1])


def _is_level_naked(
    highs: np.ndarray,
    lows: np.ndarray,
    lower_bound: float,
    upper_bound: float,
) -> bool:
    touches = (lows <= upper_bound) & (highs >= lower_bound)
    touch_indices = np.flatnonzero(touches)
    if touch_indices.size == 0:
        return True
    return int(touch_indices[-1]) < len(highs) - 1