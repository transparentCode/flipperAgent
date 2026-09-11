"""
Fair Value Gap Kernel
======================
Detects 3-candle fair value gaps (FVGs) as S/R candidates.

An FVG is a gap between candle 1's wick and candle 3's wick,
created by a strong candle 2 that leaves unfilled price space:

  * Bullish FVG: ``low[i+1] > high[i-1]`` (gap up → support)
  * Bearish FVG: ``high[i+1] < low[i-1]`` (gap down → resistance)

Config params (via ``KernelConfig.kernel_params``):
  * ``gap_min_atr``    — minimum gap size in ATR (default 0.5)
    * ``fill_threshold`` — fraction of zone re-entered before the gap counts as filled (default 0.5)
  * ``max_age_bars``   — max bars back to search (default 200)
  * ``fvg_strength``   — base strength for FVG zones (default 0.75)
"""

from __future__ import annotations

from datetime import datetime
from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


@register_kernel("fair_value_gap")
class FairValueGapKernel(BaseSRKernel):
    """3-candle FVG detection as S/R candidates."""

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 20)))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        gap_min = params.get("gap_min_atr", 0.5) * atr
        fill_threshold = params.get("fill_threshold", 0.5)
        max_age = params.get("max_age_bars", 200)
        validity_lookback = params.get("validity_lookback_bars", 5)
        fvg_strength = params.get("fvg_strength", 0.75)
        max_cap = params.get("max_gap_atr_cap", 2.0)
        penalty = params.get("filled_penalty_multiplier", 0.5)

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        volumes = df["volume"].values
        timestamps = df.index

        last_bar = len(df) - 1
        start = max(1, last_bar - max_age)
        candidate_start = max(start + 1, validity_lookback)
        candidate_end = last_bar

        if candidate_start >= candidate_end:
            return []

        candidate_indices = np.arange(candidate_start, candidate_end)

        trailing_highs = np.lib.stride_tricks.sliding_window_view(
            highs,
            validity_lookback,
        ).max(axis=1)
        trailing_lows = np.lib.stride_tricks.sliding_window_view(
            lows,
            validity_lookback,
        ).min(axis=1)
        local_highs = trailing_highs[candidate_indices - validity_lookback]
        local_lows = trailing_lows[candidate_indices - validity_lookback]

        prev_highs = highs[candidate_indices - 1]
        prev_lows = lows[candidate_indices - 1]
        next_highs = highs[candidate_indices + 1]
        next_lows = lows[candidate_indices + 1]
        displacement_closes = closes[candidate_indices]
        displacement_volumes = volumes[candidate_indices]

        suffix_min = np.minimum.accumulate(lows[::-1])[::-1]
        suffix_max = np.maximum.accumulate(highs[::-1])[::-1]
        min_after = suffix_min[candidate_indices + 1]
        max_after = suffix_max[candidate_indices + 1]

        bullish_gap_sizes = next_lows - prev_highs
        bullish_thresholds = next_lows - bullish_gap_sizes * fill_threshold
        bullish_filled = min_after <= bullish_thresholds
        bullish_valid = (
            (next_lows > prev_highs)
            & (displacement_closes >= local_highs)
            & (bullish_gap_sizes >= gap_min)
        )

        bearish_gap_sizes = prev_lows - next_highs
        bearish_thresholds = next_highs + bearish_gap_sizes * fill_threshold
        bearish_filled = max_after >= bearish_thresholds
        bearish_valid = (
            (next_highs < prev_lows)
            & (displacement_closes <= local_lows)
            & (bearish_gap_sizes >= gap_min)
        )

        candidates: List[CandidateLevel] = []

        for pos, i in enumerate(candidate_indices):
            ts = timestamps[i]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()

            if bullish_valid[pos]:
                gap_size = float(bullish_gap_sizes[pos])
                lower = float(prev_highs[pos])
                upper = float(next_lows[pos])
                center = (lower + upper) / 2
                filled = bool(bullish_filled[pos])
                score = fvg_strength * min(gap_size / (atr * max_cap), 1.0)
                if filled:
                    score *= penalty

                candidates.append(CandidateLevel(
                    center_price=center,
                    lower_bound=lower,
                    upper_bound=upper,
                    level_type=LevelType.SUPPORT,
                    kernel_name="fair_value_gap",
                    timeframe=config.timeframe,
                    raw_score=min(1.0, score),
                    metadata={
                        "fvg_type": "bullish",
                        "gap_atr": gap_size / atr,
                        "filled": filled,
                        "displacement_index": int(i),
                        "displacement_volume": float(displacement_volumes[pos]),
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

            if bearish_valid[pos]:
                gap_size = float(bearish_gap_sizes[pos])
                lower = float(next_highs[pos])
                upper = float(prev_lows[pos])
                center = (lower + upper) / 2
                filled = bool(bearish_filled[pos])
                score = fvg_strength * min(gap_size / (atr * max_cap), 1.0)
                if filled:
                    score *= penalty

                candidates.append(CandidateLevel(
                    center_price=center,
                    lower_bound=lower,
                    upper_bound=upper,
                    level_type=LevelType.RESISTANCE,
                    kernel_name="fair_value_gap",
                    timeframe=config.timeframe,
                    raw_score=min(1.0, score),
                    metadata={
                        "fvg_type": "bearish",
                        "gap_atr": gap_size / atr,
                        "filled": filled,
                        "displacement_index": int(i),
                        "displacement_volume": float(displacement_volumes[pos]),
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

        return candidates
