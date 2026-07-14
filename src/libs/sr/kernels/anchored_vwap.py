"""
Anchored VWAP Kernel
====================
Dynamic AVWAP S/R detection anchored to structural pivots or volume spikes.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


@register_kernel("anchored_vwap")
class AnchoredVWAPKernel(BaseSRKernel):
    """
    Dynamic AVWAP lines anchored to recent structural events.

    Config params (via ``KernelConfig.kernel_params``):
      * ``anchor_type`` — ``pivot`` | ``volume_spike`` | ``hybrid``
      * ``volume_spike_multiplier`` — rolling-median multiplier for spike anchors
      * ``min_bars`` — minimum data bars before evaluation
    """

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        pivot_min_bars = config.rule_derived.n1 + config.rule_derived.n2 + 1
        min_bars = max(1, int(params.get("min_bars", max(20, pivot_min_bars))))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        anchor_type = str(params.get("anchor_type", "hybrid")).strip().lower()
        if anchor_type not in {"pivot", "volume_spike", "hybrid"}:
            anchor_type = "hybrid"

        highs = df["high"].to_numpy(dtype=float, copy=False)
        lows = df["low"].to_numpy(dtype=float, copy=False)
        closes = df["close"].to_numpy(dtype=float, copy=False)
        volumes = df["volume"].to_numpy(dtype=float, copy=False)
        timestamps = df.index

        if not np.any(volumes > 0):
            return []

        typical_price = (highs + lows + closes) / 3.0
        cum_volume = np.cumsum(volumes)
        cum_price_volume = np.cumsum(typical_price * volumes)
        last_index = len(df) - 1
        last_close = float(closes[last_index])
        detection_ts = self._to_datetime(timestamps[last_index], fallback_index=last_index)

        volume_window = max(20, int(config.rule_derived.breakout_confirm_bars) * 8)
        rolling_median_volume = (
            pd.Series(volumes)
            .rolling(window=volume_window, min_periods=1)
            .median()
            .to_numpy(dtype=float, copy=False)
        )

        anchors: List[Tuple[str, int]] = []
        if anchor_type in {"pivot", "hybrid"}:
            anchors.extend(
                _latest_pivot_anchors(
                    highs,
                    lows,
                    config.rule_derived.n1,
                    config.rule_derived.n2,
                )
            )
        if anchor_type in {"volume_spike", "hybrid"}:
            spike_index = _latest_volume_spike_anchor(
                volumes,
                rolling_median_volume,
                float(params.get("volume_spike_multiplier", 2.0)),
            )
            if spike_index is not None:
                anchors.append(("volume_spike", spike_index))

        candidates: List[CandidateLevel] = []
        seen_indices = set()
        volume_spike_multiplier = max(float(params.get("volume_spike_multiplier", 2.0)), 1e-9)

        for source, anchor_index in anchors:
            anchor_index = int(anchor_index)
            if anchor_index < 0 or anchor_index > last_index or anchor_index in seen_indices:
                continue

            prev_volume = cum_volume[anchor_index - 1] if anchor_index > 0 else 0.0
            active_volume = cum_volume[last_index] - prev_volume
            if active_volume <= 0:
                continue

            prev_price_volume = cum_price_volume[anchor_index - 1] if anchor_index > 0 else 0.0
            avwap = (cum_price_volume[last_index] - prev_price_volume) / active_volume
            baseline_volume = max(float(rolling_median_volume[anchor_index]), 1e-9)
            anchor_volume_ratio = float(volumes[anchor_index] / baseline_volume)
            raw_score = anchor_volume_ratio
            if source == "volume_spike":
                raw_score /= volume_spike_multiplier

            half_width = params.get("zone_half_width_atr", 0.1) * atr
            candidates.append(
                CandidateLevel(
                    center_price=float(avwap),
                    lower_bound=float(avwap) - half_width,
                    upper_bound=float(avwap) + half_width,
                    level_type=LevelType.SUPPORT if avwap <= last_close else LevelType.RESISTANCE,
                    kernel_name="anchored_vwap",
                    timeframe=config.timeframe,
                    raw_score=float(min(1.0, raw_score)),
                    metadata={
                        "anchor_type": source,
                        "anchor_index": anchor_index,
                        "anchor_price": float(typical_price[anchor_index]),
                        "anchor_volume_ratio": anchor_volume_ratio,
                        "bars_since_anchor": int(last_index - anchor_index),
                        "avwap_price": float(avwap),
                    },
                    timestamp=detection_ts,
                    atr_at_detection=atr,
                )
            )
            seen_indices.add(anchor_index)

        return candidates


def _latest_pivot_anchors(
    highs: np.ndarray,
    lows: np.ndarray,
    n1: int,
    n2: int,
) -> List[Tuple[str, int]]:
    window_size = n1 + n2 + 1
    if len(highs) < window_size:
        return []

    high_windows = np.lib.stride_tricks.sliding_window_view(highs, window_size)
    low_windows = np.lib.stride_tricks.sliding_window_view(lows, window_size)
    center_highs = highs[n1 : len(highs) - n2]
    center_lows = lows[n1 : len(lows) - n2]

    high_pivots = np.where(center_highs == high_windows.max(axis=1))[0]
    low_pivots = np.where(center_lows == low_windows.min(axis=1))[0]

    anchors: List[Tuple[str, int]] = []
    if low_pivots.size:
        anchors.append(("pivot_low", int(low_pivots[-1] + n1)))
    if high_pivots.size:
        anchors.append(("pivot_high", int(high_pivots[-1] + n1)))
    return anchors


def _latest_volume_spike_anchor(
    volumes: np.ndarray,
    rolling_median_volume: np.ndarray,
    multiplier: float,
) -> Optional[int]:
    threshold = rolling_median_volume * max(multiplier, 1.0)
    spike_indices = np.where((rolling_median_volume > 0) & (volumes >= threshold))[0]
    if spike_indices.size == 0:
        return None
    return int(spike_indices[-1])