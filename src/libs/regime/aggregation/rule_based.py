"""
Feature Aggregator (Rule-Based)
================================
Combines 4 regime layers into a unified RegimeFeatures output.

Layers:
  HMM       → p_trending / NON_TRENDING
  VolOverlay → vol_percentile / HIGH_VOL | LOW_VOL
  BCPD       → changepoint_prob
  Hilbert    → dominant_period, confidence

Direction overlay (non-hindsight ROC over direction_period bars):
  Price ROC > +bull_roc_thresh  → BULL
  Price ROC < -bull_roc_thresh  → BEAR
  Otherwise                     → FLAT

Combined regime labels (9):
  Trend + direction:
    CLEAN_TREND_BULL      — smooth uptrend
    CLEAN_TREND_BEAR      — smooth downtrend
    CLEAN_TREND_FLAT      — trending but indeterminate direction
    VOLATILE_TREND_BULL   — volatile uptrend
    VOLATILE_TREND_BEAR   — volatile downtrend
    VOLATILE_TREND_FLAT   — volatile, indeterminate direction
  Non-trend:
    QUIET_MR_RANGE        — quiet, range-bound
    QUIET_MR_SQUEEZE      — quiet, vol contracting (potential breakout)
    CHOPPY                — high vol, non-trending
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from libs.regime.aggregation.base import BaseAggregator
from libs.regime.models import ChangePointSignal, HMMState, RegimeFeatures, VolState

logger = logging.getLogger("app.regime")

# ── Regime label constants ────────────────────────────────────────────────────

CLEAN_TREND_BULL    = "CLEAN_TREND_BULL"
CLEAN_TREND_BEAR    = "CLEAN_TREND_BEAR"
CLEAN_TREND_FLAT    = "CLEAN_TREND_FLAT"
VOLATILE_TREND_BULL = "VOLATILE_TREND_BULL"
VOLATILE_TREND_BEAR = "VOLATILE_TREND_BEAR"
VOLATILE_TREND_FLAT = "VOLATILE_TREND_FLAT"
QUIET_MR_RANGE      = "QUIET_MR_RANGE"
QUIET_MR_SQUEEZE    = "QUIET_MR_SQUEEZE"
CHOPPY              = "CHOPPY"

ALL_REGIMES = [
    CLEAN_TREND_BULL, CLEAN_TREND_BEAR, CLEAN_TREND_FLAT,
    VOLATILE_TREND_BULL, VOLATILE_TREND_BEAR, VOLATILE_TREND_FLAT,
    QUIET_MR_RANGE, QUIET_MR_SQUEEZE, CHOPPY,
]

# Convenience sets for strategy filters
TREND_REGIMES    = {CLEAN_TREND_BULL, CLEAN_TREND_BEAR, CLEAN_TREND_FLAT,
                    VOLATILE_TREND_BULL, VOLATILE_TREND_BEAR, VOLATILE_TREND_FLAT}
CLEAN_TREND_REGIMES   = {CLEAN_TREND_BULL, CLEAN_TREND_BEAR, CLEAN_TREND_FLAT}
VOLATILE_TREND_REGIMES = {VOLATILE_TREND_BULL, VOLATILE_TREND_BEAR, VOLATILE_TREND_FLAT}
BULL_REGIMES     = {CLEAN_TREND_BULL, VOLATILE_TREND_BULL}
BEAR_REGIMES     = {CLEAN_TREND_BEAR, VOLATILE_TREND_BEAR}
NON_TREND_REGIMES = {QUIET_MR_RANGE, QUIET_MR_SQUEEZE, CHOPPY}

# ── Ensemble group mapping (9 regimes → 4 groups + TRANSITION) ───────────────
# Used by RegimeEnsembleBlender for regime-conditioned weight lookup.
# TRANSITION is not mapped from any regime label — it is dynamically activated
# via changepoint_prob threshold in the blender.
# Redesigned 2026-05-31: split BULL/BEAR (opposite return profiles) instead of
# CLEAN/VOLATILE (no statistical difference). See backtest_blender_redesign.ipynb.
REGIME_TO_GROUP: dict[str, str] = {
    CLEAN_TREND_BULL:     "TREND_BULL",
    CLEAN_TREND_BEAR:     "TREND_BEAR",
    CLEAN_TREND_FLAT:     "RANGE",
    VOLATILE_TREND_BULL:  "TREND_BULL",
    VOLATILE_TREND_BEAR:  "TREND_BEAR",
    VOLATILE_TREND_FLAT:  "CHOPPY",
    QUIET_MR_RANGE:       "RANGE",
    QUIET_MR_SQUEEZE:     "RANGE",
    CHOPPY:               "CHOPPY",
}

ENSEMBLE_GROUPS = ["TREND_BULL", "TREND_BEAR", "RANGE", "CHOPPY", "TRANSITION"]

_BB_BASE = 20
_RSI_BASE = 14


@dataclass(frozen=True)
class AggregatorConfig:
    """Configuration for FeatureAggregator — 9-regime system."""

    # Adaptive period (Hilbert)
    bb_base: int = _BB_BASE
    rsi_base: int = _RSI_BASE
    hilbert_high_threshold: float = 0.70

    # Direction overlay
    direction_period: int = 20           # bars for ROC direction signal
    bull_roc_thresh: float = 0.02        # 2% ROC → BULL (used if adaptive is False)
    adaptive_roc: bool = True            # Use 0.5 * rolling std for threshold instead of fixed

    # QUIET_MR sub-classification
    vol_squeeze_pct: float = 30.0        # vol_percentile < this → SQUEEZE

    # Direction overlay: adaptive ROC threshold
    roc_std_window: int = 100            # Window for rolling std of ROC (adaptive threshold)

    # Position scale by regime (long-short: negative = short)
    position_scale: dict = field(
        default_factory=lambda: {
            CLEAN_TREND_BULL:     1.0,
            CLEAN_TREND_BEAR:    -1.0,
            CLEAN_TREND_FLAT:     0.0,
            VOLATILE_TREND_BULL:  0.6,
            VOLATILE_TREND_BEAR: -0.6,
            VOLATILE_TREND_FLAT:  0.0,
            QUIET_MR_RANGE:       0.3,
            QUIET_MR_SQUEEZE:     0.0,
            CHOPPY:               0.0,
        }
    )

    # ATR multiplier for stops by regime
    atr_multiplier: dict = field(
        default_factory=lambda: {
            CLEAN_TREND_BULL:    2.0,
            CLEAN_TREND_BEAR:    2.0,
            CLEAN_TREND_FLAT:    2.0,
            VOLATILE_TREND_BULL: 3.5,
            VOLATILE_TREND_BEAR: 3.5,
            VOLATILE_TREND_FLAT: 3.5,
            QUIET_MR_RANGE:      1.5,
            QUIET_MR_SQUEEZE:    1.5,
            CHOPPY:              2.5,
        }
    )

    # Holding period (bars) by regime
    holding_period: dict = field(
        default_factory=lambda: {
            CLEAN_TREND_BULL:    20,
            CLEAN_TREND_BEAR:    20,
            CLEAN_TREND_FLAT:    15,
            VOLATILE_TREND_BULL: 10,
            VOLATILE_TREND_BEAR: 10,
            VOLATILE_TREND_FLAT: 8,
            QUIET_MR_RANGE:      8,
            QUIET_MR_SQUEEZE:    5,
            CHOPPY:              3,
        }
    )

    # Decay position_scale when BCPD fires a fresh changepoint
    cp_position_decay: float = 0.5

    # Minimum bars a regime must hold before switching (prevents whipsaws)
    min_dwell_bars: int = 5

    # Adaptive period fallback scale per regime (used when Hilbert confidence is low)
    adaptive_period_scale: dict = field(
        default_factory=lambda: {
            CLEAN_TREND_BULL:    1.0,
            CLEAN_TREND_BEAR:    1.0,
            CLEAN_TREND_FLAT:    1.0,
            VOLATILE_TREND_BULL: 0.75,
            VOLATILE_TREND_BEAR: 0.75,
            VOLATILE_TREND_FLAT: 0.75,
            QUIET_MR_RANGE:      1.25,
            QUIET_MR_SQUEEZE:    1.5,
            CHOPPY:              0.5,
        }
    )


class FeatureAggregator(BaseAggregator):
    """
    Rule-based aggregator: combines HMM + VolOverlay + BCPD + Hilbert + Direction.

    Produces 9 regime labels by combining:
      - HMM trend state (TRENDING / NON_TRENDING)
      - Vol state (LOW_VOL / HIGH_VOL)
      - Price direction (BULL / BEAR / FLAT) — from ROC over direction_period
      - QUIET_MR squeeze detection (vol_percentile < vol_squeeze_pct)

    Usage
    -----
    agg      = FeatureAggregator()
    features = agg.aggregate(hmm_state, vol_state, cp_signal, period, confidence, close_series)
    """

    def __init__(self, config: Optional[AggregatorConfig] = None):
        self.config = config or AggregatorConfig()
        self._current_regime: Optional[str] = None
        self._dwell_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def aggregate(
        self,
        hmm: HMMState,
        vol: VolState,
        cp: ChangePointSignal,
        hilbert_period: float,
        hilbert_confidence: float,
        close: Optional[pd.Series] = None,
    ) -> RegimeFeatures:
        direction = self._compute_direction_scalar(close) if close is not None else "FLAT"
        raw_regime = self._combine_regime(hmm, vol, direction)
        regime = self._apply_dwell(raw_regime)
        position_scale = self._blend_position_scale(
            hmm.p_trending, vol.vol_regime, cp.change_point_prob, direction
        )
        adaptive_period = self._compute_adaptive_period(
            hilbert_period, hilbert_confidence, regime
        )
        return RegimeFeatures(
            timestamp=cp.timestamp,
            regime=regime,
            p_trending=hmm.p_trending,
            vol_percentile=vol.vol_percentile,
            changepoint_prob=cp.change_point_prob,
            adaptive_period=adaptive_period,
            position_scale=position_scale,
            atr_multiplier=self.config.atr_multiplier.get(regime, 2.0),
            holding_period=self.config.holding_period.get(regime, 20),
            hmm_state=hmm,
            vol_state=vol,
            change_signal=cp,
            hilbert_period=hilbert_period,
            hilbert_confidence=hilbert_confidence,
        )

    def aggregate_series(
        self,
        hmm_df: pd.DataFrame,
        vol_df: pd.DataFrame,
        cp_df: pd.DataFrame,
        hilbert_periods: "np.ndarray | None" = None,
        hilbert_confidences: "np.ndarray | None" = None,
        close: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Aggregate series given pre-computed per-bar DataFrames.

        Expects columns:
          hmm_df  : hmm_p_trending, hmm_regime
          vol_df  : vol_percentile, vol_regime
          cp_df   : bcpd_prob

        Optional:
          hilbert_periods, hilbert_confidences : aligned arrays
          close : price series for direction overlay (same index as hmm_df)
        """
        result = pd.DataFrame(index=hmm_df.index)
        result["p_trending"]      = hmm_df["hmm_p_trending"]
        result["vol_percentile"]  = vol_df["vol_percentile"]
        result["vol_regime"]      = vol_df["vol_regime"]
        result["changepoint_prob"] = cp_df["bcpd_prob"]
        if "bcpd_signal" in cp_df.columns:
            result["bcpd_signal"] = cp_df["bcpd_signal"]
        # Forward per-channel BCPD columns from multichannel detection
        for ch_col in ("bcpd_prob_returns", "bcpd_prob_volume", "bcpd_prob_range"):
            if ch_col in cp_df.columns:
                result[ch_col] = cp_df[ch_col]

        n = len(result)
        if hilbert_periods is not None and len(hilbert_periods) == n:
            result["hilbert_period"]     = hilbert_periods
            result["hilbert_confidence"] = (
                hilbert_confidences if hilbert_confidences is not None else np.zeros(n)
            )
        else:
            result["hilbert_period"]     = float(_BB_BASE)
            result["hilbert_confidence"] = 0.0

        # Direction overlay (non-hindsight ROC)
        if close is not None and len(close) == n:
            result["trend_direction"] = self._compute_direction_series(close)
        else:
            result["trend_direction"] = "FLAT"

        # ── Vectorized regime assignment (replaces iterrows) ─────────────
        trending = result["p_trending"].values >= 0.5
        high_vol = result["vol_regime"].values == "HIGH_VOL"
        direction = result["trend_direction"].values
        vol_pct = result["vol_percentile"].values

        is_bull = direction == "BULL"
        is_bear = direction == "BEAR"
        is_flat = ~is_bull & ~is_bear  # covers "FLAT" and any other value

        conditions = [
            trending & ~high_vol & is_bull,   # CLEAN_TREND_BULL
            trending & ~high_vol & is_bear,   # CLEAN_TREND_BEAR
            trending & ~high_vol & is_flat,   # CLEAN_TREND_FLAT
            trending & high_vol & is_bull,    # VOLATILE_TREND_BULL
            trending & high_vol & is_bear,    # VOLATILE_TREND_BEAR
            trending & high_vol & is_flat,    # VOLATILE_TREND_FLAT
            ~trending & high_vol,             # CHOPPY
            ~trending & ~high_vol & (vol_pct < self.config.vol_squeeze_pct),  # QUIET_MR_SQUEEZE
            ~trending & ~high_vol,            # QUIET_MR_RANGE (default non-trend low-vol)
        ]
        choices = [
            CLEAN_TREND_BULL, CLEAN_TREND_BEAR, CLEAN_TREND_FLAT,
            VOLATILE_TREND_BULL, VOLATILE_TREND_BEAR, VOLATILE_TREND_FLAT,
            CHOPPY, QUIET_MR_SQUEEZE, QUIET_MR_RANGE,
        ]
        result["regime"] = np.select(conditions, choices, default=CHOPPY)

        # Dwell time filter (inherently sequential — kept as-is)
        result["regime"] = self._apply_dwell_series(result["regime"].values)

        # ── Vectorized adaptive_period (replaces .apply) ──────────────
        h_period = result["hilbert_period"].values.astype(float)
        h_conf = result["hilbert_confidence"].values.astype(float)
        regimes = result["regime"].values

        # Build per-regime scale lookup for the low-confidence path
        aps = self.config.adaptive_period_scale
        regime_scale = np.array([aps.get(r, 1.0) for r in regimes])

        high_conf_mask = h_conf >= self.config.hilbert_high_threshold
        scale = np.where(high_conf_mask, h_period / self.config.bb_base, regime_scale)
        scale = np.clip(scale, 0.5, 2.0)
        adaptive_period = np.maximum(5, np.round(self.config.bb_base * scale)).astype(int)
        result["adaptive_period"] = adaptive_period

        # ── Vectorized position_scale (replaces .apply) ───────────────
        p_trend = result["p_trending"].values.astype(float)
        cp_prob = result["changepoint_prob"].values.astype(float)
        ps = self.config.position_scale

        # Trending-side scale: pick by direction × vol
        t_bull_hv = ps[VOLATILE_TREND_BULL]
        t_bull_lv = ps[CLEAN_TREND_BULL]
        t_bear_hv = ps[VOLATILE_TREND_BEAR]
        t_bear_lv = ps[CLEAN_TREND_BEAR]
        t_flat_hv = ps[VOLATILE_TREND_FLAT]
        t_flat_lv = ps[CLEAN_TREND_FLAT]

        t_scale = np.where(
            is_bull,
            np.where(high_vol, t_bull_hv, t_bull_lv),
            np.where(
                is_bear,
                np.where(high_vol, t_bear_hv, t_bear_lv),
                np.where(high_vol, t_flat_hv, t_flat_lv),
            ),
        )

        # Non-trending side
        nt_scale = np.where(high_vol, ps[CHOPPY], ps[QUIET_MR_RANGE])

        blended = p_trend * t_scale + (1.0 - p_trend) * nt_scale
        decay = 1.0 - (1.0 - self.config.cp_position_decay) * cp_prob
        result["position_scale"] = np.round(blended * decay, 4)

        return result

    # ------------------------------------------------------------------
    # Direction overlay
    # ------------------------------------------------------------------

    def _compute_direction_series(self, close: pd.Series) -> pd.Series:
        """Non-hindsight direction from N-bar ROC. Returns series of BULL/BEAR/FLAT."""
        roc = close.pct_change(periods=self.config.direction_period).fillna(0.0)
        if self.config.adaptive_roc:
            thresh = roc.rolling(self.config.roc_std_window, min_periods=10).std().fillna(self.config.bull_roc_thresh) * 0.5
            thresh = thresh.clip(lower=0.001)
        else:
            thresh = self.config.bull_roc_thresh

        return pd.Series(
            np.where(roc > thresh, "BULL", np.where(roc < -thresh, "BEAR", "FLAT")),
            index=close.index,
        )

    def _compute_direction_scalar(self, close: pd.Series) -> str:
        """Direction for single-bar (last N bars of close series)."""
        p = self.config.direction_period
        if len(close) < p + 1:
            return "FLAT"
        roc_series = close.pct_change(periods=p).fillna(0.0)
        roc = roc_series.iloc[-1]

        if self.config.adaptive_roc:
            thresh = roc_series.iloc[-self.config.roc_std_window:].std() * 0.5
            if pd.isna(thresh):
                thresh = self.config.bull_roc_thresh
            thresh = max(0.001, thresh)
        else:
            thresh = self.config.bull_roc_thresh

        if roc > thresh:
            return "BULL"
        elif roc < -thresh:
            return "BEAR"
        return "FLAT"

    # ------------------------------------------------------------------
    # Regime construction
    # ------------------------------------------------------------------

    def _combine_regime(self, hmm: HMMState, vol: VolState, direction: str) -> str:
        return self._regime_from_flags(
            trending  = hmm.hmm_regime == "TRENDING",
            high_vol  = vol.vol_regime == "HIGH_VOL",
            direction = direction,
            vol_pct   = vol.vol_percentile,
        )

    def _regime_from_flags(
        self,
        trending: bool,
        high_vol: bool,
        direction: str,
        vol_pct: float = 50.0,
    ) -> str:
        if trending:
            base = VOLATILE_TREND_BULL if high_vol else CLEAN_TREND_BULL
            base_bear = VOLATILE_TREND_BEAR if high_vol else CLEAN_TREND_BEAR
            base_flat = VOLATILE_TREND_FLAT if high_vol else CLEAN_TREND_FLAT
            if direction == "BULL":
                return base
            if direction == "BEAR":
                return base_bear
            return base_flat
        else:
            if high_vol:
                return CHOPPY
            # Non-trending, low vol — check for squeeze
            if vol_pct < self.config.vol_squeeze_pct:
                return QUIET_MR_SQUEEZE
            return QUIET_MR_RANGE

    def _compute_adaptive_period(
        self,
        hilbert_period: float,
        hilbert_confidence: float,
        regime: str,
    ) -> int:
        if hilbert_confidence >= self.config.hilbert_high_threshold:
            scale = hilbert_period / self.config.bb_base
        else:
            scale = self.config.adaptive_period_scale.get(regime, 1.0)
        period = max(5, round(self.config.bb_base * max(0.5, min(scale, 2.0))))
        return int(period)

    def _apply_dwell(self, raw_regime: str) -> str:
        if self._current_regime is None:
            self._current_regime = raw_regime
            self._dwell_count = 1
            return raw_regime
        if raw_regime == self._current_regime:
            self._dwell_count += 1
            return raw_regime
        if self._dwell_count >= self.config.min_dwell_bars:
            self._current_regime = raw_regime
            self._dwell_count = 1
            return raw_regime
        self._dwell_count += 1
        return self._current_regime

    def _apply_dwell_series(self, regimes: np.ndarray) -> np.ndarray:
        filtered = regimes.copy()
        current = regimes[0]
        dwell = 1
        for i in range(1, len(regimes)):
            if regimes[i] == current:
                dwell += 1
                filtered[i] = current
            elif dwell >= self.config.min_dwell_bars:
                current = regimes[i]
                dwell = 1
                filtered[i] = current
            else:
                dwell += 1
                filtered[i] = current
        return filtered

    def _blend_position_scale(
        self,
        p_trending: float,
        vol_regime: str,
        cp_prob: float,
        direction: str = "FLAT",
    ) -> float:
        """Continuous blend between trending and non-trending position scales."""
        high_vol = vol_regime == "HIGH_VOL"

        # Trending side: pick scale by direction
        if direction == "BULL":
            t_scale = self.config.position_scale[
                VOLATILE_TREND_BULL if high_vol else CLEAN_TREND_BULL
            ]
        elif direction == "BEAR":
            t_scale = self.config.position_scale[
                VOLATILE_TREND_BEAR if high_vol else CLEAN_TREND_BEAR
            ]
        else:
            t_scale = self.config.position_scale[
                VOLATILE_TREND_FLAT if high_vol else CLEAN_TREND_FLAT
            ]

        # Non-trending side
        nt_scale = self.config.position_scale[
            CHOPPY if high_vol else QUIET_MR_RANGE
        ]

        blended = p_trending * t_scale + (1.0 - p_trending) * nt_scale
        decay   = 1.0 - (1.0 - self.config.cp_position_decay) * cp_prob
        return round(blended * decay, 4)
