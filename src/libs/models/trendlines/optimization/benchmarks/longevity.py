"""Tier 1 — Longevity benchmark.

Measures mean trendline survival ratio in the forward test window.
A longevity of 1.0 means all lines survived the entire test period
without consecutive penetration breach.
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
    consecutive_penetration_bars: int = 3,
    min_tolerance_atr_frac: float = 0.1,
) -> Dict[str, float]:
    """Compute mean longevity across all trendlines.

    Returns
    -------
    dict with keys: ``mean_longevity``, ``n_lines``.
    """
    import pandas as pd
    from app.trendlines.optimization.benchmarks._tolerance import compute_tolerance

    if not lines or test_df.empty:
        return {"mean_longevity": 0.0, "n_lines": 0}

    closes = test_df["close"].to_numpy(dtype=float)
    n_test = len(closes)
    test_x = np.arange(fit_window_bars, fit_window_bars + n_test, dtype=float)

    longevities: List[float] = []

    for line in lines:
        projected = line.slope * test_x + line.intercept
        tolerance = compute_tolerance(
            line.slope, test_df,
            slope_tolerance=slope_tolerance,
            min_tolerance_atr_frac=min_tolerance_atr_frac,
        )

        if line.is_support:
            penetrated = closes < (projected - tolerance)
        else:
            penetrated = closes > (projected + tolerance)

        life = n_test
        consecutive = 0
        for idx in range(n_test):
            if penetrated[idx]:
                consecutive += 1
                if consecutive >= consecutive_penetration_bars:
                    life = idx - (consecutive_penetration_bars - 1)
                    break
            else:
                consecutive = 0
        longevities.append(max(life / n_test, 0.0))

    return {
        "mean_longevity": float(np.mean(longevities)),
        "n_lines": len(lines),
    }
