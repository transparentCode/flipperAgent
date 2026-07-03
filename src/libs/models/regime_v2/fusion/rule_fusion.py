"""Transparent rule fusion for RegimeV2 phase 1."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import FusionConfig
from libs.models.regime_v2.contracts import RegimeEvidence
from libs.models.regime_v2.features.utils import clip01


def build_evidence_frame(
    features: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    config: FusionConfig,
    warmup_complete: bool = True,
) -> pd.DataFrame:
    """Fuse feature columns into the RegimeEvidence dataframe schema."""
    out = pd.DataFrame(index=features.index)
    out["asset"] = asset
    out["timeframe"] = timeframe

    out["trend_direction"] = features.get("trend_direction", pd.Series("neutral", index=features.index))
    out["trend_strength"] = _col(features, "trend_strength")
    out["trend_persistence"] = _col(features, "trend_persistence")
    out["trend_confidence"] = _col(features, "trend_confidence")

    out["volatility_percentile"] = _col(features, "volatility_percentile", 50.0).clip(0.0, 100.0)
    out["volatility_state"] = features.get("volatility_state", pd.Series("normal", index=features.index))
    out["compression_score"] = _col(features, "compression_score")
    out["shock_risk"] = _col(features, "shock_risk")

    out["mean_reversion_score"] = _col(features, "mean_reversion_score")
    out["range_quality"] = _col(features, "range_quality")
    raw_chop_risk = _col(features, "chop_risk")
    trend_chop_discount = (0.50 * out["trend_strength"] * out["trend_persistence"]).clip(0.0, 0.45)
    out["chop_risk"] = (raw_chop_risk * (1.0 - trend_chop_discount)).clip(0.0, 1.0)
    out["raw_chop_risk"] = raw_chop_risk

    out["structural_break_risk"] = _col(features, "structural_break_risk")
    out["breakout_quality"] = _col(features, "breakout_quality")
    out["pre_breakout_setup_score"] = _col(features, "pre_breakout_setup_score")
    out["displacement_breakout_score"] = _col(features, "displacement_breakout_score")
    out["post_breakout_retest_score"] = _col(features, "post_breakout_retest_score")
    out["false_breakout_risk"] = _col(features, "false_breakout_risk")

    out["market_context_score"] = _col(features, "market_context_score", 0.0).clip(-1.0, 1.0)
    out["breadth_confirmation"] = _col(features, "breadth_confirmation", 0.0).clip(-1.0, 1.0)
    out["liquidity_stress"] = _col(features, "liquidity_stress")

    signal_strength = pd.concat(
        [
            out["trend_confidence"],
            out["breakout_quality"],
            out["mean_reversion_score"] * out["range_quality"],
            out["compression_score"],
        ],
        axis=1,
    ).max(axis=1)
    conflict = (
        (out["trend_strength"] * out["chop_risk"])
        + (out["breakout_quality"] * out["false_breakout_risk"])
        + out["shock_risk"] * 0.75
        + out["liquidity_stress"] * 0.50
    ).clip(0.0, 1.0)

    confidence = clip01(signal_strength * (1.0 - 0.55 * conflict))
    uncertainty = clip01(1.0 - confidence + 0.35 * conflict)
    if not warmup_complete:
        confidence = confidence * 0.25
        uncertainty = pd.Series(1.0, index=features.index)

    out["confidence"] = confidence.clip(lower=config.min_confidence if warmup_complete else 0.0)
    out["uncertainty"] = uncertainty.clip(0.0, 1.0)
    out["summary_label"] = _summary_labels(out, config, warmup_complete=warmup_complete)
    return out


def row_to_evidence(row: pd.Series, *, asset: str, timeframe: str) -> RegimeEvidence:
    """Convert one evidence dataframe row into a RegimeEvidence contract."""
    return RegimeEvidence(
        timestamp=row.name,
        asset=asset,
        timeframe=timeframe,
        trend_direction=str(row.get("trend_direction", "neutral")),
        trend_strength=float(row.get("trend_strength", 0.0)),
        trend_persistence=float(row.get("trend_persistence", 0.0)),
        trend_confidence=float(row.get("trend_confidence", 0.0)),
        volatility_percentile=float(row.get("volatility_percentile", 50.0)),
        volatility_state=str(row.get("volatility_state", "normal")),
        compression_score=float(row.get("compression_score", 0.0)),
        shock_risk=float(row.get("shock_risk", 0.0)),
        mean_reversion_score=float(row.get("mean_reversion_score", 0.0)),
        range_quality=float(row.get("range_quality", 0.0)),
        chop_risk=float(row.get("chop_risk", 0.0)),
        structural_break_risk=float(row.get("structural_break_risk", 0.0)),
        breakout_quality=float(row.get("breakout_quality", 0.0)),
        false_breakout_risk=float(row.get("false_breakout_risk", 0.0)),
        market_context_score=float(row.get("market_context_score", 0.0)),
        breadth_confirmation=float(row.get("breadth_confirmation", 0.0)),
        liquidity_stress=float(row.get("liquidity_stress", 0.0)),
        confidence=float(row.get("confidence", 0.0)),
        uncertainty=float(row.get("uncertainty", 1.0)),
        summary_label=str(row.get("summary_label", "unknown")),
        pre_breakout_setup_score=float(row.get("pre_breakout_setup_score", 0.0)),
        displacement_breakout_score=float(row.get("displacement_breakout_score", 0.0)),
        post_breakout_retest_score=float(row.get("post_breakout_retest_score", 0.0)),
    )


def _summary_labels(out: pd.DataFrame, config: FusionConfig, *, warmup_complete: bool) -> pd.Series:
    labels = pd.Series("neutral", index=out.index, dtype=object)
    if not warmup_complete:
        labels[:] = "warming_up"
        return labels

    shock = out["shock_risk"] >= config.shock_threshold
    transition = (out["structural_break_risk"] >= config.break_threshold) & (out["breakout_quality"] >= 0.45)
    trend = (out["trend_strength"] >= config.trend_threshold) & (out["chop_risk"] < 0.60)
    mr_context = (out["range_quality"] >= 0.30) | (out["compression_score"] >= 0.70)
    mr = (out["mean_reversion_score"] >= config.mr_threshold) & mr_context & (out["structural_break_risk"] < 0.60)
    compressed = out["compression_score"] >= 0.72
    choppy = out["chop_risk"] >= config.chop_threshold

    labels[choppy] = "choppy"
    labels[compressed] = "compressed_range"
    labels[mr] = "mean_reversion_range"
    labels[trend & (out["trend_direction"] == "bull")] = "bull_trend"
    labels[trend & (out["trend_direction"] == "bear")] = "bear_trend"
    labels[transition] = "breakout_transition"
    labels[shock] = "shock"
    return labels


def _col(df: pd.DataFrame, name: str, default: float = 0.0) -> pd.Series:
    if name not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce").fillna(default).astype(float)


__all__ = ["build_evidence_frame", "row_to_evidence"]
