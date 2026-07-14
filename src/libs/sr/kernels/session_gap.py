"""
Session Gap Kernel
===================
Detects overnight / weekend gaps for non-continuous markets and
produces S/R candidates at gap boundaries and fill levels.

Assumes upstream preprocessing has already adjusted corporate-action
effects and filtered or normalized intraday non-session price jumps
before bars reach any downstream module.

**No-op when ``config.metadata.has_session_gaps`` is ``False``**
(crypto, most FX).  This is entirely config-driven — no asset-class
string matching in code.

Gap detection: ``|open[i] - close[i-1]| > gap_min_atr × ATR``
across a real timestamp session boundary.

For each gap, produces candidates at:
  * Previous session close (gap origin)
  * Current session open (gap destination)
  * Fill levels at configured fractions (default: 50%)

Zone bounds: ``[min(close, open), max(close, open)]``

Config params (via ``KernelConfig.kernel_params``):
  * ``gap_min_atr``          — minimum gap size in ATR (default 0.5)
  * ``fill_level_fractions`` — list of fill percentages (default [0.5])
  * ``max_age_bars``         — max bars back to scan (default 500)
  * ``gap_origin_strength``  — strength for gap-origin levels (default 0.7)
  * ``gap_dest_strength``    — strength for gap-destination levels (default 0.7)
  * ``fill_level_strength``  — strength for fill levels (default 0.6)
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


def _session_boundary_mask(
    timestamps: pd.Index,
    multiplier: float = 1.5,
    baseline_bars: int = 20,
) -> np.ndarray:
    if len(timestamps) <= 1:
        return np.zeros(len(timestamps), dtype=bool)

    normalized = pd.to_datetime(
        [
            BaseSRKernel._to_datetime(value, fallback_index=index)
            for index, value in enumerate(timestamps)
        ],
        utc=True,
    )
    delta_seconds = np.empty(len(normalized), dtype=float)
    delta_seconds[0] = np.nan
    delta_seconds[1:] = np.diff(normalized.asi8) / 1_000_000_000.0

    baseline_seconds = (
        pd.Series(np.where(delta_seconds > 0, delta_seconds, np.nan))
        .rolling(window=baseline_bars + 1, min_periods=1)
        .median()
        .to_numpy(dtype=float, copy=False)
    )

    return (
        np.isfinite(delta_seconds)
        & (delta_seconds > 0)
        & np.isfinite(baseline_seconds)
        & (baseline_seconds > 0)
        & (delta_seconds > baseline_seconds * multiplier)
    )


def _is_session_boundary(timestamps: pd.Index, index: int, multiplier: float = 1.5, baseline_bars: int = 20) -> bool:
    if index <= 0 or index >= len(timestamps):
        return False

    return bool(
        _session_boundary_mask(
            timestamps,
            multiplier=multiplier,
            baseline_bars=baseline_bars,
        )[index]
    )


@register_kernel("session_gap")
class SessionGapKernel(BaseSRKernel):
    """
    Session gap detection kernel.

    No-op for continuous markets (``metadata.has_session_gaps == False``).
    """

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        # No-op for continuous markets
        if not config.metadata.has_session_gaps:
            return []

        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 20)))

        if len(df) < min_bars:
            return []

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        gap_min = params.get("gap_min_atr", 0.5) * atr
        fill_fractions = params.get("fill_level_fractions", [0.5])
        max_age = params.get("max_age_bars", 500)
        origin_strength = params.get("gap_origin_strength", 0.7)
        dest_strength = params.get("gap_dest_strength", 0.7)
        fill_strength = params.get("fill_level_strength", 0.6)
        max_cap = params.get("max_gap_atr_cap", 2.0)
        boundary_multiplier = params.get("session_boundary_multiplier", 1.5)
        boundary_baseline_bars = params.get("session_boundary_baseline_bars", 20)

        opens = df["open"].values
        closes = df["close"].values
        timestamps = df.index

        last_bar = len(df) - 1
        start = max(1, last_bar - max_age)

        boundary_mask = _session_boundary_mask(
            timestamps,
            multiplier=boundary_multiplier,
            baseline_bars=boundary_baseline_bars,
        )
        candidate_indices = np.arange(start, last_bar + 1)
        prev_closes = closes[candidate_indices - 1]
        curr_opens = opens[candidate_indices]
        gap_sizes = np.abs(curr_opens - prev_closes)
        valid_positions = np.where(
            boundary_mask[candidate_indices] & (gap_sizes >= gap_min)
        )[0]

        candidates: List[CandidateLevel] = []

        for pos in valid_positions:
            i = int(candidate_indices[pos])
            prev_close = float(prev_closes[pos])
            curr_open = float(curr_opens[pos])
            gap_size = float(gap_sizes[pos])

            gap_lower = min(prev_close, curr_open)
            gap_upper = max(prev_close, curr_open)
            gap_atr = gap_size / atr

            ts = BaseSRKernel._to_datetime(timestamps[i], fallback_index=i)

            # Gap direction
            gap_up = curr_open > prev_close
            gap_meta = {
                "gap_direction": "up" if gap_up else "down",
                "gap_atr": gap_atr,
                "gap_index": i,
            }

            # 1. Gap origin (previous close)
            candidates.append(CandidateLevel(
                center_price=prev_close,
                lower_bound=gap_lower,
                upper_bound=gap_upper,
                level_type=LevelType.SUPPORT if gap_up else LevelType.RESISTANCE,
                kernel_name="session_gap",
                timeframe=config.timeframe,
                raw_score=min(1.0, origin_strength * min(gap_atr, max_cap)),
                metadata={**gap_meta, "gap_role": "origin"},
                timestamp=ts,
                atr_at_detection=atr,
            ))

            # 2. Gap destination (current open)
            candidates.append(CandidateLevel(
                center_price=curr_open,
                lower_bound=gap_lower,
                upper_bound=gap_upper,
                level_type=LevelType.RESISTANCE if gap_up else LevelType.SUPPORT,
                kernel_name="session_gap",
                timeframe=config.timeframe,
                raw_score=min(1.0, dest_strength * min(gap_atr, max_cap)),
                metadata={**gap_meta, "gap_role": "destination"},
                timestamp=ts,
                atr_at_detection=atr,
            ))

            # 3. Fill levels
            for frac in fill_fractions:
                fill_price = gap_lower + (gap_upper - gap_lower) * frac
                candidates.append(CandidateLevel(
                    center_price=fill_price,
                    lower_bound=gap_lower,
                    upper_bound=gap_upper,
                    level_type=LevelType.SUPPORT if gap_up else LevelType.RESISTANCE,
                    kernel_name="session_gap",
                    timeframe=config.timeframe,
                    raw_score=min(1.0, fill_strength * min(gap_atr, max_cap)),
                    metadata={**gap_meta, "gap_role": f"fill_{frac:.0%}"},
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

        return candidates
