"""
Data-Driven Search-Space Bounds
================================
Compute per-asset, data-informed bounds for the 6 derivable kernel params
by analyzing the OHLCV price series.  The optimizer still searches, but
within a *much* tighter window seeded from empirical distributions.

The 6 derivable params and their data sources:

  gap_min_atr          ← distribution of 3-bar gap sizes / ATR
  displacement_atr     ← distribution of |body| / ATR
  max_pierce_atr       ← distribution of wick penetration / ATR
  sweep_lookback       ← structural pivot spacing (autocorrelation lag)
  imbalance_ratio      ← distribution of body / range ratios
  band_width_sigma     ← residual distribution σ from rolling regression

The remaining 4 params (hvn_prominence, fill_threshold,
filled_penalty_multiplier, pipeline gates) keep their static defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _canonical_bounds() -> Dict[str, Tuple[float, float]]:
    """Load canonical (low, high) from the search space definition.

    This ensures data-driven clamping always matches the optimizer's
    approved parameter ranges — no duplicated magic numbers.
    """
    from app.sr.optimization._shared import default_parameter_space
    return {name: (spec.low, spec.high) for name, spec in default_parameter_space().items()}


# Map from dotted param name → key in _canonical_bounds()
_PARAM_KEYS = {
    "gap_min_atr": "kernels.fair_value_gap.gap_min_atr",
    "displacement_atr": "kernels.order_block.displacement_atr",
    "max_pierce_atr": "kernels.liquidity_sweep.max_pierce_atr",
    "sweep_lookback": "kernels.liquidity_sweep.sweep_lookback",
    "imbalance_ratio": "kernels.order_block.imbalance_ratio",
    "band_width_sigma": "kernels.regression_band.band_width_sigma",
    "merge_threshold": "pipeline.merge_threshold_pct_atr",
}


@dataclass(frozen=True)
class DerivedBound:
    """A single data-derived (low, high) bound with the derivation source."""

    low: float
    high: float
    source: str  # human-readable description

    def as_tuple(self) -> Tuple[float, float]:
        return (self.low, self.high)


def compute_data_driven_bounds(
    df: pd.DataFrame,
    atr_period: int = 14,
    warmup_bars: int = 200,
) -> Dict[str, DerivedBound]:
    """
    Analyse *df* and return tightened bounds for derivable kernel params.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with columns ``open, high, low, close, volume``.
    atr_period : int
        ATR lookback for normalisation.
    warmup_bars : int
        Skip first N bars (ATR needs warmup).

    Returns
    -------
    dict mapping dotted param name → DerivedBound.
    Only returns entries for params where the data is sufficient.
    """
    if len(df) < warmup_bars + 50:
        logger.warning(
            "Insufficient data for data-driven bounds (%d bars, need %d+50). "
            "Returning empty.",
            len(df),
            warmup_bars,
        )
        return {}

    atr = _compute_atr(df, atr_period)
    usable = df.iloc[warmup_bars:].copy()
    atr_usable = atr.iloc[warmup_bars:]

    bounds: Dict[str, DerivedBound] = {}

    # 1. gap_min_atr — 3-bar gap sizes normalised by ATR
    gap_bound = _derive_gap_min_atr(usable, atr_usable)
    if gap_bound is not None:
        bounds["kernels.fair_value_gap.gap_min_atr"] = gap_bound

    # 2. displacement_atr — |body| / ATR distribution
    disp_bound = _derive_displacement_atr(usable, atr_usable)
    if disp_bound is not None:
        bounds["kernels.order_block.displacement_atr"] = disp_bound

    # 3. max_pierce_atr — wick penetrations / ATR
    pierce_bound = _derive_max_pierce_atr(usable, atr_usable)
    if pierce_bound is not None:
        bounds["kernels.liquidity_sweep.max_pierce_atr"] = pierce_bound

    # 4. sweep_lookback — structural pivot spacing
    sweep_bound = _derive_sweep_lookback(usable)
    if sweep_bound is not None:
        bounds["kernels.liquidity_sweep.sweep_lookback"] = sweep_bound

    # 5. imbalance_ratio — body / range distribution
    # 6. merge_threshold — wick size distribution
    merge_bound = _derive_merge_threshold_pct_atr(usable, atr_usable)
    if merge_bound is not None:
        bounds["pipeline.merge_threshold_pct_atr"] = merge_bound

    imb_bound = _derive_imbalance_ratio(usable)
    if imb_bound is not None:
        bounds["kernels.order_block.imbalance_ratio"] = imb_bound

    # 6. band_width_sigma — regression residual spread
    bw_bound = _derive_band_width_sigma(usable)
    if bw_bound is not None:
        bounds["kernels.regression_band.band_width_sigma"] = bw_bound

    return bounds


# ---------------------------------------------------------------------------
# ATR helper
# ---------------------------------------------------------------------------


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder-style ATR."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Per-param derivations
# ---------------------------------------------------------------------------


def _derive_gap_min_atr(
    df: pd.DataFrame, atr: pd.Series
) -> Optional[DerivedBound]:
    """
    FVG gap_min_atr: measure 3-bar gap sizes (high[i-2] vs low[i]) / ATR.
    We want the optimizer to search around the empirical gap distribution.
    """
    canon = _canonical_bounds()[_PARAM_KEYS["gap_min_atr"]]
    # Bearish FVG: low[i] > high[i-2]  (gap down is symmetric)
    gap_up = (df["low"].values[2:] - df["high"].values[:-2])
    gap_down = (df["low"].values[:-2] - df["high"].values[2:])
    atr_vals = atr.values[2:]

    # Combine absolute gap sizes, filter non-gaps
    all_gaps = np.concatenate([gap_up, gap_down])
    all_atr = np.concatenate([atr_vals, atr_vals])
    mask = all_gaps > 0
    if mask.sum() < 20:
        return None

    gap_ratios = all_gaps[mask] / all_atr[mask]
    p20, p80 = float(np.percentile(gap_ratios, 20)), float(np.percentile(gap_ratios, 80))

    # Clamp to canonical bounds
    low = max(canon[0], round(p20, 4))
    high = min(canon[1], round(p80, 4))
    if low >= high:
        return None

    return DerivedBound(low, high, f"gap_ratios p20={p20:.3f} p80={p80:.3f}")


def _derive_displacement_atr(
    df: pd.DataFrame, atr: pd.Series
) -> Optional[DerivedBound]:
    """
    OB displacement_atr: |body| / ATR.
    Large-body candles are displacement candidates.
    Focus on the upper tail (>= 75th percentile) since OBs require strong moves.
    """
    canon = _canonical_bounds()[_PARAM_KEYS["displacement_atr"]]
    body = (df["close"].values - df["open"].values)
    abs_body = np.abs(body)
    atr_vals = atr.values

    mask = atr_vals > 0
    if mask.sum() < 50:
        return None

    body_ratios = abs_body[mask] / atr_vals[mask]
    # OB displacement is about large moves → upper tail
    p75, p95 = float(np.percentile(body_ratios, 75)), float(np.percentile(body_ratios, 95))

    low = max(canon[0], round(p75, 4))
    high = min(canon[1], round(p95, 4))
    if low >= high:
        return None

    return DerivedBound(low, high, f"body_atr p75={p75:.3f} p95={p95:.3f}")


def _derive_max_pierce_atr(
    df: pd.DataFrame, atr: pd.Series
) -> Optional[DerivedBound]:
    """
    Liquidity sweep max_pierce_atr: how far wicks extend beyond body / ATR.
    """
    canon = _canonical_bounds()[_PARAM_KEYS["max_pierce_atr"]]
    high = df["high"].values
    low = df["low"].values
    body_high = np.maximum(df["open"].values, df["close"].values)
    body_low = np.minimum(df["open"].values, df["close"].values)

    upper_wick = high - body_high
    lower_wick = body_low - low
    max_wick = np.maximum(upper_wick, lower_wick)
    atr_vals = atr.values

    mask = atr_vals > 0
    if mask.sum() < 50:
        return None

    wick_ratios = max_wick[mask] / atr_vals[mask]
    # Filter to meaningful wicks (> 0.05 ATR)
    wick_ratios = wick_ratios[wick_ratios > 0.05]
    if len(wick_ratios) < 30:
        return None

    p50, p90 = float(np.percentile(wick_ratios, 50)), float(np.percentile(wick_ratios, 90))

    low = max(canon[0], round(p50, 4))
    high = min(canon[1], round(p90, 4))
    if low >= high:
        return None

    return DerivedBound(low, high, f"wick_atr p50={p50:.3f} p90={p90:.3f}")


def _derive_sweep_lookback(df: pd.DataFrame) -> Optional[DerivedBound]:
    """
    Liquidity sweep lookback: estimate structural pivot spacing.
    Uses rolling-max/min distance to approximate how far back to look
    for liquidity levels.
    """
    canon = _canonical_bounds()[_PARAM_KEYS["sweep_lookback"]]
    close = df["close"].values
    n = len(close)
    if n < 200:
        return None

    # Find local pivots: points where close[i] is a 5-bar high or 5-bar low
    window = 5
    pivot_indices = []
    for i in range(window, n - window):
        local_high = close[i] == np.max(close[i - window : i + window + 1])
        local_low = close[i] == np.min(close[i - window : i + window + 1])
        if local_high or local_low:
            pivot_indices.append(i)

    if len(pivot_indices) < 10:
        return None

    # Spacing between consecutive pivots
    spacings = np.diff(pivot_indices)
    p30, p70 = float(np.percentile(spacings, 30)), float(np.percentile(spacings, 70))

    low = max(int(canon[0]), int(round(p30)))
    high = min(int(canon[1]), int(round(p70)))
    if low >= high:
        return None

    return DerivedBound(float(low), float(high), f"pivot_spacing p30={p30:.1f} p70={p70:.1f}")


def _derive_imbalance_ratio(df: pd.DataFrame) -> Optional[DerivedBound]:
    """
    OB imbalance_ratio: body / range distribution.
    High imbalance = strong directional candles (order block candidates).
    """
    canon = _canonical_bounds()[_PARAM_KEYS["imbalance_ratio"]]
    body = np.abs(df["close"].values - df["open"].values)
    candle_range = df["high"].values - df["low"].values

    mask = candle_range > 0
    if mask.sum() < 50:
        return None

    ratios = body[mask] / candle_range[mask]
    # OB detection cares about the upper half — strong conviction candles
    p50, p85 = float(np.percentile(ratios, 50)), float(np.percentile(ratios, 85))

    low = max(canon[0], round(p50, 4))
    high = min(canon[1], round(p85, 4))
    if low >= high:
        return None

    return DerivedBound(low, high, f"body_range p50={p50:.3f} p85={p85:.3f}")


def _derive_band_width_sigma(df: pd.DataFrame) -> Optional[DerivedBound]:
    """
    Regression band_width_sigma: fit a rolling linear regression and measure
    the residual spread in σ units.  The band width should cover the
    empirical spread.
    """
    canon = _canonical_bounds()[_PARAM_KEYS["band_width_sigma"]]
    close = df["close"].values
    n = len(close)
    window = 50
    if n < window + 30:
        return None

    # Rolling regression residuals (using simple detrending)
    residuals_sigma = []
    for i in range(window, n, window // 2):
        segment = close[i - window : i]
        x = np.arange(window, dtype=float)
        # Linear fit
        x_mean = x.mean()
        s_mean = segment.mean()
        denom = np.sum((x - x_mean) ** 2)
        if denom == 0:
            continue
        slope = np.sum((x - x_mean) * (segment - s_mean)) / denom
        intercept = s_mean - slope * x_mean
        fitted = slope * x + intercept
        resid = segment - fitted
        sigma = np.std(resid)
        if sigma > 0:
            # How many σ covers 95% of residuals
            max_resid = np.max(np.abs(resid))
            residuals_sigma.append(max_resid / sigma)

    if len(residuals_sigma) < 10:
        return None

    arr = np.array(residuals_sigma)
    p25, p75 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))

    low = max(canon[0], round(p25, 2))
    high = min(canon[1], round(p75, 2))
    if low >= high:
        return None

    return DerivedBound(low, high, f"resid_sigma p25={p25:.2f} p75={p75:.2f}")


# ---------------------------------------------------------------------------
# Integration helper
# ---------------------------------------------------------------------------


def narrow_parameter_space(
    default_space: Dict[str, "OptimizationParameterSpec"],
    data_bounds: Dict[str, DerivedBound],
) -> Dict[str, "OptimizationParameterSpec"]:
    """
    Return a *copy* of *default_space* with bounds tightened by *data_bounds*.

    For each param in *data_bounds*, the original [low, high] is intersected
    with the data-derived [low, high].  Params not in *data_bounds* keep
    their original bounds.
    """
    from app.sr.config_schema import OptimizationParameterConfig

    narrowed = {}
    for name, spec in default_space.items():
        if name in data_bounds:
            db = data_bounds[name]
            new_low = max(spec.low, db.low)
            new_high = min(spec.high, db.high)
            if new_low >= new_high:
                # Data bounds don't intersect → keep original
                narrowed[name] = spec
            else:
                narrowed[name] = OptimizationParameterConfig(
                    low=new_low,
                    high=new_high,
                    kind=spec.kind,
                    enabled=spec.enabled,
                    metadata_gate=spec.metadata_gate,
                )
                logger.info(
                    "Data-driven bounds for %s: [%.4f, %.4f] → [%.4f, %.4f] (%s)",
                    name,
                    spec.low,
                    spec.high,
                    new_low,
                    new_high,
                    db.source,
                )
        else:
            narrowed[name] = spec
    return narrowed

def _derive_merge_threshold_pct_atr(df: pd.DataFrame, atr: pd.Series) -> Optional[DerivedBound]:
    """
    Merge threshold: bounds around the 75th percentile of wick sizes.
    """
    canon = _canonical_bounds()["pipeline.merge_threshold_pct_atr"]
    
    # Calculate wicks
    upper_wick = df["high"] - df[["open", "close"]].max(axis=1)
    lower_wick = df[["open", "close"]].min(axis=1) - df["low"]
    
    # Take max wick for each bar to represent "typical noise structure"
    max_wick = np.maximum(upper_wick.values, lower_wick.values)
    wick_ratios = max_wick / atr.values
    
    if len(wick_ratios) < 50:
        return None
        
    # Remove NaNs and Infs (ZeroDivision protection)
    wick_ratios = wick_ratios[np.isfinite(wick_ratios)]
    if len(wick_ratios) == 0:
        return None
        
    p75 = np.percentile(wick_ratios, 75)
    baseline = max(0.15, p75 * 0.5)
    
    # Bound around baseline (± 50%)
    low = max(canon[0], baseline * 0.5)
    high = min(canon[1], baseline * 1.5)
    
    return DerivedBound(low=low, high=high, source="wick_p75 * 0.5 ±50%")

