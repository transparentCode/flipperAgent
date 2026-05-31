"""
Regime Orchestrator
===================
Top-level coordinator for the 4-layer regime detection pipeline.

Layers run in order:
  1. BCPD ChangeDetector    — structural breaks
  2. HMMClassifier          — trending / non-trending
  3. VolOverlay             — low / high volatility
  4. HilbertCycle           — adaptive period / confidence

BCPD feeds back into HMM: a confirmed changepoint triggers force_retrain().

Usage
-----
    orch = RegimeOrchestrator.create("BTCUSDT", "1h")
    features = orch.analyze(df)
    df_out   = orch.analyze_series(df)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import pandas as pd

from app.regime.aggregation.rule_based import AggregatorConfig, FeatureAggregator
from app.regime.change_detector import ChangeDetector, ChangeDetectorConfig
from app.regime.hmm_classifier import HMMClassifier, HMMConfig
from app.regime.kernels.hilbert_cycle import HilbertCycle
from app.regime.market_structure import (
    MarketStructure,
    MarketStructureConfig,
    infer_asset_type,
)
from app.regime.models import RegimeFeatures
from app.regime.mtf_fusion import MTFConfig, MTFFusion
from app.regime.vol_overlay import VolConfig, VolOverlay

logger = logging.getLogger("app.regime")

# ------------------------------------------------------------------
# Timeframe utilities
# ------------------------------------------------------------------

_TF_UNIT_HOURS = {"m": 1 / 60, "h": 1.0, "d": 24.0, "w": 168.0}
_REFERENCE_TF_HOURS = 1.0  # 1h is the reference timeframe


def timeframe_to_hours(tf: str) -> float:
    """Convert timeframe string to hours.

    Examples: '1h' -> 1.0, '15m' -> 0.25, '4h' -> 4.0, '1d' -> 24.0, '30m' -> 0.5
    """
    m = re.fullmatch(r"(\d+)([mhdw])", tf.strip().lower())
    if not m:
        raise ValueError(f"Unrecognised timeframe format: {tf!r}")
    value, unit = int(m.group(1)), m.group(2)
    return value * _TF_UNIT_HOURS[unit]


class RegimeOrchestrator:
    """
    Stateless regime detection pipeline for bar-close execution.

    Designed for 1H+ bars — no threading, no internal caching.
    Redis handles caching at the infrastructure level.
    """

    def __init__(
        self,
        change_detector: ChangeDetector,
        hmm_classifier: HMMClassifier,
        vol_overlay: VolOverlay,
        hilbert: HilbertCycle,
        aggregator: FeatureAggregator,
        asset: Optional[str] = None,
    ):
        self.change_detector = change_detector
        self.hmm_classifier = hmm_classifier
        self.vol_overlay = vol_overlay
        self.hilbert = hilbert
        self.aggregator = aggregator
        self.asset = asset

    @classmethod
    def create(
        cls,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        **overrides,
    ) -> "RegimeOrchestrator":
        """
        Factory method: load config from regime.yaml and construct all layers.

        Parameters
        ----------
        asset     : e.g. "BTCUSDT"
        timeframe : e.g. "1h"
        **overrides : runtime param overrides (highest priority)
        """
        # 1. Single-pass YAML load
        try:
            from app.utils.ConfigLoader import ConfigLoader
            raw = ConfigLoader.load("app/regime/config/regime.yaml")
        except Exception:
            raw = {}

        defaults = raw.get("defaults", {})
        asset_cfg = raw.get("assets", {}).get(asset or "", {}).get(timeframe or "", {})
        using_defaults = not asset_cfg  # empty dict or missing -> using defaults

        def _get(key: str, default: Any = None) -> Any:
            """Priority: overrides > asset_cfg > defaults > hardcoded default"""
            return overrides.pop(key, asset_cfg.get(key, defaults.get(key, default)))

        # 2. Market structure preprocessing
        ms_asset_type = _get("market_structure_asset_type", None)
        ms_gap_attenuation = float(_get("market_structure_gap_attenuation", 0.3))
        ms_gap_threshold_mult = float(_get("market_structure_gap_threshold_mult", 2.0))
        if not ms_asset_type and asset:
            ms_asset_type = infer_asset_type(asset)
        market_structure = MarketStructure(MarketStructureConfig(
            asset_type=ms_asset_type or "crypto",
            gap_attenuation=ms_gap_attenuation,
            gap_threshold_mult=ms_gap_threshold_mult,
        ))
        logger.info(
            "MarketStructure: asset=%s -> type=%s",
            asset, market_structure.config.asset_type,
        )

        # 3. ChangeDetector relies on its own load method but we can pass overrides
        change_detector = ChangeDetector.create(
            asset, timeframe, market_structure=market_structure, **overrides
        )

        # 4. HMM Classifier Configure
        hmm_retrain_window = int(_get("hmm_retrain_window", 1000))
        vol_lookback = int(_get("vol_lookback", 168))
        min_dwell_bars = int(_get("min_dwell_bars", 5))

        # Scale bar-count defaults for timeframe (only when not using
        # asset-specific optimized params which are already calibrated)
        if using_defaults and timeframe:
            hmm_retrain_window, vol_lookback, min_dwell_bars = (
                cls._scale_defaults_for_timeframe(
                    timeframe, hmm_retrain_window, vol_lookback, min_dwell_bars,
                )
            )

        hmm_classifier = HMMClassifier(HMMConfig(
            retrain_window=hmm_retrain_window,
            min_train_bars=int(_get("hmm_min_train_bars", 200)),
            log_vol_lookback=int(_get("hmm_log_vol_lookback", 24)),
            hurst_lookback=int(_get("hurst_lookback", 100)),
            use_volume=bool(_get("hmm_use_volume", True)),
            hmm_n_states=int(_get("hmm_n_states", 0)),
            hmm_max_states=int(_get("hmm_max_states", 4)),
            hmm_covariance_type=str(_get("hmm_covariance_type", "full")),
            hmm_robust_scoring=bool(_get("hmm_robust_scoring", True)),
            hmm_student_df=float(_get("hmm_student_df", 5.0)),
            hmm_crisis_vol_mult=float(_get("hmm_crisis_vol_mult", 2.0)),
        ))

        # 5. Vol Overlay Configure
        vol_overlay = VolOverlay(VolConfig(
            lookback=vol_lookback,
            rank_window=int(_get("vol_rank_window", 336)),
            high_percentile=float(_get("vol_high_percentile", 70.0)),
            hysteresis_band=float(_get("vol_hysteresis_band", 2.0)),
        ))

        # 6. Hilbert Cycle Configure
        hilbert = HilbertCycle(
            min_period=int(_get("hilbert_min_period", 10)),
            max_period=int(_get("hilbert_max_period", 40)),
            stability_bars=int(_get("hilbert_stability_bars", 10)),
        )

        # 7. Feature Aggregator Configure
        agg_kwargs = {
            "bb_base": int(_get("agg_bb_base", 20)),
            "rsi_base": int(_get("agg_rsi_base", 14)),
            "direction_period": int(_get("agg_direction_period", 20)),
            "bull_roc_thresh": float(_get("agg_bull_roc_thresh", 0.02)),
            "adaptive_roc": bool(_get("agg_adaptive_roc", True)),
            "vol_squeeze_pct": float(_get("agg_vol_squeeze_pct", 30.0)),
            "roc_std_window": int(_get("roc_std_window", 100)),
            "cp_position_decay": float(_get("agg_cp_position_decay", 0.5)),
            "min_dwell_bars": min_dwell_bars,
        }
        # Optional dictionary overrides
        for d_key in ["position_scale", "atr_multiplier", "holding_period"]:
            val = _get(d_key, None)
            if val is not None and isinstance(val, dict):
                agg_kwargs[d_key] = val

        aggregator = FeatureAggregator(AggregatorConfig(**agg_kwargs))

        return cls(change_detector, hmm_classifier, vol_overlay, hilbert, aggregator, asset)

    @staticmethod
    def _scale_defaults_for_timeframe(
        timeframe: str,
        hmm_retrain_window: int,
        vol_lookback: int,
        min_dwell_bars: int,
    ) -> tuple[int, int, int]:
        """Scale bar-count parameters relative to the 1h reference timeframe.

        At 1h (reference): params unchanged.
        At 15m: 4x more bars per unit time -> multiply by 4.
        At 4h: 4x fewer bars per unit time -> divide by 4.
        """
        bar_hours = timeframe_to_hours(timeframe)
        scale = _REFERENCE_TF_HOURS / bar_hours  # >1 for sub-hour, <1 for multi-hour

        if scale == 1.0:
            return hmm_retrain_window, vol_lookback, min_dwell_bars

        scaled = (
            max(1, int(round(hmm_retrain_window * scale))),
            max(1, int(round(vol_lookback * scale))),
            max(1, int(round(min_dwell_bars * scale))),
        )
        logger.info(
            "Timeframe %s: scaled defaults by %.2fx — "
            "hmm_retrain_window=%d, vol_lookback=%d, min_dwell_bars=%d",
            timeframe, scale, *scaled,
        )
        return scaled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, df: pd.DataFrame) -> RegimeFeatures:
        """Run all 4 layers and return RegimeFeatures for the last bar."""
        return self._run_layers(df)

    def analyze_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Run all 4 layers over the full series.

        BCPD→HMM feedback is applied: changepoint signals trigger HMM
        retraining within the series, matching live analyze() behavior.

        Returns a DataFrame with columns:
            regime, p_trending, vol_percentile, changepoint_prob,
            adaptive_period, position_scale.
        """
        if self.change_detector.config.multichannel:
            cp_df = self.change_detector.detect_series_multichannel(df)
        else:
            cp_df = self.change_detector.detect_series(df)

        # Pass BCPD signals to HMM for mid-segment retraining
        bcpd_signals = cp_df["bcpd_signal"].values if "bcpd_signal" in cp_df.columns else None
        hmm_df = self.hmm_classifier.classify_series_with_bcpd(df, bcpd_signals)

        vol_df = self.vol_overlay.compute_series(df)
        periods, confidences = self.hilbert.calculate_series(df["close"].values)
        return self.aggregator.aggregate_series(
            hmm_df, vol_df, cp_df, periods, confidences, close=df["close"]
        )

    def analyze_series_mtf(
        self,
        df_primary: pd.DataFrame,
        df_higher: pd.DataFrame,
        higher_timeframe: str = "4h",
        mtf_config: Optional[MTFConfig] = None,
    ) -> pd.DataFrame:
        """
        Run regime on both TFs and fuse.

        Creates a second orchestrator for the higher TF (using
        _scale_defaults_for_timeframe), runs analyze_series on both,
        then calls MTFFusion.fuse_series().

        Parameters
        ----------
        df_primary : Primary TF data (e.g., 1h OHLCV)
        df_higher  : Higher TF data (e.g., 4h OHLCV)
        higher_timeframe : Higher TF label (e.g., "4h")
        mtf_config : Optional MTFConfig override. If None, builds from
                     the orchestrator's config source with defaults.
        """
        # Run primary TF through this orchestrator
        primary_result = self.analyze_series(df_primary)

        # Create a second orchestrator for the higher TF
        higher_orch = RegimeOrchestrator.create(
            asset=self.asset,
            timeframe=higher_timeframe,
        )
        higher_result = higher_orch.analyze_series(df_higher)

        # Build MTF config
        if mtf_config is None:
            mtf_config = MTFConfig(higher_tf=higher_timeframe)

        fusion = MTFFusion(mtf_config)
        return fusion.fuse_series(primary_result, higher_result)

    def reset_state(self) -> None:
        """Reset HMM model state (useful between backtesting folds)."""
        self.hmm_classifier.reset()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_layers(self, df: pd.DataFrame) -> RegimeFeatures:
        """Execute all 4 layers sequentially and aggregate."""
        # BCPD runs first — trigger HMM retrain BEFORE classify so current bar is fresh
        cp = self.change_detector.detect(df)
        if cp.change_point_prob > self.change_detector.config.signal_threshold:
            self.hmm_classifier.force_retrain()

        hmm = self.hmm_classifier.classify(df)
        vol = self.vol_overlay.compute(df)
        period, confidence = self.hilbert.calculate(df["close"].values)

        return self.aggregator.aggregate(hmm, vol, cp, period, confidence)
