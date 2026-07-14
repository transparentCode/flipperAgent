"""
Fractal Channel Kernel
=======================
Extracts S/R candidates from fractal channel boundaries.

Uses ``app.indicators.fractal_channel.FractalChannel`` to compute
upper and lower channel lines, then emits candidates at the
channel boundaries.

The channel upper boundary → resistance, lower → support.
Additional candidates at the channel midpoint are optionally emitted.

Config params (via ``KernelConfig.kernel_params``):
    * ``channel_lookback`` — bars for channel computation (default 32)
    * ``boundary_buffer_atr`` — buffer added to channel bounds as ATR fraction (default 0.1)
    * ``use_rule_derived_buffer`` — use ``rule_derived.fractal_buffer`` instead of ``boundary_buffer_atr`` (default False)
  * ``pivot_method``     — 'fractal' or 'zigzag' (default 'fractal')
  * ``mode``             — 'geometric' or 'dynamic' (default 'geometric')
  * ``emit_midline``     — emit midpoint candidate (default False)
  * ``channel_strength`` — base strength for channel levels (default 0.85)

Rule-derived params (via ``KernelConfig.rule_derived``):
  * ``fractal_period`` — used as ``2 × n1`` for channel period
    * ``fractal_buffer`` — auto-used as zone buffer when ``use_rule_derived_buffer`` is enabled
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


@register_kernel("fractal_channel")
class FractalChannelKernel(BaseSRKernel):
    """Fractal channel boundaries as S/R candidates."""

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 30)))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        channel_period = config.rule_derived.fractal_period
        use_rule_derived_buffer = bool(params.get("use_rule_derived_buffer", False))
        explicit_buffer = params.get("boundary_buffer_atr", 0.1) * atr
        derived_buffer = float(getattr(config.rule_derived, "fractal_buffer", 0.0) or 0.0)
        buffer = derived_buffer if use_rule_derived_buffer and derived_buffer > 0 else explicit_buffer
        pivot_method = params.get("pivot_method", "fractal")
        mode = params.get("mode", "geometric")
        emit_midline = params.get("emit_midline", False)
        strength = params.get("channel_strength", 0.85)
        midline_strength_factor = params.get("midline_strength_factor", 0.6)

        # Use lookback from params or rule-derived
        lookback = params.get("channel_lookback", channel_period * 2)
        lookback = min(lookback, len(df))

        # Compute channel using fractal indicator
        from app.indicators.fractal_channel import FractalChannel

        fc = FractalChannel(
            name="fc_kernel",
            pivot_method=pivot_method,
            pivot_window=max(2, channel_period // 2),
            lookback=lookback,
            mode=mode,
        )

        result = fc.calculate(df)

        if result is None:
            return []

        # Extract channel boundaries from result
        upper_col, lower_col = _extract_channel_bounds(result, lookback, mode)

        if hasattr(upper_col, "values"):
            upper_arr = upper_col.values
        elif upper_col is not None:
            upper_arr = np.asarray(upper_col)
        else:
            upper_arr = None

        if hasattr(lower_col, "values"):
            lower_arr = lower_col.values
        elif lower_col is not None:
            lower_arr = np.asarray(lower_col)
        else:
            lower_arr = None

        candidates: List[CandidateLevel] = []
        
        if getattr(config, "_is_walk_forward_fold", False):
            candidate_start = int(params.get("start_index", 0))
            candidate_end = int(params.get("end_index", len(df)))
        else:
            candidate_end = len(df)
            candidate_start = candidate_end - 1 if candidate_end > 0 else 0

        # Loop over candidate_indices
        candidate_indices = np.arange(candidate_start, candidate_end)
        for i in candidate_indices:
            timestamp = df.index[i]
            if not isinstance(timestamp, datetime):
                timestamp = timestamp.to_pydatetime()

            if upper_arr is not None:
                upper_val = upper_arr[i]
                if np.isfinite(upper_val):
                    candidates.append(CandidateLevel(
                        center_price=float(upper_val),
                        lower_bound=float(upper_val - buffer),
                        upper_bound=float(upper_val + buffer),
                        level_type=LevelType.RESISTANCE,
                        kernel_name="fractal_channel",
                        timeframe=config.timeframe,
                        raw_score=strength,
                        metadata={
                            "channel_role": "upper",
                            "channel_period": channel_period,
                            "mode": mode,
                        },
                        timestamp=timestamp,
                        atr_at_detection=atr,
                    ))

            if lower_arr is not None:
                lower_val = lower_arr[i]
                if np.isfinite(lower_val):
                    candidates.append(CandidateLevel(
                        center_price=float(lower_val),
                        lower_bound=float(lower_val - buffer),
                        upper_bound=float(lower_val + buffer),
                        level_type=LevelType.SUPPORT,
                        kernel_name="fractal_channel",
                        timeframe=config.timeframe,
                        raw_score=strength,
                        metadata={
                            "channel_role": "lower",
                            "channel_period": channel_period,
                            "mode": mode,
                        },
                        timestamp=timestamp,
                        atr_at_detection=atr,
                    ))

            # Midline
            if emit_midline and upper_arr is not None and lower_arr is not None:
                uv = upper_arr[i]
                lv = lower_arr[i]
                if np.isfinite(uv) and np.isfinite(lv):
                    mid = (uv + lv) / 2.0
                    candidates.append(CandidateLevel(
                        center_price=float(mid),
                        lower_bound=float(mid - buffer),
                        upper_bound=float(mid + buffer),
                        level_type=LevelType.SUPPORT,
                        kernel_name="fractal_channel",
                        timeframe=config.timeframe,
                        raw_score=strength * midline_strength_factor,
                        metadata={
                            "channel_role": "midline",
                            "channel_period": channel_period,
                            "mode": mode,
                        },
                        timestamp=timestamp,
                        atr_at_detection=atr,
                    ))

        return candidates


def _extract_channel_bounds(result, lookback: int, mode: str) -> tuple[object | None, object | None]:
    """Resolve the exact upper/lower channel outputs for the active indicator config."""
    if isinstance(result, dict):
        return result.get("upper"), result.get("lower")

    if isinstance(result, pd.DataFrame):
        upper_col = f"fc_upper_{lookback}_{mode}"
        lower_col = f"fc_lower_{lookback}_{mode}"
        upper = result[upper_col].values if upper_col in result.columns else None
        lower = result[lower_col].values if lower_col in result.columns else None
        return upper, lower

    return None, None
