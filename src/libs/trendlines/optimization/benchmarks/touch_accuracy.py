"""Tier 2 — Touch Accuracy benchmark.

Measures how accurately trendline touches predict short-term price reaction
in the forward test window.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from app.trendlines.contracts import Trendline


def compute(
    lines: List[Trendline],
    test_df: "pd.DataFrame",
    fit_window_bars: int,
    *,
    slope_tolerance: float = 0.25,
    forward_lookahead_bars: int = 3,
    min_tolerance_atr_frac: float = 0.1,
) -> Dict[str, float]:
    """Compute touch-reaction accuracy across all trendlines.

    Returns
    -------
    dict with keys: ``touch_accuracy``, ``total_touches``, ``total_hits``.
    """
    import pandas as pd

    if not lines or test_df.empty:
        return {"touch_accuracy": 0.0, "total_touches": 0, "total_hits": 0}

    from app.trendlines.optimization.benchmarks._tolerance import compute_tolerance

    closes = test_df["close"].to_numpy(dtype=float)
    highs = test_df["high"].to_numpy(dtype=float)
    lows = test_df["low"].to_numpy(dtype=float)
    n_test = len(closes)
    test_x = np.arange(fit_window_bars, fit_window_bars + n_test, dtype=float)

    total_touches = 0
    total_hits = 0

    for line in lines:
        projected = line.slope * test_x + line.intercept
        tolerance = compute_tolerance(
            line.slope, test_df,
            slope_tolerance=slope_tolerance,
            min_tolerance_atr_frac=min_tolerance_atr_frac,
        )

        if line.is_support:
            near = np.abs(lows - projected) < tolerance
        else:
            near = np.abs(highs - projected) < tolerance

        touch_indices = np.where(near)[0]
        for ti in touch_indices:
            if ti + forward_lookahead_bars >= n_test:
                continue
            total_touches += 1
            if line.is_support:
                if np.any(closes[ti + 1: ti + 1 + forward_lookahead_bars] > closes[ti]):
                    total_hits += 1
            else:
                if np.any(closes[ti + 1: ti + 1 + forward_lookahead_bars] < closes[ti]):
                    total_hits += 1

    acc = total_hits / max(total_touches, 1)
    return {
        "touch_accuracy": float(acc),
        "total_touches": total_touches,
        "total_hits": total_hits,
    }
