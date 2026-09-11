"""Offline derivation of asset/timeframe behavior profiles."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from libs.common.timeframes import timeframe_to_seconds
from libs.models.regime_prob_v1.config import RegimeProbFeatureFrameConfig, RegimeProbLabelConfig
from libs.models.regime_prob_v1.contracts import AssetTimeframeProfile
from libs.models.regime_prob_v1.edge import build_regime_prob_edge_labels
from libs.models.regime_prob_v1.feature_builder import build_regime_prob_feature_frame
from libs.models.regime_prob_v1.profile.asset_tf_profile import AssetTimeframeProfileReport
from libs.models.regime_v2.data_quality import prepare_ohlcv


def derive_asset_timeframe_profile(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    external_context_frames: dict[str, pd.DataFrame] | None = None,
) -> AssetTimeframeProfile:
    """Derive a coarse behavior profile for one asset/timeframe pair."""
    return derive_asset_timeframe_profile_report(
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        external_context_frames=external_context_frames,
    ).profile


def derive_asset_timeframe_profile_report(
    ohlcv: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    external_context_frames: dict[str, pd.DataFrame] | None = None,
) -> AssetTimeframeProfileReport:
    """Derive a profile plus the metrics that support it."""
    prepared = prepare_ohlcv(ohlcv, ("open", "high", "low", "close", "volume"))
    feature_config = replace(
        RegimeProbFeatureFrameConfig(),
        include_external_context=bool(external_context_frames),
    )
    feature_frame = build_regime_prob_feature_frame(
        prepared,
        asset=asset,
        timeframe=timeframe,
        config=feature_config,
        external_context_frames=external_context_frames,
    )
    labels = build_regime_prob_edge_labels(
        feature_frame,
        prepared,
        timeframe=timeframe,
        config=RegimeProbLabelConfig(horizons=(3,)),
    )
    metrics = _compute_profile_metrics(
        prepared,
        feature_frame=feature_frame,
        label_frame=labels.frame,
        timeframe=timeframe,
    )
    profile = AssetTimeframeProfile(
        asset=asset.upper(),
        timeframe=str(timeframe),
        liquidity_tier=_tier(
            metrics["median_notional_volume"],
            thresholds=(2.5e7, 1.0e8, 5.0e8),
        ),
        volatility_tier=_tier(
            metrics["realized_vol_annualized"],
            thresholds=(0.60, 1.00, 1.60),
        ),
        trend_persistence_tier=_tier(
            metrics["trend_persistence_mean"],
            thresholds=(0.25, 0.45, 0.65),
        ),
        mean_reversion_tier=_tier(
            metrics["mean_reversion_score_mean"],
            thresholds=(0.25, 0.45, 0.65),
        ),
        breakout_followthrough_tier=_tier(
            metrics["breakout_positive_rate_h3"],
            thresholds=(0.40, 0.52, 0.62),
        ),
        false_breakout_tier=_tier(
            metrics["false_breakout_risk_mean"],
            thresholds=(0.25, 0.45, 0.65),
        ),
        btc_beta_tier=_tier(
            metrics["asset_beta_btc_abs_mean"],
            thresholds=(0.60, 0.90, 1.20),
        ),
        eth_beta_tier=_tier(
            metrics["asset_beta_eth_abs_mean"],
            thresholds=(0.60, 0.90, 1.20),
        ),
        total2_beta_tier=_tier(
            metrics["asset_beta_total2_abs_mean"],
            thresholds=(0.60, 0.90, 1.20),
        ),
        total3_beta_tier=_tier(
            metrics["asset_beta_total3_abs_mean"],
            thresholds=(0.60, 0.90, 1.20),
        ),
        funding_sensitivity_tier="unavailable",
        oi_sensitivity_tier="unavailable",
        recommended_profile=_recommended_profile(metrics),
    )
    diagnostics = {
        "status": "ok",
        "rows": int(len(prepared)),
        "feature_rows": int(len(feature_frame)),
        "breakout_support_h3": int(metrics["breakout_support_h3"]),
        "external_context_enabled": bool(external_context_frames),
        "external_sources": sorted((external_context_frames or {}).keys()),
    }
    return AssetTimeframeProfileReport(
        profile=profile,
        metrics=metrics,
        diagnostics=diagnostics,
    )


def _compute_profile_metrics(
    prepared: pd.DataFrame,
    *,
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    timeframe: str,
) -> dict[str, Any]:
    close = prepared["close"].astype(float)
    volume = prepared["volume"].astype(float)
    log_return = np.log(close.replace(0.0, np.nan)).diff()
    seconds = max(timeframe_to_seconds(timeframe), 1)
    bars_per_year = (365.0 * 24.0 * 3600.0) / float(seconds)
    breakout_positive = pd.to_numeric(label_frame.get("breakout_edge_positive_h3"), errors="coerce")
    breakout_edge = pd.to_numeric(label_frame.get("breakout_edge_return_h3"), errors="coerce")
    breakout_side = pd.to_numeric(label_frame.get("breakout_side"), errors="coerce").fillna(0.0)
    breakout_mask = breakout_side != 0.0
    external_available = feature_frame.get("external_context_available")
    external_coverage = (
        external_available.fillna(False).astype(float).mean()
        if external_available is not None else 0.0
    )
    return {
        "median_notional_volume": float((close * volume).median()),
        "realized_vol_annualized": float(log_return.std(ddof=0) * np.sqrt(bars_per_year)) if len(log_return.dropna()) else 0.0,
        "trend_persistence_mean": _series_mean(feature_frame.get("trend_persistence")),
        "mean_reversion_score_mean": _series_mean(feature_frame.get("mean_reversion_score")),
        "breakout_quality_mean": _series_mean(feature_frame.get("breakout_quality")),
        "false_breakout_risk_mean": _series_mean(feature_frame.get("false_breakout_risk")),
        "shock_risk_mean": _series_mean(feature_frame.get("shock_risk")),
        "liquidity_stress_mean": _series_mean(feature_frame.get("liquidity_stress")),
        "breakout_support_h3": int(breakout_mask.sum()),
        "breakout_positive_rate_h3": float(breakout_positive.loc[breakout_mask].mean()) if breakout_mask.any() else 0.0,
        "breakout_mean_edge_h3": float(breakout_edge.loc[breakout_mask].mean()) if breakout_mask.any() else 0.0,
        "asset_beta_btc_abs_mean": _series_mean(feature_frame.get("asset_beta_btc"), absolute=True),
        "asset_beta_eth_abs_mean": _series_mean(feature_frame.get("asset_beta_eth"), absolute=True),
        "asset_beta_total2_abs_mean": _series_mean(feature_frame.get("asset_beta_total2"), absolute=True),
        "asset_beta_total3_abs_mean": _series_mean(feature_frame.get("asset_beta_total3"), absolute=True),
        "asset_return_corr_btc_abs_mean": _series_mean(feature_frame.get("asset_return_corr_btc"), absolute=True),
        "asset_return_corr_eth_abs_mean": _series_mean(feature_frame.get("asset_return_corr_eth"), absolute=True),
        "asset_return_corr_total2_abs_mean": _series_mean(feature_frame.get("asset_return_corr_total2"), absolute=True),
        "asset_return_corr_total3_abs_mean": _series_mean(feature_frame.get("asset_return_corr_total3"), absolute=True),
        "external_context_coverage": float(external_coverage),
        "market_alignment_score_mean": _series_mean(feature_frame.get("market_alignment_score")),
    }


def _recommended_profile(metrics: dict[str, Any]) -> str:
    if metrics["liquidity_stress_mean"] >= 0.55 or metrics["shock_risk_mean"] >= 0.55:
        return "risk_off"
    if metrics["trend_persistence_mean"] >= 0.60 and metrics["breakout_positive_rate_h3"] >= 0.55:
        return "breakout"
    if metrics["trend_persistence_mean"] >= 0.60:
        return "trend"
    if metrics["mean_reversion_score_mean"] >= 0.55 and metrics["trend_persistence_mean"] < 0.45:
        return "mean_reversion"
    return "balanced"


def _tier(value: float, *, thresholds: tuple[float, float, float]) -> str:
    if value != value:
        return "unavailable"
    if value < thresholds[0]:
        return "low"
    if value < thresholds[1]:
        return "medium"
    if value < thresholds[2]:
        return "high"
    return "extreme"


def _series_mean(values: pd.Series | None, *, absolute: bool = False) -> float:
    if values is None:
        return 0.0
    series = pd.to_numeric(values, errors="coerce")
    if absolute:
        series = series.abs()
    if series.notna().sum() == 0:
        return 0.0
    return float(series.mean())


__all__ = [
    "derive_asset_timeframe_profile",
    "derive_asset_timeframe_profile_report",
]
