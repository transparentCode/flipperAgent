"""Shared penetration tolerance computation for benchmarks.

The tolerance defines the band around a projected trendline within which
price is considered 'on the line' (not penetrating).

Prior to this helper, tolerance was purely slope-relative:
    tolerance = |slope| × slope_tolerance

This fails for flat/gentle trendlines on volatile assets where even normal
price noise exceeds the slope-derived tolerance, causing spuriously high
penetration rates and low longevity.

The fixed formula adds an ATR-based floor:
    tolerance = max(|slope| × slope_tolerance, ATR × min_tolerance_atr_frac)

This ensures horizontal S/R lines have a meaningful tolerance band
proportional to the asset's volatility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_tolerance(
    slope: float,
    test_df: pd.DataFrame,
    *,
    slope_tolerance: float = 0.25,
    min_tolerance_atr_frac: float = 0.1,
    atr_period: int = 14,
) -> float:
    """Compute penetration tolerance with ATR-based floor.

    Parameters
    ----------
    slope : Trendline slope (price/bar).
    test_df : Forward test DataFrame with OHLC columns.
    slope_tolerance : Multiplier for slope-based tolerance.
    min_tolerance_atr_frac : Fraction of ATR used as minimum floor.
    atr_period : ATR lookback period.

    Returns
    -------
    Tolerance value in price units.
    """
    slope_tol = abs(slope) * slope_tolerance
    atr_tol = _estimate_atr(test_df, atr_period) * min_tolerance_atr_frac
    return max(slope_tol, atr_tol, 1e-9)


def _estimate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Estimate ATR from test DataFrame."""
    if df.empty:
        return 1e-9
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)

    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        ),
    )
    if len(tr) == 0:
        return float(np.mean(high - low)) if len(high) > 0 else 1e-9

    # Simple moving average ATR
    if len(tr) >= period:
        atr = float(np.mean(tr[-period:]))
    else:
        atr = float(np.mean(tr))
    return max(atr, 1e-9)
