"""
Liquidity Sweep Kernel
=======================
Detects liquidity sweeps (stop hunts) as S/R candidates.

A liquidity sweep occurs when price pierces a previous structural pivot
with a wick but fails to close beyond it, indicating a rejection and
a potential reversal zone.

Config params:
  * ``sweep_lookback`` — bars to look back for the pivot being swept (default 50)
  * ``max_pierce_atr`` — maximum allowed pierce distance in ATR (default 1.0)
    * ``max_age_bars``   — maximum bars back to scan for sweeps (default 200)
  * ``sweep_strength`` — base strength score (default 0.8)
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


@register_kernel("liquidity_sweep")
class LiquiditySweepKernel(BaseSRKernel):
    """Detects liquidity sweeps of recent pivots."""

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

        sweep_lookback = max(1, int(params.get("sweep_lookback", 50)))
        max_pierce_atr = params.get("max_pierce_atr", 1.0)
        max_age_bars = max(1, int(params.get("max_age_bars", 200)))
        sweep_strength = params.get("sweep_strength", 0.8)
        half_w = params.get("zone_half_width_atr", 0.1) * atr
        
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        timestamps = df.index
        
        last_bar = len(df) - 1
        start = max(1, last_bar - max_age_bars)
        candidate_indices = np.arange(start, last_bar + 1)
        local_highs = (
            pd.Series(highs)
            .rolling(window=sweep_lookback, min_periods=1)
            .max()
            .shift(1)
            .to_numpy(dtype=float, copy=False)
        )
        local_lows = (
            pd.Series(lows)
            .rolling(window=sweep_lookback, min_periods=1)
            .min()
            .shift(1)
            .to_numpy(dtype=float, copy=False)
        )

        candidate_highs = highs[candidate_indices]
        candidate_lows = lows[candidate_indices]
        candidate_closes = closes[candidate_indices]
        candidate_local_highs = local_highs[candidate_indices]
        candidate_local_lows = local_lows[candidate_indices]
        max_pierce = max_pierce_atr * atr

        bearish_pierce = candidate_highs - candidate_local_highs
        bullish_pierce = candidate_local_lows - candidate_lows
        bearish_valid = (
            (candidate_highs > candidate_local_highs)
            & (candidate_closes <= candidate_local_highs)
            & (bearish_pierce <= max_pierce)
        )
        bullish_valid = (
            (candidate_lows < candidate_local_lows)
            & (candidate_closes >= candidate_local_lows)
            & (bullish_pierce <= max_pierce)
        )

        if max_pierce > 0:
            bearish_scores = np.clip(sweep_strength * (1.0 - bearish_pierce / max_pierce), 0.0, 1.0)
            bullish_scores = np.clip(sweep_strength * (1.0 - bullish_pierce / max_pierce), 0.0, 1.0)
        else:
            bearish_scores = np.zeros_like(bearish_pierce, dtype=float)
            bullish_scores = np.zeros_like(bullish_pierce, dtype=float)
        
        candidates: List[CandidateLevel] = []
        
        for pos, i in enumerate(candidate_indices):
            ts = self._to_datetime(timestamps[i], fallback_index=int(i))

            if bearish_valid[pos]:
                local_max = float(candidate_local_highs[pos])
                pierce_dist = float(bearish_pierce[pos])
                candidates.append(CandidateLevel(
                    center_price=local_max,
                    lower_bound=local_max - half_w,
                    upper_bound=min(float(candidate_highs[pos]), local_max + half_w),
                    level_type=LevelType.RESISTANCE,
                    kernel_name="liquidity_sweep",
                    timeframe=config.timeframe,
                    raw_score=float(bearish_scores[pos]),
                    metadata={
                        "sweep_type": "bearish",
                        "pierce_atr": pierce_dist / atr,
                        "score_modulation": "pierce_depth",
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

            if bullish_valid[pos]:
                local_min = float(candidate_local_lows[pos])
                pierce_dist = float(bullish_pierce[pos])
                candidates.append(CandidateLevel(
                    center_price=local_min,
                    lower_bound=max(float(candidate_lows[pos]), local_min - half_w),
                    upper_bound=local_min + half_w,
                    level_type=LevelType.SUPPORT,
                    kernel_name="liquidity_sweep",
                    timeframe=config.timeframe,
                    raw_score=float(bullish_scores[pos]),
                    metadata={
                        "sweep_type": "bullish",
                        "pierce_atr": pierce_dist / atr,
                        "score_modulation": "pierce_depth",
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

        return candidates
