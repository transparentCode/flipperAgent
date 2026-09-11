"""
Feature Context
===============
Market context required for computing level feature vectors.

Holds current price, ATR, volume stats, optional regime state,
and VP data — everything the ``LevelFeatureBuilder`` needs
beyond the candidate itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.sr.models import AssetMetadata


@dataclass
class FeatureContext:
    """
    Contextual data for feature computation.

    Built once per (asset, timeframe) pipeline invocation and
    passed to ``LevelFeatureBuilder.build()`` for every candidate.

    Attributes:
        df: OHLCV DataFrame for the current timeframe.
        current_price: Latest close price.
        atr: 14-period ATR at latest bar.
        volume_mean: Rolling mean volume (20-bar).
        volume_kurtosis: Rolling kurtosis of volume (200+ bar).
        poc_price: Volume-profile POC (if VP kernel ran), else None.
        vah_price: VP VAH, else None.
        val_price: VP VAL, else None.
        regime_state: Optional regime label (None when unavailable).
        regime_confidence: Confidence of regime label [0, 1].
        gap_events: List of recent gap events for gap-related features.
        bar_count: Total bars available.
    """
    df: pd.DataFrame
    current_price: float
    atr: float
    volume_mean: float = 0.0
    volume_kurtosis: float = 0.0
    poc_price: Optional[float] = None
    vah_price: Optional[float] = None
    val_price: Optional[float] = None
    regime_state: Optional[str] = None
    regime_confidence: float = 0.0
    gap_events: List[Dict[str, Any]] = field(default_factory=list)
    bar_count: int = 0
    metadata: Optional[AssetMetadata] = None
    timeframe: str = "1h"

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        atr: float,
        *,
        volume_mean_window: int = 20,
        volume_kurtosis_window: int = 200,
        poc: Optional[float] = None,
        vah: Optional[float] = None,
        val: Optional[float] = None,
        regime_state: Optional[str] = None,
        regime_confidence: float = 0.0,
        gap_events: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[AssetMetadata] = None,
        timeframe: str = "1h",
    ) -> FeatureContext:
        """Build context from OHLCV DataFrame."""
        vol = df["volume"].values
        mean_window = max(1, int(volume_mean_window))
        kurt_window = max(1, int(volume_kurtosis_window))

        vol_mean = float(np.mean(vol[-mean_window:])) if len(vol) >= mean_window else float(np.mean(vol))

        from scipy.stats import kurtosis as sp_kurtosis  # type: ignore[import-untyped]
        try:
            window = vol[-kurt_window:] if len(vol) >= kurt_window else vol
            if len(window) < 2 or np.all(window == window[0]):
                vol_kurt = 0.0
            else:
                vol_kurt = float(sp_kurtosis(window, fisher=True))
        except Exception:
            vol_kurt = 0.0
        if not np.isfinite(vol_kurt):
            vol_kurt = 0.0

        return cls(
            df=df,
            current_price=float(df["close"].iloc[-1]),
            atr=atr,
            volume_mean=vol_mean,
            volume_kurtosis=vol_kurt,
            poc_price=poc,
            vah_price=vah,
            val_price=val,
            regime_state=regime_state,
            regime_confidence=regime_confidence,
            gap_events=gap_events or [],
            bar_count=len(df),
            metadata=metadata,
            timeframe=timeframe,
        )

    def bars_for_hours(self, hours: float) -> int:
        """Convert a trading-hours horizon to bars for the active timeframe."""
        if hours <= 0:
            return 1

        minutes = _timeframe_minutes(self.timeframe)
        return max(1, int(math.ceil(float(hours) * 60.0 / minutes)))

    def derived_lookback_bars(
        self,
        *,
        override_hours: Optional[float],
        metadata_slot: int,
        fallback_bars: int,
    ) -> int:
        """Resolve a lookback horizon from explicit override or asset metadata."""
        hours = override_hours
        if hours is None and self.metadata is not None:
            lookbacks = self.metadata.session_lookback_hours
            if metadata_slot < len(lookbacks):
                hours = float(lookbacks[metadata_slot])

        if hours is not None:
            return min(self.bar_count, self.bars_for_hours(hours))

        return min(self.bar_count, max(1, int(fallback_bars)))


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
