"""
Order Block Kernel
===================
Detects order blocks — zones of institutional activity characterized
by a strong displacement candle preceded by consolidation or
an opposing move.

An order block is the last opposing candle before a displacement move:
  * Bullish OB: last bearish candle before a strong up-move (→ support)
  * Bearish OB: last bullish candle before a strong down-move (→ resistance)

Config params (via ``KernelConfig.kernel_params``):
  * ``displacement_atr`` — minimum displacement size in ATR (default 1.5)
  * ``imbalance_ratio``  — minimum body/range ratio for displacement (default 0.7)
  * ``max_age_bars``     — max bars back to search (default 200)
  * ``ob_strength``      — base strength score for detected OBs (default 0.8)
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


@register_kernel("order_block")
class OrderBlockKernel(BaseSRKernel):
    """Institutional order block detection as S/R candidates."""

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

        displacement_threshold = params.get("displacement_atr", 1.5) * atr
        imbalance_ratio = params.get("imbalance_ratio", 0.7)
        max_age = params.get("max_age_bars", 200)
        validity_lookback = params.get("validity_lookback_bars", 5)
        ob_strength = params.get("ob_strength", 0.8)
        displacement_score_cap_atr = params.get("displacement_score_cap_atr", 2.0)

        opens = df["open"].values
        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        volumes = df["volume"].values
        timestamps = df.index

        last_bar = len(df) - 1
        start = max(1, last_bar - max_age)
        candidate_start = max(start, validity_lookback)
        candidate_end = last_bar + 1

        if candidate_start >= candidate_end:
            return []

        candidate_indices = np.arange(candidate_start, candidate_end)
        moves = closes - opens
        bar_ranges = highs - lows
        body_ratios = np.divide(
            np.abs(moves),
            bar_ranges,
            out=np.zeros_like(moves, dtype=float),
            where=bar_ranges > 0,
        )
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

        candidate_moves = moves[candidate_indices]
        candidate_body_ratios = body_ratios[candidate_indices]
        displacement_valid = (
            (bar_ranges[candidate_indices] > 0)
            & (np.abs(candidate_moves) >= displacement_threshold)
            & (candidate_body_ratios >= imbalance_ratio)
        )

        # Pre-calculate nearest opposing candles
        is_bullish = moves > 0
        is_bearish = moves < 0
        
        last_bearish = np.zeros(len(moves), dtype=int) - 1
        last_corr = -1
        for idx in range(len(moves)):
            last_bearish[idx] = last_corr
            if is_bearish[idx]:
                last_corr = idx
                
        last_bullish = np.zeros(len(moves), dtype=int) - 1
        last_corr = -1
        for idx in range(len(moves)):
            last_bullish[idx] = last_corr
            if is_bullish[idx]:
                last_corr = idx

        candidates: List[CandidateLevel] = []

        for pos, i in enumerate(candidate_indices):
            if not displacement_valid[pos]:
                continue

            move = float(candidate_moves[pos])
            body_ratio = float(candidate_body_ratios[pos])
            
            if move > 0:
                ob_idx = last_bearish[i]
            else:
                ob_idx = last_bullish[i]
                
            if ob_idx == -1:
                continue
                
            ob_open = float(opens[ob_idx])
            ob_close = float(closes[ob_idx])
            ob_high = float(highs[ob_idx])
            ob_low = float(lows[ob_idx])

            # Skip doji OBs — zero-width zones are invalid
            if ob_high == ob_low:
                continue

            # Displacement factor: reward stronger displacements
            displacement_factor = min(1.0, abs(move) / (displacement_threshold * displacement_score_cap_atr))

            ts = timestamps[ob_idx]
            if not isinstance(ts, datetime):
                ts = ts.to_pydatetime()

            if move > 0 and closes[i] >= local_highs[pos]:
                # Bullish displacement, bearish OB candle → support
                candidates.append(CandidateLevel(
                    center_price=(ob_high + ob_low) / 2,
                    lower_bound=ob_low,
                    upper_bound=ob_high,
                    level_type=LevelType.SUPPORT,
                    kernel_name="order_block",
                    timeframe=config.timeframe,
                    raw_score=ob_strength * body_ratio * displacement_factor,
                    metadata={
                        "ob_type": "bullish",
                        "ob_index": ob_idx,
                        "displacement_atr": abs(move) / atr,
                        "ob_volume": float(volumes[ob_idx]),
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))
            elif move < 0 and closes[i] <= local_lows[pos]:
                # Bearish displacement, bullish OB candle → resistance
                candidates.append(CandidateLevel(
                    center_price=(ob_high + ob_low) / 2,
                    lower_bound=ob_low,
                    upper_bound=ob_high,
                    level_type=LevelType.RESISTANCE,
                    kernel_name="order_block",
                    timeframe=config.timeframe,
                    raw_score=ob_strength * body_ratio * displacement_factor,
                    metadata={
                        "ob_type": "bearish",
                        "ob_index": ob_idx,
                        "displacement_atr": abs(move) / atr,
                        "ob_volume": float(volumes[ob_idx]),
                    },
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

        return candidates
