"""
Round Number Kernel
===================
Psychological price levels as S/R candidates.

Round numbers (100, 1000, 10000 for decimals; pip intervals for FX)
act as natural psychological support/resistance. The interval is
derived from the live close price and ``AssetMetadata.round_number_mode``
so decimal- and pip-based spacing stay aligned with the current series.

Config params (via ``KernelConfig.kernel_params``):
    * ``atr_snap_factor`` — zone half-width as a fraction of ATR (default 0.5)
    * ``max_levels`` — maximum levels to return (default 20)
    * ``strength_decay`` — decay per level away from current price (default 0.05)
    * ``base_confidence`` — baseline weighting for psychological levels (default 0.5)
    * ``score_skip_threshold`` — skip weak levels below this score (default 0.05)

Rule-derived:
    * ``round_interval`` — static spacing hint for offline contexts; runtime recomputes from live price
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


def _round_interval(price: float, round_number_mode: str, pip_intervals: dict | None = None, pip_thresholds: dict | None = None) -> float:
    if price <= 0:
        return 1.0

    if round_number_mode == "pip":
        intervals = pip_intervals or {"micro": 0.01, "minor": 1.0, "major": 10.0}
        thresholds = pip_thresholds or {"micro_max": 2.0, "minor_max": 200.0}
        if price < thresholds.get("micro_max", 2.0):
            return intervals.get("micro", 0.01)
        if price < thresholds.get("minor_max", 200.0):
            return intervals.get("minor", 1.0)
        return intervals.get("major", 10.0)

    return 10 ** (math.floor(math.log10(price)) - 1)


@register_kernel("round_number")
class RoundNumberKernel(BaseSRKernel):
    """Psychological round-number levels as S/R candidates."""

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 14)))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        atr_snap = params.get("atr_snap_factor", 0.5)
        max_levels = params.get("max_levels", 20)
        strength_decay = params.get("strength_decay", 0.05)
        base_confidence = params.get("base_confidence", 0.5)
        score_skip_threshold = params.get("score_skip_threshold", 0.05)

        closes = df["close"].to_numpy(dtype=float, copy=False)
        pip_intervals = params.get("pip_intervals")
        pip_thresholds = params.get("pip_thresholds")

        if getattr(config, "_is_walk_forward_fold", False):
            candidate_start = int(params.get("start_index", 0))
            candidate_end = int(params.get("end_index", len(df)))
        else:
            candidate_end = len(df)
            candidate_start = candidate_end - 1 if candidate_end > 0 else 0

        candidates: List[CandidateLevel] = []
        candidate_indices = np.arange(candidate_start, candidate_end)
        for i in candidate_indices:
            current_price = closes[i]
            interval = _round_interval(current_price, config.metadata.round_number_mode, pip_intervals, pip_thresholds)
            if interval <= 0:
                continue

            timestamp = self._to_datetime(df.index[i], fallback_index=int(i))
            half_width = atr_snap * atr

            # Find the nearest round number below and above
            base = math.floor(current_price / interval) * interval
            
            idx_candidates: List[CandidateLevel] = []
            for offset in range(-max_levels // 2, max_levels // 2 + 1):
                level_price = base + offset * interval
                if level_price <= 0:
                    continue

                dist_atr = abs(level_price - current_price) / atr
                # Score decays with distance, starts from lower base confidence for psychological levels
                score = max(0.0, base_confidence - strength_decay * dist_atr)
                if score <= score_skip_threshold:
                    continue

                # Classify: above current price → resistance, below → support
                if level_price > current_price:
                    level_type = LevelType.RESISTANCE
                elif level_price < current_price:
                    level_type = LevelType.SUPPORT
                else:
                    level_type = LevelType.SUPPORT  # At price → treat as support

                idx_candidates.append(CandidateLevel(
                    center_price=level_price,
                    lower_bound=level_price - half_width,
                    upper_bound=level_price + half_width,
                    level_type=level_type,
                    kernel_name="round_number",
                    timeframe=config.timeframe,
                    raw_score=score,
                    metadata={
                        "interval": interval,
                        "distance_atr": dist_atr,
                        "level_tag": "psychological",
                    },
                    timestamp=timestamp,
                    atr_at_detection=atr,
                ))

            idx_candidates.sort(key=lambda c: abs(c.center_price - current_price))
            candidates.extend(idx_candidates[:max_levels])

        return candidates
