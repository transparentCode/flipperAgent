"""Optional external-context feature builder for RegimeProbV1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.context.cross_asset_features import (
    build_cross_asset_feature_frame,
    compute_breakout_confirmation_flags,
)
from libs.models.regime_prob_v1.context.staleness import (
    align_external_series,
    neutral_context_frame,
    normalize_source_frames,
)
from libs.models.regime_v2.data_quality import prepare_ohlcv

_CORE_INDEX_SOURCES = ("BTC.D", "TOTAL2", "TOTAL3")
_OPTIONAL_LEADER_SOURCES = ("BTCUSDT", "ETHUSDT")


@dataclass(frozen=True)
class ExternalContextConfig:
    """Context-alignment and feature-window settings."""

    max_staleness_bars: int = 2
    correlation_window: int = 24
    beta_window: int = 24
    relative_strength_period: int = 24
    trend_window: int = 24
    momentum_window: int = 12
    zscore_window: int = 48


@dataclass(frozen=True)
class ExternalContextOutput:
    """Feature frame and diagnostics for optional external context."""

    frame: pd.DataFrame
    diagnostics: dict[str, Any]


def build_external_context_features(
    asset_frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    external_context_frames: Mapping[str, pd.DataFrame] | None = None,
    config: ExternalContextConfig | None = None,
    breakout_direction: pd.Series | None = None,
) -> ExternalContextOutput:
    """As-of align optional external data and derive neutral-safe features."""
    cfg = config or ExternalContextConfig()
    if asset_frame.empty:
        return ExternalContextOutput(
            frame=pd.DataFrame(index=asset_frame.index.copy()),
            diagnostics={"status": "empty_asset_frame"},
        )

    prepared = prepare_ohlcv(asset_frame, ("open", "high", "low", "close", "volume"))
    close = prepared["close"].astype(float)
    normalized = normalize_source_frames(external_context_frames)
    if not normalized:
        neutral = _neutral_feature_frame(close.index)
        return ExternalContextOutput(
            frame=neutral,
            diagnostics={"status": "no_external_context_frames", "sources": []},
        )

    aligned_sources: dict[str, pd.DataFrame] = {}
    for source in _CORE_INDEX_SOURCES + _OPTIONAL_LEADER_SOURCES:
        raw = normalized.get(source)
        if raw is None:
            continue
        aligned_sources[source] = align_external_series(
            close.index,
            raw,
            timeframe=timeframe,
            max_staleness_bars=cfg.max_staleness_bars,
        )

    feature_frame = _neutral_feature_frame(close.index)
    if aligned_sources:
        availability = _availability_frame(close.index, aligned_sources)
        for column in availability.columns:
            feature_frame[column] = availability[column]
        cross_asset = build_cross_asset_feature_frame(
            close,
            aligned_sources=aligned_sources,
            correlation_window=cfg.correlation_window,
            beta_window=cfg.beta_window,
            relative_strength_period=cfg.relative_strength_period,
            trend_window=cfg.trend_window,
            momentum_window=cfg.momentum_window,
            zscore_window=cfg.zscore_window,
        )
        for column in cross_asset.columns:
            feature_frame[column] = cross_asset[column]
        breakout_flags = compute_breakout_confirmation_flags(
            breakout_direction=breakout_direction,
            total3_trend=feature_frame.get("total3_trend"),
        )
        for column in breakout_flags.columns:
            feature_frame[column] = breakout_flags[column]
        unavailable = ~feature_frame["external_context_available"].fillna(False).astype(bool)
        for column in (
            "market_alignment_score",
            "alt_market_alignment",
            "btc_d_conflict_score",
            "total3_confirmation",
            "asset_breakout_without_market_confirmation",
            "market_breakout_without_asset_confirmation",
        ):
            if column in feature_frame.columns:
                feature_frame.loc[unavailable, column] = 0.0

    feature_frame = feature_frame.fillna(
        {
            "external_context_available": False,
            "external_context_coverage_ratio": 0.0,
            "btc_d_available": False,
            "total2_available": False,
            "total3_available": False,
            "btc_available": False,
            "eth_available": False,
        }
    )
    bool_columns = [column for column in feature_frame.columns if column.endswith("_available")]
    if "external_context_available" in feature_frame.columns:
        bool_columns.append("external_context_available")
    for column in dict.fromkeys(bool_columns):
        feature_frame[column] = feature_frame[column].fillna(False).astype(bool)

    numeric_columns = [column for column in feature_frame.columns if column not in bool_columns]
    for column in numeric_columns:
        feature_frame[column] = pd.to_numeric(feature_frame[column], errors="coerce")

    diagnostics = {
        "status": "ok" if aligned_sources else "no_usable_sources",
        "asset": asset,
        "timeframe": timeframe,
        "sources": sorted(aligned_sources.keys()),
        "available_rows": int(feature_frame["external_context_available"].sum()),
        "coverage_mean": float(feature_frame["external_context_coverage_ratio"].mean()),
    }
    return ExternalContextOutput(frame=feature_frame, diagnostics=diagnostics)


def _availability_frame(index: pd.Index, aligned_sources: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    out = neutral_context_frame(index)
    core_available_columns = []
    staleness_columns = []
    for source, alias in (
        ("BTC.D", "btc_d"),
        ("TOTAL2", "total2"),
        ("TOTAL3", "total3"),
        ("BTCUSDT", "btc"),
        ("ETHUSDT", "eth"),
    ):
        aligned = aligned_sources.get(source)
        if aligned is None:
            continue
        available_col = f"{alias}_available"
        out[available_col] = aligned["available"].reindex(index).fillna(False).astype(bool)
        staleness_col = f"{alias}_staleness_bars"
        out[staleness_col] = aligned["staleness_bars"].reindex(index)
        staleness_columns.append(staleness_col)
        if source in _CORE_INDEX_SOURCES:
            core_available_columns.append(available_col)

    if core_available_columns:
        coverage = out[core_available_columns].astype(float).mean(axis=1)
        out["external_context_coverage_ratio"] = coverage
        out["external_context_available"] = coverage >= 1.0
    if staleness_columns:
        out["external_context_staleness_bars"] = out[staleness_columns].min(axis=1)
        missing_all = out[[column for column in staleness_columns]].isna().all(axis=1)
        max_staleness = out[staleness_columns].max(axis=1)
        out.loc[missing_all, "external_context_staleness_bars"] = np.nan
        out.loc[~missing_all, "external_context_staleness_bars"] = max_staleness.loc[~missing_all]
    return out


def _neutral_feature_frame(index: pd.Index) -> pd.DataFrame:
    neutral = neutral_context_frame(index)
    neutral = neutral.assign(
        btc_d_staleness_bars=np.nan,
        total2_staleness_bars=np.nan,
        total3_staleness_bars=np.nan,
        btc_staleness_bars=np.nan,
        eth_staleness_bars=np.nan,
        asset_trend_context=0.0,
        btc_d_trend=0.0,
        btc_d_momentum=0.0,
        total2_trend=0.0,
        total3_trend=0.0,
        btcusdt_trend=0.0,
        ethusdt_trend=0.0,
        asset_return_corr_btc=0.0,
        asset_return_corr_eth=0.0,
        asset_return_corr_total2=0.0,
        asset_return_corr_total3=0.0,
        asset_beta_btc=0.0,
        asset_beta_eth=0.0,
        asset_beta_total2=0.0,
        asset_beta_total3=0.0,
        relative_strength_vs_btc=0.0,
        relative_strength_vs_eth=0.0,
        relative_strength_vs_total2=0.0,
        relative_strength_vs_total3=0.0,
        total3_confirmation=0.0,
        alt_market_alignment=0.0,
        market_alignment_score=0.0,
        asset_vs_total3_divergence=0.0,
        asset_vs_btc_divergence=0.0,
        btc_d_conflict_score=0.0,
        asset_breakout_without_market_confirmation=0.0,
        market_breakout_without_asset_confirmation=0.0,
    )
    return neutral


__all__ = [
    "ExternalContextConfig",
    "ExternalContextOutput",
    "build_external_context_features",
]
