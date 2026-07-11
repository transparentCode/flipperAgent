"""Map latent HMM states onto RegimeProbV1 semantic state labels."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

SEMANTIC_STATES: tuple[str, ...] = (
    "trend",
    "range",
    "chop",
    "breakout",
    "vol_shock",
    "transition",
)

_PRIORITY = {
    "transition": 5,
    "vol_shock": 4,
    "breakout": 3,
    "trend": 2,
    "range": 1,
    "chop": 0,
}


@dataclass(frozen=True)
class SemanticMappingResult:
    """Per-fit semantic mapping metadata for a latent-state model."""

    state_to_label: dict[int, str]
    state_scores: dict[int, dict[str, float]]
    state_feature_means: dict[int, dict[str, float]]


def map_latent_states(
    feature_frame: pd.DataFrame,
    posteriors: np.ndarray,
    *,
    self_transition_prob: pd.Series | None = None,
) -> SemanticMappingResult:
    """Map each latent state onto the most plausible semantic label."""
    state_to_label: dict[int, str] = {}
    state_scores: dict[int, dict[str, float]] = {}
    state_feature_means: dict[int, dict[str, float]] = {}
    for state_idx in range(posteriors.shape[1]):
        weights = np.asarray(posteriors[:, state_idx], dtype=float)
        weights = np.clip(weights, 0.0, None)
        means = _feature_means(
            feature_frame,
            weights,
            self_transition_prob=self_transition_prob,
        )
        scores = _semantic_scores(means)
        best = max(
            scores.items(),
            key=lambda item: (float(item[1]), _PRIORITY[item[0]]),
        )[0]
        state_to_label[state_idx] = best
        state_scores[state_idx] = scores
        state_feature_means[state_idx] = means
    return SemanticMappingResult(
        state_to_label=state_to_label,
        state_scores=state_scores,
        state_feature_means=state_feature_means,
    )


def _feature_means(
    feature_frame: pd.DataFrame,
    weights: np.ndarray,
    *,
    self_transition_prob: pd.Series | None,
) -> dict[str, float]:
    total = float(weights.sum())
    if total <= 0.0:
        return {
            "trend_strength": 0.0,
            "trend_persistence": 0.0,
            "trend_confidence": 0.0,
            "volatility_percentile": 0.5,
            "compression_score": 0.0,
            "shock_risk": 0.0,
            "mean_reversion_score": 0.0,
            "range_quality": 0.0,
            "chop_risk": 0.0,
            "raw_chop_risk": 0.0,
            "structural_break_risk": 0.0,
            "breakout_quality": 0.0,
            "pre_breakout_setup_score": 0.0,
            "displacement_breakout_score": 0.0,
            "false_breakout_risk": 0.0,
            "confidence": 0.0,
            "uncertainty": 0.0,
            "changepoint_prob": 0.0,
            "cp_recent_max": 0.0,
            "transition_risk_raw": 0.0,
            "hurst": 0.5,
            "volume_confirmation": 0.0,
            "liquidity_stress": 0.0,
            "self_transition_prob": 0.5,
        }
    means = {
        "trend_strength": _weighted_series_mean(feature_frame, "trend_strength", weights),
        "trend_persistence": _weighted_series_mean(feature_frame, "trend_persistence", weights),
        "trend_confidence": _weighted_series_mean(feature_frame, "trend_confidence", weights),
        "volatility_percentile": _weighted_series_mean(
            feature_frame,
            "volatility_percentile",
            weights,
            scale=0.01,
            lower=0.0,
            upper=1.0,
        ),
        "compression_score": _weighted_series_mean(feature_frame, "compression_score", weights),
        "shock_risk": _weighted_series_mean(feature_frame, "shock_risk", weights),
        "mean_reversion_score": _weighted_series_mean(feature_frame, "mean_reversion_score", weights),
        "range_quality": _weighted_series_mean(feature_frame, "range_quality", weights),
        "chop_risk": _weighted_series_mean(feature_frame, "chop_risk", weights),
        "raw_chop_risk": _weighted_series_mean(feature_frame, "raw_chop_risk", weights),
        "structural_break_risk": _weighted_series_mean(feature_frame, "structural_break_risk", weights),
        "breakout_quality": _weighted_series_mean(feature_frame, "breakout_quality", weights),
        "pre_breakout_setup_score": _weighted_series_mean(feature_frame, "pre_breakout_setup_score", weights),
        "displacement_breakout_score": _weighted_series_mean(
            feature_frame,
            "displacement_breakout_score",
            weights,
        ),
        "false_breakout_risk": _weighted_series_mean(feature_frame, "false_breakout_risk", weights),
        "confidence": _weighted_series_mean(feature_frame, "confidence", weights),
        "uncertainty": _weighted_series_mean(feature_frame, "uncertainty", weights),
        "changepoint_prob": _weighted_series_mean(feature_frame, "changepoint_prob", weights),
        "cp_recent_max": _weighted_series_mean(feature_frame, "cp_recent_max", weights),
        "transition_risk_raw": _weighted_series_mean(feature_frame, "transition_risk_raw", weights),
        "hurst": _weighted_series_mean(feature_frame, "hurst", weights),
        "volume_confirmation": _weighted_series_mean(feature_frame, "volume_confirmation", weights),
        "liquidity_stress": _weighted_series_mean(feature_frame, "liquidity_stress", weights),
        "self_transition_prob": _weighted_optional_mean(self_transition_prob, weights, feature_frame.index),
    }
    return means


def _semantic_scores(means: dict[str, float]) -> dict[str, float]:
    scores = {
        "trend": (
            0.30 * means["trend_strength"]
            + 0.25 * means["trend_persistence"]
            + 0.15 * means["trend_confidence"]
            + 0.10 * means["confidence"]
            + 0.10 * means["hurst"]
            + 0.10 * (1.0 - means["chop_risk"])
        ),
        "range": (
            0.35 * means["range_quality"]
            + 0.20 * means["mean_reversion_score"]
            + 0.15 * means["compression_score"]
            + 0.15 * (1.0 - means["shock_risk"])
            + 0.15 * (1.0 - means["uncertainty"])
        ),
        "chop": (
            0.40 * means["chop_risk"]
            + 0.20 * means["raw_chop_risk"]
            + 0.15 * means["uncertainty"]
            + 0.15 * means["compression_score"]
            + 0.10 * (1.0 - means["trend_strength"])
        ),
        "breakout": (
            0.35 * means["breakout_quality"]
            + 0.20 * means["pre_breakout_setup_score"]
            + 0.15 * means["displacement_breakout_score"]
            + 0.10 * means["volume_confirmation"]
            + 0.10 * means["trend_strength"]
            + 0.10 * means["structural_break_risk"]
            - 0.10 * means["false_breakout_risk"]
        ),
        "vol_shock": (
            0.40 * means["shock_risk"]
            + 0.25 * means["volatility_percentile"]
            + 0.15 * means["uncertainty"]
            + 0.10 * means["liquidity_stress"]
            + 0.10 * means["structural_break_risk"]
        ),
        "transition": (
            0.30 * means["changepoint_prob"]
            + 0.20 * means["transition_risk_raw"]
            + 0.15 * means["cp_recent_max"]
            + 0.15 * means["structural_break_risk"]
            + 0.10 * means["uncertainty"]
            + 0.10 * (1.0 - means["self_transition_prob"])
        ),
    }
    return {name: float(np.clip(score, 0.0, 1.0)) for name, score in scores.items()}


def _weighted_series_mean(
    feature_frame: pd.DataFrame,
    column: str,
    weights: np.ndarray,
    *,
    scale: float = 1.0,
    lower: float = 0.0,
    upper: float = 1.0,
) -> float:
    if column not in feature_frame.columns:
        return 0.0
    series = pd.to_numeric(feature_frame[column], errors="coerce")
    values = np.clip(np.nan_to_num(series.to_numpy(dtype=float) * scale, nan=0.0), lower, upper)
    total = float(weights.sum())
    if total <= 0.0:
        return 0.0
    return float(np.average(values, weights=weights))


def _weighted_optional_mean(
    series: pd.Series | None,
    weights: np.ndarray,
    index: pd.Index,
) -> float:
    if series is None:
        return 0.5
    aligned = pd.to_numeric(series.reindex(index), errors="coerce").fillna(0.5)
    total = float(weights.sum())
    if total <= 0.0:
        return 0.5
    values = np.clip(aligned.to_numpy(dtype=float), 0.0, 1.0)
    return float(np.average(values, weights=weights))


__all__ = [
    "SEMANTIC_STATES",
    "SemanticMappingResult",
    "map_latent_states",
]
