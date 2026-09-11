"""
Pivot High/Low Kernel
=====================
Stateless extraction of swing high/low pivot points as S/R candidates.

Core logic extracted from the original swing-detection implementation.
The kernel detects pivot highs (resistance) and pivot lows (support) via
rolling-window comparison, then emits one ``CandidateLevel`` per pivot.

**No clustering here** — clustering is handled downstream by the aggregation
stage.  This keeps the kernel stateless and composable.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


@register_kernel("pivot_hl")
class PivotHighLowKernel(BaseSRKernel):
    """
    Swing high/low detection kernel.

    For each bar *i*, checks whether:
      * ``high[i]`` is the maximum in ``[i - n1, i + n2]`` → resistance pivot
      * ``low[i]``  is the minimum in ``[i - n1, i + n2]`` → support pivot

        Candidates are emitted only once the right-hand confirmation window has
        elapsed, so ``CandidateLevel.timestamp`` is the timestamp of bar ``i + n2``.
        The original pivot bar remains available via ``metadata["pivot_index"]``.

    Config params (via ``KernelConfig.kernel_params``):
      * ``historical_depth`` — max bars to scan (default 500)
      * ``smoothing_period`` — EMA span for noise reduction (default 3, 0 to disable)

    Rule-derived params (via ``KernelConfig.rule_derived``):
      * ``n1`` — left lookback bars
      * ``n2`` — right lookback bars
    """

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        n1 = config.rule_derived.n1
        n2 = config.rule_derived.n2
        params = config.kernel_params
        depth = max(1, int(params.get("historical_depth", 500)))
        smoothing = max(0, int(params.get("smoothing_period", 3)))
        min_bars = max(1, int(params.get("min_bars", config.atr_period)), n1 + n2 + 1)

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        # Optional smoothing
        if smoothing > 0:
            high = _ema(df["high"], smoothing)
            low = _ema(df["low"], smoothing)
            # Guard against NaN from EMA on leading bars
            nan_mask = np.isnan(high) | np.isnan(low)
            if nan_mask.any():
                high = np.where(nan_mask, df["high"].to_numpy(dtype=float, copy=False), high)
                low = np.where(nan_mask, df["low"].to_numpy(dtype=float, copy=False), low)
        else:
            high = df["high"].to_numpy(dtype=float, copy=False)
            low = df["low"].to_numpy(dtype=float, copy=False)

        # Use original prices for candidate output
        raw_high = df["high"].to_numpy(dtype=float, copy=False)
        raw_low = df["low"].to_numpy(dtype=float, copy=False)
        volume = df["volume"].to_numpy(dtype=float, copy=False)
        timestamps = df.index

        last_bar = len(df) - 1
        candidate_start = max(n1, last_bar - depth + 1)
        candidate_end = last_bar - n2 + 1  # exclusive

        candidates: List[CandidateLevel] = []
        
        if candidate_start >= candidate_end:
            return candidates

        half_width = max(0.0, params.get("zone_half_width_atr", 0.1)) * atr  # point → zone width
        vol_weight = params.get("vol_factor_weight", 0.5)
        dom_weight = params.get("dominance_weight", 0.5)

        # Vectorized extrema detection via sliding_window_view
        slice_start = candidate_start - n1
        slice_end = candidate_end + n2
        window_size = n1 + n2 + 1
        
        high_slice = high[slice_start:slice_end]
        high_windows = np.lib.stride_tricks.sliding_window_view(high_slice, window_size)
        high_max = high_windows.max(axis=1)
        # Use argmax within each window to avoid float-equality fragility
        high_argmax = high_windows.argmax(axis=1)
        high_pivots = candidate_start + np.where(high_argmax == n1)[0]

        low_slice = low[slice_start:slice_end]
        low_windows = np.lib.stride_tricks.sliding_window_view(low_slice, window_size)
        low_min = low_windows.min(axis=1)
        # Use argmin within each window to avoid float-equality fragility
        low_argmin = low_windows.argmin(axis=1)
        low_pivots = candidate_start + np.where(low_argmin == n1)[0]

        # Process High Pivots (Resistance)
        for i in high_pivots:
            confirmation_index = i + n2
            confirmation_ts = self._to_datetime(
                timestamps[confirmation_index],
                fallback_index=confirmation_index,
            )
            price = float(raw_high[i])
            score = self._pivot_score(i, raw_high, volume, n1, n2, vol_weight, dom_weight)
            candidates.append(CandidateLevel(
                center_price=price,
                lower_bound=price - half_width,
                upper_bound=price + half_width,
                level_type=LevelType.RESISTANCE,
                kernel_name="pivot_hl",
                timeframe=config.timeframe,
                raw_score=score,
                metadata={
                    "pivot_index": int(i),
                    "confirmation_index": int(confirmation_index),
                    "pivot_volume": float(volume[i]),
                    "n1": n1,
                    "n2": n2,
                },
                timestamp=confirmation_ts,
                atr_at_detection=atr,
            ))

        # Process Low Pivots (Support)
        for i in low_pivots:
            confirmation_index = i + n2
            confirmation_ts = self._to_datetime(
                timestamps[confirmation_index],
                fallback_index=confirmation_index,
            )
            price = float(raw_low[i])
            score = self._pivot_score(i, raw_low, volume, n1, n2, vol_weight, dom_weight)
            candidates.append(CandidateLevel(
                center_price=price,
                lower_bound=price - half_width,
                upper_bound=price + half_width,
                level_type=LevelType.SUPPORT,
                kernel_name="pivot_hl",
                timeframe=config.timeframe,
                raw_score=score,
                metadata={
                    "pivot_index": int(i),
                    "confirmation_index": int(confirmation_index),
                    "pivot_volume": float(volume[i]),
                    "n1": n1,
                    "n2": n2,
                },
                timestamp=confirmation_ts,
                atr_at_detection=atr,
            ))

        # Preserve chronological ordering that tests expect (sort by pivot index then resistance-first)
        candidates.sort(key=lambda c: (c.metadata["pivot_index"], 0 if c.level_type == LevelType.RESISTANCE else 1))

        return candidates

    @staticmethod
    def _pivot_score(
        idx: int,
        prices: np.ndarray,
        volume: np.ndarray,
        n1: int,
        n2: int,
        vol_weight: float = 0.5,
        dom_weight: float = 0.5,
    ) -> float:
        """
        Simple quality score [0, 1] for a pivot point.

        Combines volume prominence and price dominance over the window.
        """
        window_start = max(0, idx - n1)
        window_end = min(len(prices), idx + n2 + 1)

        # Volume factor: pivot bar volume vs window mean
        window_vol = volume[window_start:window_end]
        mean_vol = float(window_vol.mean()) if len(window_vol) > 0 else 1.0
        vol_factor = min(1.0, float(volume[idx]) / mean_vol) if mean_vol > 0 else 0.5

        # Dominance: how far is the pivot from the window mean price?
        window_prices = prices[window_start:window_end]
        price_range = float(window_prices.max() - window_prices.min())
        if price_range > 0:
            dominance = abs(float(prices[idx]) - float(window_prices.mean())) / price_range
        else:
            dominance = 0.5

        return min(1.0, vol_weight * vol_factor + dom_weight * dominance)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ema(series: pd.Series, span: int) -> np.ndarray:
    """Vectorized EMA using pandas."""
    return series.ewm(span=span, adjust=False).mean().to_numpy(dtype=float, copy=False)



