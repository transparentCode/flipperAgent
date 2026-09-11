"""Tier 3 — Penetration Rate gate benchmark.

Measures mean penetration rate across trendlines in the forward window.
Acts as a multiplicative GATE: trials with high penetration are penalised.
"""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from libs.models.trendlines.contracts import Trendline


def compute(
    lines: List[Trendline],
    test_df: "pd.DataFrame",
    fit_window_bars: int,
    *,
    slope_tolerance: float = 0.25,
    consecutive_penetration_bars: int = 3,
    max_penetration_rate: float = 0.5,
    min_tolerance_atr_frac: float = 0.1,
) -> Dict[str, object]:
    """Compute mean penetration rate and gate pass status.

    Returns
    -------
    dict with keys: ``mean_pen_rate``, ``passed_gate``.
    """
    import pandas as pd
    from libs.models.trendlines.optimization.benchmarks._tolerance import compute_tolerance

    if not lines or test_df.empty:
        return {"mean_pen_rate": 1.0, "passed_gate": False}

    closes = test_df["close"].to_numpy(dtype=float)
    n_test = len(closes)
    test_x = np.arange(fit_window_bars, fit_window_bars + n_test, dtype=float)

    pen_rates: List[float] = []

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

        # Compute life span (same as longevity)
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

        life_bars = max(life, 1)
        pen_rates.append(float(np.sum(penetrated[:life_bars])) / life_bars)

    mean_pen = float(np.mean(pen_rates))
    return {
        "mean_pen_rate": mean_pen,
        "passed_gate": mean_pen < max_penetration_rate,
    }


def gate_penalty(
    pen_rate: float,
    threshold: float = 0.5,
    penalty_factor: float = 3.0,
    soft: bool = True,
) -> float:
    """Multiplicative gate penalty for penetration rate.

    Returns 1.0 if pen_rate <= threshold, else 1/penalty_factor (soft)
    or 0.0 (hard).
    """
    if pen_rate <= threshold:
        return 1.0
    return (1.0 / penalty_factor) if soft else 0.0
