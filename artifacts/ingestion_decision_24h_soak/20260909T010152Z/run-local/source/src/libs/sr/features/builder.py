"""
Level Feature Builder
=====================
Computes a typed ``LevelFeatureVector`` for each ``CandidateLevel``.

Pure function: candidate + market context + other candidates → features.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from app.sr.config_schema import FeaturesConfig
from app.sr.models import LevelType
from app.sr.features.context import FeatureContext
from app.sr.models import CandidateLevel, LevelFeatureVector


class LevelFeatureBuilder:
    """
    Feature builder for the v2 S/R pipeline (§2B).

    Usage::

        builder = LevelFeatureBuilder()
        fv = builder.build(candidate, all_candidates, context)
    """

    def __init__(self, config: FeaturesConfig | None = None):
        self._config = config or FeaturesConfig()

    def build(
        self,
        candidate: CandidateLevel,
        all_candidates: List[CandidateLevel],
        context: FeatureContext,
    ) -> LevelFeatureVector:
        """
        Compute feature vector for a single candidate level.

        Args:
            candidate: The candidate to compute features for.
            all_candidates: All candidates from all kernels (for cluster density, kernel agreement).
            context: Market context (df, ATR, VP, regime, gaps).

        Returns:
            Immutable ``LevelFeatureVector``.
        """
        df = context.df
        atr = context.atr
        price = context.current_price

        if atr <= 0 or len(df) < 2:
            return LevelFeatureVector()

        cp = candidate.center_price
        cfg = self._config
        feature_atr = float(candidate.atr_at_detection) if candidate.atr_at_detection > 0 else atr

        # Ensure look-ahead safety: all historical feature extraction MUST strictly 
        # end at the candidate's formation bar (t), never using future data.
        formation_idx = self._formation_index(candidate, df)
        if formation_idx is None or formation_idx >= len(df):
            formation_idx = len(df) - 1

        # --- Touch analysis ---
        touch_count, rejection_ratio, vol_at_touches, wick_depth = self._touch_analysis(
            df,
            cp,
            feature_atr,
            formation_idx,
            candidate.level_type,
            proximity_atr=cfg.touch_proximity_atr,
        )

        volume_trend_lookback_bars = context.derived_lookback_bars(
            override_hours=cfg.volume_trend_lookback_hours,
            metadata_slot=1,
            fallback_bars=200,
        )
        false_breakout_lookback_bars = context.derived_lookback_bars(
            override_hours=cfg.false_breakout_lookback_hours,
            metadata_slot=2,
            fallback_bars=500,
        )

        # --- Time since formation ---
        time_since = max(0, context.bar_count - formation_idx - 1)

        # --- Cluster density (candidates within 1 ATR) ---
        cluster_density = sum(
            1 for c in all_candidates
            if abs(c.center_price - cp) <= cfg.cluster_density_proximity_atr * feature_atr and c is not candidate
        )

        # --- ATR distance from current price ---
        atr_dist = abs(cp - price) / feature_atr

        # --- POC distance ---
        poc_dist = 0.0
        if context.poc_price is not None:
            poc_dist = abs(cp - context.poc_price) / feature_atr

        # --- Value Area overlap ---
        va_overlap = 0.0
        if context.vah_price is not None and context.val_price is not None:
            va_overlap = _zone_overlap_fraction(
                candidate.lower_bound, candidate.upper_bound,
                context.val_price, context.vah_price,
            )

        # --- MTF confluence (placeholder — filled at aggregation stage) ---
        mtf_confluence = 0

        # --- Breakout recency ---
        breakout_recency = self._breakout_recency(
            df,
            cp,
            feature_atr,
            formation_idx,
            proximity_atr=cfg.breakout_proximity_atr,
        )

        # --- Volume trend at level ---
        vol_trend = self._volume_trend_at_level(
            df,
            cp,
            feature_atr,
            formation_idx,
            proximity_atr=cfg.volume_trend_proximity_atr,
            lookback_bars=volume_trend_lookback_bars,
        )

        # --- False breakout count ---
        false_breakout_count = self._false_breakout_count(
            df,
            cp,
            feature_atr,
            formation_idx,
            threshold_atr=cfg.false_breakout_threshold_atr,
            window_bars=cfg.false_breakout_window_bars,
            lookback_bars=false_breakout_lookback_bars,
        )

        # --- Kernel agreement ---
        kernel_agreement = len(set(
            c.kernel_name for c in all_candidates
            if abs(c.center_price - cp) <= cfg.kernel_agreement_proximity_atr * feature_atr
        ))

        # --- Gap features ---
        gap_prox, gap_align = self._gap_features(candidate, context, feature_atr)

        # --- Regime alignment ---
        regime_alignment = self._regime_alignment(candidate, context, cfg)

        return LevelFeatureVector(
            touch_count=touch_count,
            rejection_ratio=rejection_ratio,
            volume_at_touches=vol_at_touches,
            time_since_formation=float(time_since),
            cluster_density=float(cluster_density),
            atr_distance_from_price=atr_dist,
            poc_distance_atr=poc_dist,
            value_area_overlap=va_overlap,
            mtf_confluence_count=mtf_confluence,
            breakout_recency=breakout_recency,
            volume_trend_at_level=vol_trend,
            wick_depth_max_atr=wick_depth,
            false_breakout_count=false_breakout_count,
            kernel_agreement=kernel_agreement,
            gap_proximity_atr=gap_prox,
            gap_direction_alignment=gap_align,
            regime_alignment=regime_alignment,
            extra_features={},
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _formation_index(candidate: CandidateLevel, df: pd.DataFrame) -> int | None:
        """Resolve candidate formation index from metadata keys or timestamp."""
        metadata = candidate.metadata or {}

        for key in ("pivot_index", "gap_index", "ob_index", "displacement_index"):
            value = metadata.get(key)
            if isinstance(value, int):
                return value

        for key, value in metadata.items():
            if key.endswith("_index") and isinstance(value, int):
                return value

        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        ts = pd.Timestamp(candidate.timestamp)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        index = df.index
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")

        # Align timestamp resolution with index to avoid lossless-conversion errors
        if hasattr(index.dtype, 'str') and hasattr(ts, 'as_unit'):
            # Extract unit from index dtype (e.g. 'datetime64[ms]' -> 'ms')
            unit = getattr(index, 'unit', None)
            if unit is not None:
                ts = ts.as_unit(unit)

        pos = int(index.searchsorted(ts, side="right")) - 1
        return pos if pos >= 0 else None

    @staticmethod
    def _touch_analysis(
        df,
        price: float,
        atr: float,
        end_idx: int,
        level_type: Any,
        *,
        proximity_atr: float,
    ) -> tuple:
        """Count touches within ATR proximity, compute rejection ratio and volume."""
        proximity = max(0.0, float(proximity_atr)) * atr
        highs = df["high"].values[:end_idx + 1]
        lows = df["low"].values[:end_idx + 1]
        closes = df["close"].values[:end_idx + 1]
        opens = df["open"].values[:end_idx + 1]
        volumes = df["volume"].values[:end_idx + 1]

        condition = (lows <= price + proximity) & (highs >= price - proximity)
        touch_indices = np.where(condition)[0]
        
        touches = len(touch_indices)
        if touches == 0:
            return 0, 0.0, 0.0, 0.0

        touch_volumes = volumes[touch_indices]
        touch_closes = closes[touch_indices]
        touch_opens = opens[touch_indices]
        touch_highs = highs[touch_indices]
        touch_lows = lows[touch_indices]
        
        bodies = np.abs(touch_closes - touch_opens)
        
        # Only evaluate the relevant side's wick
        from app.sr.models import LevelType
        if level_type == LevelType.SUPPORT:
            wicks = np.minimum(touch_opens, touch_closes) - touch_lows
        elif level_type == LevelType.RESISTANCE:
            wicks = touch_highs - np.maximum(touch_opens, touch_closes)
        else:
            wicks = touch_highs - touch_lows - bodies
        
        rejection_ratios = np.zeros_like(bodies, dtype=float)
        mask = bodies > 0
        rejection_ratios[mask] = wicks[mask] / bodies[mask]
        
        wick_depths = np.where(price >= touch_closes, (price - touch_lows) / atr, (touch_highs - price) / atr)

        avg_rej = float(np.mean(rejection_ratios))
        mean_vol = float(np.mean(volumes))
        vol_ratio = (float(np.mean(touch_volumes)) / mean_vol) if mean_vol > 0 else 0.0
        max_wick = float(np.max(wick_depths))

        return touches, avg_rej, vol_ratio, max_wick

    @staticmethod
    def _breakout_recency(
        df,
        price: float,
        atr: float,
        end_idx: int,
        *,
        proximity_atr: float,
    ) -> float:
        """Bars since the last time close moved beyond the zone."""
        closes = df["close"].values[:end_idx + 1]
        proximity = proximity_atr * atr
        for i in range(len(closes) - 1, -1, -1):
            if abs(closes[i] - price) > proximity:
                return float(len(closes) - 1 - i)
        return 0.0

    @staticmethod
    def _volume_trend_at_level(
        df,
        price: float,
        atr: float,
        end_idx: int,
        *,
        proximity_atr: float,
        lookback_bars: int,
    ) -> float:
        """Slope of volume at bars near the level (positive = rising)."""
        proximity = proximity_atr * atr
        closes = df["close"].values[:end_idx + 1]
        volumes = df["volume"].values[:end_idx + 1]

        start_idx = max(0, len(closes) - max(1, int(lookback_bars)))
        
        indices = [
            i for i in range(start_idx, len(closes))
            if abs(closes[i] - price) <= proximity
        ]
        if len(indices) < 3:
            return 0.0
        y = np.array([volumes[i] for i in indices], dtype=float)
        x = np.arange(len(y), dtype=float)
        if np.std(y) == 0:
            return 0.0
        slope = float(np.polyfit(x, y, 1)[0])
        mean_vol = float(np.mean(y))
        return slope / mean_vol if mean_vol > 0 else 0.0

    @staticmethod
    def _false_breakout_count(
        df,
        price: float,
        atr: float,
        end_idx: int,
        *,
        threshold_atr: float,
        window_bars: int,
        lookback_bars: int,
    ) -> int:
        """Count times price closed beyond zone then returned within N bars."""
        closes = df["close"].values[:end_idx + 1]

        start_idx = max(0, len(closes) - max(1, int(lookback_bars)))
        closes = closes[start_idx:]
        
        threshold = threshold_atr * atr
        window = max(1, int(window_bars))
        count = 0
        i = 0
        while i < len(closes) - window:
            if abs(closes[i] - price) > threshold:
                # Check if price returned within window
                return_idx = -1
                for j in range(i + 1, min(i + window + 1, len(closes))):
                    if abs(closes[j] - price) <= threshold:
                        return_idx = j
                        break
                
                if return_idx != -1:
                    count += 1
                    i = return_idx  # Resume exactly at the return point
                    continue
            i += 1
        return count

    @staticmethod
    def _gap_features(
        candidate: CandidateLevel,
        context: FeatureContext,
        atr: float,
    ) -> tuple:
        """Compute gap_proximity_atr and gap_direction_alignment."""
        if not context.gap_events:
            return 0.0, 0.0

        cp = candidate.center_price
        closest_dist = float("inf")
        closest_gap = None

        for gap in context.gap_events:
            gap_price = gap.get("price", 0.0)
            dist = abs(cp - gap_price) / atr if atr > 0 else float("inf")
            if dist < closest_dist:
                closest_dist = dist
                closest_gap = gap

        if closest_gap is None:
            return 0.0, 0.0

        # Direction alignment
        gap_dir = closest_gap.get("direction", 0)  # +1 up, -1 down
        if candidate.level_type == LevelType.RESISTANCE:
            alignment = float(gap_dir)  # gap-up near resistance = +1
        else:
            alignment = float(-gap_dir)  # gap-down near support = +1

        return closest_dist, alignment

    @staticmethod
    def _regime_alignment(
        candidate: CandidateLevel,
        context: FeatureContext,
        config: FeaturesConfig,
    ) -> float:
        """Regime alignment: [-1, 1]. Default 0.0 when regime unavailable."""
        if context.regime_state is None:
            return 0.0

        regime = context.regime_state.lower()
        lt = candidate.level_type
        weights = config.regime_alignment

        if regime == "trending":
            # In trend, resistance likely to break (+1 for breakout), support may hold
            if lt == LevelType.RESISTANCE:
                return float(weights.get("trending_resistance", -0.5))
            return float(weights.get("trending_support", 0.5))
        elif regime == "ranging":
            # In range, both S and R likely to hold
            return float(weights.get("ranging", 0.7))
        elif regime == "volatile":
            # High vol — uncertain
            return float(weights.get("volatile", 0.0))
        return 0.0


def _zone_overlap_fraction(
    zone_lo: float, zone_hi: float,
    va_lo: float, va_hi: float,
) -> float:
    """Fraction of zone overlapping with value area [0, 1]."""
    overlap_lo = max(zone_lo, va_lo)
    overlap_hi = min(zone_hi, va_hi)
    if overlap_hi <= overlap_lo:
        return 0.0
    zone_width = zone_hi - zone_lo
    if zone_width <= 0:
        return 0.0
    return (overlap_hi - overlap_lo) / zone_width
