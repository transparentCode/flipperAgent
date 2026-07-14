"""
Volume POC/VAH/VAL/HVN Kernel
==============================
Stateless volume-profile S/R detection kernel.

Extracts candidates at:
  * **POC** (Point of Control) — highest traded volume price
  * **VAH** (Value Area High) — upper boundary of value area
  * **VAL** (Value Area Low) — lower boundary of value area
  * **HVN** (High Volume Nodes) — secondary peaks

Core logic extracted from the original volume-profile implementation.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.sr.kernels.base import BaseSRKernel as _BaseSRKernel  # _to_datetime

import numpy as np
import pandas as pd

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.kernels.registry import register_kernel
from app.sr.models import CandidateLevel


@register_kernel("volume_poc")
class VolumePOCKernel(BaseSRKernel):
    """
    Volume Profile kernel — emits candidates at POC, VAH, VAL, and HVN.

    Runs multi-lookback VP (session / weekly / monthly) using lookback
    hours from ``AssetMetadata.session_lookback_hours``.  Each VP
    extracts POC, VAH, VAL, HVN independently.  Confluence across
    lookbacks is handled downstream by the aggregation stage.

    Timestamps use deterministic UTC normalization, and non-datetime
    inputs preserve hour-based lookbacks by converting configured
    lookback hours into a timeframe-aware bar count.

    Config params (via ``KernelConfig.kernel_params``):
      * ``num_bins`` — histogram bins (default 50)
      * ``value_area_pct`` — VA percentage (default 0.70)
      * ``poc_strength`` — base raw_score for POC (default 0.9)
      * ``vah_val_strength`` — base raw_score for VAH/VAL (default 0.7)
      * ``hvn_strength`` — base raw_score for HVN (default 0.6)
      * ``max_hvn_count`` — max HVN candidates per lookback (default 3)
      * ``hvn_prominence`` — min prominence for HVN peak (default 0.2)

    Rule-derived:
      * ``vp_lookback_hours`` — ``[session, weekly, monthly]`` from AssetMetadata
    """

    def compute(
        self,
        df: pd.DataFrame,
        config: KernelConfig,
    ) -> List[CandidateLevel]:
        params = config.kernel_params
        min_bars = max(1, int(params.get("min_bars", 10)))

        if len(df) < min_bars:
            return []

        num_bins = params.get("num_bins", 50)
        value_area_pct = params.get("value_area_pct", 0.70)
        poc_strength = params.get("poc_strength", 0.9)
        vah_val_strength = params.get("vah_val_strength", 0.7)
        hvn_strength = params.get("hvn_strength", 0.6)
        max_hvn = params.get("max_hvn_count", 3)
        hvn_prominence = params.get("hvn_prominence", 0.2)

        atr = self.get_atr(df, config)
        if atr <= 0:
            return []

        lookback_hours = config.rule_derived.vp_lookback_hours
        candidates: List[CandidateLevel] = []
        ts = _last_ts(df)

        for lb_hours in lookback_hours:
            lb_df = _get_lookback_data(df, lb_hours, config.timeframe)
            if len(lb_df) < min_bars:
                continue

            vp = _build_volume_profile(lb_df, num_bins)
            poc, vah, val = _extract_value_area(vp, value_area_pct)
            hvns = _find_hvn(vp, hvn_prominence, peak_distance=params.get("hvn_peak_distance_bins", 3))

            # Weight decreases for shorter lookbacks (session < weekly < monthly)
            weight = 1.0  # All lookbacks treated equally in v2; aggregation handles confluence

            half_w = params.get("zone_half_width_atr", 0.15) * atr  # VP zone half-width

            # POC
            if poc is not None:
                lt = _level_type_from_price(poc, df)
                candidates.append(CandidateLevel(
                    center_price=poc,
                    lower_bound=poc - half_w,
                    upper_bound=poc + half_w,
                    level_type=lt,
                    kernel_name="volume_poc",
                    timeframe=config.timeframe,
                    raw_score=poc_strength * weight,
                    metadata={"vp_type": "poc", "lookback_hours": lb_hours},
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

            # VAH (resistance)
            if vah is not None:
                candidates.append(CandidateLevel(
                    center_price=vah,
                    lower_bound=vah - half_w,
                    upper_bound=vah + half_w,
                    level_type=LevelType.RESISTANCE,
                    kernel_name="volume_poc",
                    timeframe=config.timeframe,
                    raw_score=vah_val_strength * weight,
                    metadata={"vp_type": "vah", "lookback_hours": lb_hours},
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

            # VAL (support)
            if val is not None:
                candidates.append(CandidateLevel(
                    center_price=val,
                    lower_bound=val - half_w,
                    upper_bound=val + half_w,
                    level_type=LevelType.SUPPORT,
                    kernel_name="volume_poc",
                    timeframe=config.timeframe,
                    raw_score=vah_val_strength * weight,
                    metadata={"vp_type": "val", "lookback_hours": lb_hours},
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

            # HVN
            for hvn_price in hvns[:max_hvn]:
                # Skip HVNs too close to POC/VAH/VAL
                min_dist = params.get("hvn_min_distance_atr", 0.3) * atr
                if any(
                    abs(hvn_price - p) < min_dist
                    for p in [poc, vah, val]
                    if p is not None
                ):
                    continue

                lt = _level_type_from_price(hvn_price, df)
                candidates.append(CandidateLevel(
                    center_price=hvn_price,
                    lower_bound=hvn_price - half_w,
                    upper_bound=hvn_price + half_w,
                    level_type=lt,
                    kernel_name="volume_poc",
                    timeframe=config.timeframe,
                    raw_score=hvn_strength * weight,
                    metadata={"vp_type": "hvn", "lookback_hours": lb_hours},
                    timestamp=ts,
                    atr_at_detection=atr,
                ))

        return candidates


# ---------------------------------------------------------------------------
# Pure helpers (no state)
# ---------------------------------------------------------------------------

def _last_ts(df: pd.DataFrame) -> datetime:
    if len(df) == 0:
        return datetime(1970, 1, 1, tzinfo=UTC)

    return _BaseSRKernel._to_datetime(df.index[-1], fallback_index=len(df) - 1)


def _level_type_from_price(price: float, df: pd.DataFrame) -> LevelType:
    """Classify as support or resistance relative to current close."""
    current = float(df["close"].iloc[-1])
    return LevelType.SUPPORT if price <= current else LevelType.RESISTANCE


def _get_lookback_data(df: pd.DataFrame, hours: int, timeframe: str) -> pd.DataFrame:
    if isinstance(df.index, pd.DatetimeIndex) and len(df) > 0:
        cutoff = df.index[-1] - timedelta(hours=hours)
        return df[df.index >= cutoff]

    bar_minutes = _timeframe_minutes(timeframe)
    lookback_bars = max(1, math.ceil(float(hours) * 60.0 / bar_minutes))
    return df.tail(lookback_bars)


def _timeframe_minutes(timeframe: str) -> int:
    value = str(timeframe).strip().lower()
    if not value:
        return 60

    unit = value[-1]
    multiplier = {
        "m": 1,
        "h": 60,
        "d": 1440,
        "w": 10080,
    }.get(unit)
    if multiplier is None:
        return 60

    try:
        amount = int(value[:-1])
    except ValueError:
        return 60

    return max(1, amount * multiplier)


def _build_volume_profile(df: pd.DataFrame, num_bins: int) -> Dict[str, Any]:
    """Build volume histogram from OHLCV bars."""
    if df.empty:
        return {"bins": np.array([]), "bin_centers": np.array([]),
                "volumes": np.array([]), "total_volume": 0.0}

    price_min = float(df["low"].min())
    price_max = float(df["high"].max())
    if price_min == price_max:
        # Additive fallback to handle zero/near-zero prices safely
        price_max = price_min + max(abs(price_min) * 0.001, 1e-8)

    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    highs = df["high"].to_numpy(dtype=float, copy=False)
    lows = df["low"].to_numpy(dtype=float, copy=False)
    vols = df["volume"].to_numpy(dtype=float, copy=False)

    lo_idx = np.searchsorted(bins, lows, side="right").astype(np.int64) - 1
    hi_idx = np.searchsorted(bins, highs, side="left").astype(np.int64)
    lo_idx = np.maximum(lo_idx, 0)
    hi_idx = np.minimum(hi_idx, num_bins)
    hi_idx = np.where(hi_idx <= lo_idx, lo_idx + 1, hi_idx)

    valid = (lo_idx < num_bins) & (hi_idx > lo_idx)
    volumes = np.zeros(num_bins, dtype=float)
    if np.any(valid):
        lo_idx = lo_idx[valid]
        hi_idx = hi_idx[valid]
        weights = vols[valid] / (hi_idx - lo_idx)
        diff = (
            np.bincount(lo_idx, weights=weights, minlength=num_bins + 1)
            - np.bincount(hi_idx, weights=weights, minlength=num_bins + 1)
        )
        volumes = np.cumsum(diff)[:-1]

    return {
        "bins": bins,
        "bin_centers": bin_centers,
        "volumes": volumes,
        "total_volume": float(volumes.sum()),
    }


def _extract_value_area(
    vp: Dict[str, Any],
    value_area_pct: float,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Extract POC, VAH, VAL from volume profile."""
    volumes = vp.get("volumes", np.array([]))
    bin_centers = vp.get("bin_centers", np.array([]))
    total_volume = vp.get("total_volume", 0.0)

    if len(volumes) == 0 or total_volume == 0:
        return None, None, None

    poc_idx = int(np.argmax(volumes))
    poc = float(bin_centers[poc_idx])

    target = total_volume * value_area_pct
    lo = poc_idx
    hi = poc_idx
    current = float(volumes[poc_idx])

    while current < target:
        can_lo = lo > 0
        can_hi = hi < len(volumes) - 1
        if not can_lo and not can_hi:
            break
        lo_v = float(volumes[lo - 1]) if can_lo else 0.0
        hi_v = float(volumes[hi + 1]) if can_hi else 0.0
        if lo_v >= hi_v and can_lo:
            lo -= 1
            current += lo_v
        elif can_hi:
            hi += 1
            current += hi_v
        elif can_lo:
            lo -= 1
            current += lo_v
        else:
            break

    bins = vp.get("bins", np.array([]))
    vah = float(bins[hi + 1]) if len(bins) > hi + 1 else float(bin_centers[hi])
    val = float(bins[lo]) if lo >= 0 else float(bin_centers[0])

    return poc, vah, val


def _find_hvn(vp: Dict[str, Any], prominence: float, peak_distance: int = 3) -> List[float]:
    """Find High Volume Nodes (local peaks)."""
    volumes = vp.get("volumes", np.array([]))
    bin_centers = vp.get("bin_centers", np.array([]))
    total_volume = vp.get("total_volume", 0.0)

    if len(volumes) < 3 or total_volume == 0:
        return []

    norm = volumes / total_volume
    hvns: List[Tuple[float, float]] = []

    try:
        from scipy.signal import find_peaks
        peaks, _ = find_peaks(norm, prominence=prominence, distance=peak_distance)
        hvns = [(float(bin_centers[p]), float(volumes[p])) for p in peaks]
    except ImportError:
        for i in range(1, len(volumes) - 1):
            if volumes[i] > volumes[i - 1] and volumes[i] > volumes[i + 1]:
                if norm[i] >= prominence:
                    hvns.append((float(bin_centers[i]), float(volumes[i])))

    hvns.sort(key=lambda x: x[1], reverse=True)
    return [p for p, _ in hvns]
