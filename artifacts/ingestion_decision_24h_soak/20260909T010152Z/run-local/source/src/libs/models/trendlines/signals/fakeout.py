"""Trendlines-native fakeout and retest signal extractor."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from libs.models.trendlines.boundary import BoundaryResult

from .base import AlphaSignal, BaseAlphaExtractor
from .constants import BREAKOUT_STATES
from .utils import volume_is_trustworthy, z_score


class FakeoutAlphaExtractor(BaseAlphaExtractor):
    """Detect false breakouts/breakdowns and score retest reliability."""

    def __init__(
        self,
        *,
        hold_bars: int = 3,
        volume_lookback: int = 20,
        wick_rejection_ratio: float = 0.5,
        **params: Any,
    ):
        super().__init__(name="fakeout", **params)
        self.hold_bars = hold_bars
        self.volume_lookback = volume_lookback
        self.wick_rejection_ratio = wick_rejection_ratio

    def extract(
        self,
        result: BoundaryResult,
        history: Optional[List[BoundaryResult]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[AlphaSignal]:
        signals: List[AlphaSignal] = []
        if not result.is_valid:
            return signals

        tf = result.timeframe
        ctx = context or {}

        if history and len(history) >= 2:
            sig = self._breakout_reversal_signal(result, history, tf)
            if sig is not None:
                signals.append(sig)

        sig = self._wick_rejection_signal(result, ctx, tf)
        if sig is not None:
            signals.append(sig)

        sig = self._volume_confirmation_signal(result, ctx, tf)
        if sig is not None:
            signals.append(sig)

        if history and len(history) >= self.hold_bars:
            sig = self._retest_confirmation_signal(result, history, tf)
            if sig is not None:
                signals.append(sig)

        return signals

    def _breakout_reversal_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        curr = result.interaction
        if curr in BREAKOUT_STATES:
            return None

        scan_window = history[-self.hold_bars :]
        breakout_event = None
        bars_since = 0

        for i, br in enumerate(reversed(scan_window)):
            if br.interaction in BREAKOUT_STATES:
                breakout_event = br.interaction
                bars_since = i + 1
                break

        if breakout_event is None:
            return None

        was_breakout = breakout_event == "STRUCTURAL_BREAKOUT"
        direction = -1.0 if was_breakout else 1.0
        confidence = 1.0 - (bars_since / (self.hold_bars + 1))

        return AlphaSignal(
            name="false_breakout" if was_breakout else "false_breakdown",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "original_event": breakout_event,
                "bars_since": bars_since,
                "current_state": curr,
            },
        )

    def _wick_rejection_signal(
        self, result: BoundaryResult, ctx: Dict[str, Any], tf: str
    ) -> Optional[AlphaSignal]:
        ohlcv = ctx.get("ohlcv")
        atr = ctx.get("atr")
        if ohlcv is None or atr is None or atr <= 0:
            return None
        if len(ohlcv) < 1:
            return None

        last = ohlcv.iloc[-1]
        high = float(last.get("high", 0))
        low = float(last.get("low", 0))
        close = float(last.get("close", 0))
        hull_ceil = result.convex_hull_ceiling
        hull_floor = result.convex_hull_floor

        if math.isnan(hull_ceil) or math.isnan(hull_floor):
            return None

        up_penetration = high - hull_ceil if high > hull_ceil else 0.0
        closed_below_ceil = close <= hull_ceil
        down_penetration = hull_floor - low if low < hull_floor else 0.0
        closed_above_floor = close >= hull_floor

        wick_ratio_up = up_penetration / atr if up_penetration > 0 else 0.0
        wick_ratio_down = down_penetration / atr if down_penetration > 0 else 0.0

        if wick_ratio_up >= self.wick_rejection_ratio and closed_below_ceil:
            confidence = min(1.0, wick_ratio_up)
            return AlphaSignal(
                name="wick_rejection_resistance",
                direction=-1.0,
                confidence=round(confidence, 4),
                source=self.name,
                timeframe=tf,
                metadata={
                    "wick_ratio": round(wick_ratio_up, 4),
                    "penetration": round(up_penetration, 6),
                    "hull_ceiling": round(hull_ceil, 6),
                    "high": round(high, 6),
                    "close": round(close, 6),
                },
            )

        if wick_ratio_down >= self.wick_rejection_ratio and closed_above_floor:
            confidence = min(1.0, wick_ratio_down)
            return AlphaSignal(
                name="wick_rejection_support",
                direction=1.0,
                confidence=round(confidence, 4),
                source=self.name,
                timeframe=tf,
                metadata={
                    "wick_ratio": round(wick_ratio_down, 4),
                    "penetration": round(down_penetration, 6),
                    "hull_floor": round(hull_floor, 6),
                    "low": round(low, 6),
                    "close": round(close, 6),
                },
            )

        return None

    def _volume_confirmation_signal(
        self, result: BoundaryResult, ctx: Dict[str, Any], tf: str
    ) -> Optional[AlphaSignal]:
        if result.interaction not in BREAKOUT_STATES:
            return None
        if not volume_is_trustworthy(ctx):
            return None

        ohlcv = ctx.get("ohlcv")
        if ohlcv is None or "volume" not in ohlcv.columns:
            return None
        if len(ohlcv) < self.volume_lookback + 1:
            return None

        vols = ohlcv["volume"].values
        current_vol = float(vols[-1])
        lookback_vols = vols[-(self.volume_lookback + 1) : -1].astype(float)

        vol_z = z_score(current_vol, lookback_vols)
        if vol_z > 0:
            return None

        is_breakout = result.interaction == "STRUCTURAL_BREAKOUT"
        direction = -0.5 if is_breakout else 0.5
        confidence = min(1.0, abs(vol_z))

        mean_vol = float(lookback_vols.mean())
        std_vol = float(lookback_vols.std())

        return AlphaSignal(
            name="low_volume_breakout" if is_breakout else "low_volume_breakdown",
            direction=direction,
            confidence=round(confidence, 4),
            source=self.name,
            timeframe=tf,
            metadata={
                "current_volume": round(current_vol, 2),
                "mean_volume": round(mean_vol, 2),
                "std_volume": round(std_vol, 2),
                "z_score": round(vol_z, 4),
            },
        )

    def _retest_confirmation_signal(
        self, result: BoundaryResult, history: List[BoundaryResult], tf: str
    ) -> Optional[AlphaSignal]:
        curr = result.interaction
        window = history[-self.hold_bars :]

        breakout_count = sum(1 for br in window if br.interaction == "STRUCTURAL_BREAKOUT")
        breakdown_count = sum(1 for br in window if br.interaction == "STRUCTURAL_BREAKDOWN")

        threshold = max(self.hold_bars // 2, 1)

        if curr == "STRUCTURAL_BREAKOUT" and breakout_count >= threshold:
            hold_ratio = breakout_count / len(window)
            return AlphaSignal(
                name="confirmed_breakout",
                direction=1.0,
                confidence=round(hold_ratio, 4),
                source=self.name,
                timeframe=tf,
                metadata={
                    "breakout_bars": breakout_count,
                    "window_size": len(window),
                    "hold_ratio": round(hold_ratio, 3),
                },
            )

        if curr == "STRUCTURAL_BREAKDOWN" and breakdown_count >= threshold:
            hold_ratio = breakdown_count / len(window)
            return AlphaSignal(
                name="confirmed_breakdown",
                direction=-1.0,
                confidence=round(hold_ratio, 4),
                source=self.name,
                timeframe=tf,
                metadata={
                    "breakdown_bars": breakdown_count,
                    "window_size": len(window),
                    "hold_ratio": round(hold_ratio, 3),
                },
            )

        return None


__all__ = ["FakeoutAlphaExtractor"]