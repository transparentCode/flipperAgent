"""
Structural Screener
====================
Computes raw structural metrics per (asset, timeframe) from OHLCV data.

Metrics computed:
  - **poc_stability**: Coefficient of variation of rolling volume POC.
    Lower = more stable volume structure = better for SR zones.
  - **wick_body_ratio**: Median ratio of candle wick range to body range.
    Lower = cleaner price action = zones hold better.
  - **quick_survival**: Zone survival rate from a short pipeline audit.
    Higher = zones naturally survive longer on this asset.

All metric definitions and parameters are driven by the ``sr.qualification``
section of sr.yaml — no hardcoded thresholds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("app.sr.qualification")


@dataclass(frozen=True)
class StructuralMetrics:
    """Raw structural metrics for a single (asset, timeframe)."""

    asset: str
    timeframe: str
    poc_stability: Optional[float] = None
    wick_body_ratio: Optional[float] = None
    quick_survival: Optional[float] = None
    bar_count: int = 0
    errors: Dict[str, str] = field(default_factory=dict)


class StructuralScreener:
    """Compute structural metrics for universe assets.

    Parameters
    ----------
    config : dict
        The ``sr.qualification`` section from sr.yaml.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._metrics_config = config.get("metrics", {})
        self._screening_lookback = config.get("screening_lookback_bars", 2000)

    def screen(
        self,
        df: pd.DataFrame,
        asset: str,
        timeframe: str,
        sr_config: Optional[Any] = None,
    ) -> StructuralMetrics:
        """Compute all enabled structural metrics for one (asset, timeframe).

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
        asset : str
            Asset symbol, e.g. ``"BTCUSDT"``.
        timeframe : str
            Timeframe string, e.g. ``"1h"``.
        sr_config : optional
            Resolved SR config for pipeline-based metrics (quick_survival).
            If None, quick_survival is skipped.
        """
        # Trim to screening lookback
        df_trimmed = df.tail(self._screening_lookback).copy()
        bar_count = len(df_trimmed)

        errors: Dict[str, str] = {}
        poc_stability = None
        wick_body = None
        quick_surv = None

        # POC stability
        poc_cfg = self._metrics_config.get("poc_stability", {})
        if poc_cfg.get("enabled", False) and bar_count > 0:
            try:
                poc_stability = self._compute_poc_stability(
                    df_trimmed,
                    rolling_window=poc_cfg.get("rolling_window", 100),
                )
            except Exception as e:
                errors["poc_stability"] = str(e)
                logger.warning("poc_stability failed for %s %s: %s", asset, timeframe, e)

        # Wick-to-body ratio
        wb_cfg = self._metrics_config.get("wick_body_ratio", {})
        if wb_cfg.get("enabled", False) and bar_count > 0:
            try:
                wick_body = self._compute_wick_body_ratio(
                    df_trimmed,
                    lookback_bars=wb_cfg.get("lookback_bars", 1000),
                )
            except Exception as e:
                errors["wick_body_ratio"] = str(e)
                logger.warning("wick_body_ratio failed for %s %s: %s", asset, timeframe, e)

        # Quick survival
        qs_cfg = self._metrics_config.get("quick_survival", {})
        if qs_cfg.get("enabled", False) and sr_config is not None and bar_count > 0:
            try:
                quick_surv = self._compute_quick_survival(
                    df_trimmed,
                    sr_config=sr_config,
                    asset=asset,
                    timeframe=timeframe,
                    audit_bars=qs_cfg.get("audit_bars", 500),
                )
            except Exception as e:
                errors["quick_survival"] = str(e)
                logger.warning("quick_survival failed for %s %s: %s", asset, timeframe, e)

        return StructuralMetrics(
            asset=asset,
            timeframe=timeframe,
            poc_stability=poc_stability,
            wick_body_ratio=wick_body,
            quick_survival=quick_surv,
            bar_count=bar_count,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Metric implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_poc_stability(df: pd.DataFrame, rolling_window: int) -> float:
        """Coefficient of variation of rolling volume-weighted POC price.

        For each rolling window, computes the volume-weighted average price
        (VWAP proxy for POC), then returns std(poc_series) / mean(poc_series).

        Returns
        -------
        float
            CV of rolling POC. Lower = more stable volume structure.
        """
        if len(df) < rolling_window:
            rolling_window = max(10, len(df) // 4)

        typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
        volume = df["volume"].replace(0, np.nan).ffill().fillna(1.0)

        # Rolling VWAP as POC proxy
        vw = typical_price * volume
        rolling_vw_sum = vw.rolling(window=rolling_window, min_periods=rolling_window // 2).sum()
        rolling_vol_sum = volume.rolling(window=rolling_window, min_periods=rolling_window // 2).sum()
        poc_series = rolling_vw_sum / rolling_vol_sum.replace(0, np.nan)
        poc_series = poc_series.dropna()

        if len(poc_series) < 2:
            return 0.0

        mean_poc = poc_series.mean()
        if mean_poc == 0:
            return 0.0

        return float(poc_series.std() / mean_poc)

    @staticmethod
    def _compute_wick_body_ratio(df: pd.DataFrame, lookback_bars: int) -> float:
        """Median wick-to-body ratio over recent bars.

        wick_range = (high - low) - abs(open - close)
        body_range = abs(open - close)
        ratio = wick_range / body_range  (capped at 10 per bar to avoid division noise)

        Returns
        -------
        float
            Median ratio. Lower = cleaner candles.
        """
        recent = df.tail(lookback_bars)
        body = (recent["close"] - recent["open"]).abs()
        full_range = recent["high"] - recent["low"]
        wick = full_range - body

        # Avoid division by zero — use a small floor on body
        body_safe = body.clip(lower=max(full_range.median() * 0.001, 1e-10))
        ratios = (wick / body_safe).clip(upper=10.0)

        return float(ratios.median())

    @staticmethod
    def _compute_quick_survival(
        df: pd.DataFrame,
        sr_config: Any,
        asset: str,
        timeframe: str,
        audit_bars: int,
    ) -> float:
        """Run a short pipeline audit and return zone survival rate.

        Uses the last ``audit_bars`` of data with the resolved SR config.
        """
        from app.sr.optimization.multi_bar_runner import MultiBarRunner
        from app.sr.pipeline import SRv2Pipeline

        pipeline = SRv2Pipeline(
            config=sr_config,
            regime_gate=None,
            asset=asset,
            timeframe=timeframe,
        )
        runner = MultiBarRunner(pipeline)

        start_bar = max(0, len(df) - audit_bars)
        result = runner.run(df, start_bar=start_bar)

        if result.total_zones_created == 0:
            return 0.0
        return min(1.0, result.zones_reached_active / result.total_zones_created)
