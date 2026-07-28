"""Runtime asset profile computed from market data at pipeline entry.

AssetProfile captures the statistical properties of a specific (asset, timeframe)
combination needed to derive adaptive config params. It is computed ONCE at the
facade entrypoint and propagated through the pipeline — no lazy computation,
no hidden data dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd


# Inline TF → minutes mapping (avoids importing from data/ which is above config/ in the dep graph)
_TF_MINUTES: Dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "1w": 10080,
}

_MIN_BARS_FOR_PROFILE = 20


def _tf_to_minutes(timeframe: str) -> int:
    minutes = _TF_MINUTES.get(timeframe)
    if minutes is not None:
        return minutes
    tf = timeframe.strip().lower()
    if tf.endswith("m") and tf[:-1].isdigit():
        return int(tf[:-1])
    if tf.endswith("h") and tf[:-1].isdigit():
        return int(tf[:-1]) * 60
    if tf.endswith("d") and tf[:-1].isdigit():
        return int(tf[:-1]) * 1440
    raise ValueError(f"Cannot parse timeframe to minutes: {timeframe!r}")


def _mean_true_range_simple(df: pd.DataFrame, window: int = 14) -> float:
    """Compute mean ATR from OHLC. Minimal standalone implementation."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
    atr_series = pd.Series(tr).rolling(window, min_periods=1).mean().to_numpy(dtype=float)
    return float(np.nanmean(atr_series))


@dataclass(frozen=True)
class AssetProfile:
    """Statistical summary of an (asset, timeframe) pair built from live OHLCV data.

    Every field needed by downstream derivation functions is pre-computed here.
    If a field cannot be computed (insufficient data), the profile build fails
    loud at the entrypoint, not silently downstream.
    """

    tf_minutes: int
    bar_duration_hours: float
    mean_atr: float
    mean_price: float
    n_bars: int
    median_touch_count: float  # from fit result if available; fallback heuristic
    mean_slope_abs: float  # mean |slope| from fit result lines; 0.0 if unavailable
    slope_diff_std: float  # std of slope diffs across lines; 0.0 if unavailable
    hull_width_atr_p20: float  # 20th pctl of hull-width-in-ATR; 0.0 if unavailable

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        timeframe: str,
        *,
        fit_result: Any | None = None,
    ) -> "AssetProfile":
        """Build a profile from OHLCV DataFrame and optional fit result.

        Raises ``ValueError`` if data is insufficient. This is intentional —
        failing at the entrypoint is better than degraded behavior downstream.
        """
        required_cols = {"open", "high", "low", "close"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"AssetProfile requires columns {sorted(required_cols)}; missing {sorted(missing)}")
        if len(df) < _MIN_BARS_FOR_PROFILE:
            raise ValueError(
                f"AssetProfile requires >= {_MIN_BARS_FOR_PROFILE} bars, got {len(df)}"
            )

        tf_minutes = _tf_to_minutes(timeframe)
        bar_duration_hours = tf_minutes / 60.0
        mean_atr = _mean_true_range_simple(df)
        mean_price = float(df["close"].mean())

        # Extract stats from fit result if available
        median_touch_count = 0.0
        mean_slope_abs = 0.0
        slope_diff_std = 0.0
        hull_width_atr_p20 = 0.0

        if fit_result is not None:
            all_lines = []
            if hasattr(fit_result, "support_lines"):
                all_lines.extend(fit_result.support_lines)
            if hasattr(fit_result, "resistance_lines"):
                all_lines.extend(fit_result.resistance_lines)

            if all_lines:
                touches = [float(line.touch_count) for line in all_lines]
                median_touch_count = float(np.median(touches)) if touches else 0.0
                slopes = [abs(float(line.slope)) for line in all_lines]
                mean_slope_abs = float(np.mean(slopes)) if slopes else 0.0
                if len(slopes) >= 2:
                    slope_diffs = np.diff(sorted(slopes))
                    slope_diff_std = float(np.std(slope_diffs))

        return cls(
            tf_minutes=tf_minutes,
            bar_duration_hours=bar_duration_hours,
            mean_atr=mean_atr,
            mean_price=mean_price,
            n_bars=len(df),
            median_touch_count=median_touch_count,
            mean_slope_abs=mean_slope_abs,
            slope_diff_std=slope_diff_std,
            hull_width_atr_p20=hull_width_atr_p20,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tf_minutes": self.tf_minutes,
            "bar_duration_hours": self.bar_duration_hours,
            "mean_atr": round(self.mean_atr, 8),
            "mean_price": round(self.mean_price, 4),
            "n_bars": self.n_bars,
            "median_touch_count": round(self.median_touch_count, 2),
            "mean_slope_abs": round(self.mean_slope_abs, 8),
            "slope_diff_std": round(self.slope_diff_std, 8),
            "hull_width_atr_p20": round(self.hull_width_atr_p20, 4),
        }


__all__ = ["AssetProfile"]
