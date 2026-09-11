"""Shared probability overlays for RegimeProbV1 runtime and optimization paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.moe import PLAYBOOKS, playbook_probability_column


@dataclass(frozen=True)
class ProbabilityOverlayConfig:
    """Default overlay settings shared by runtime and shadow optimization."""

    min_edge_probability: float = 0.35
    min_trend_state_prob: float = 0.45
    min_range_state_prob: float = 0.45
    min_breakout_state_prob: float = 0.40
    max_transition_state_prob: float = 0.55
    max_state_entropy: float = 0.80
    transition_risk_threshold: float = 0.55
    uncertainty_threshold: float = 0.75
    changepoint_prob_threshold: float = 0.55
    max_staleness_bars: int = 2
    btc_d_conflict_weight: float = 0.25
    total3_confirmation_weight: float = 0.25
    market_alignment_weight: float = 0.20
    beta_weight: float = 0.10
    context_staleness_penalty: float = 0.25


@dataclass(frozen=True)
class ProbabilityOverlayFrame:
    """Adjusted playbook probabilities plus state and gating diagnostics."""

    adjusted_probabilities: pd.DataFrame
    state_frame: pd.DataFrame
    transition_risk: pd.Series
    gate_active: pd.Series


def overlay_config_from_params(params: dict[str, Any]) -> ProbabilityOverlayConfig:
    """Map optimizer params onto the shared overlay configuration."""
    return ProbabilityOverlayConfig(
        min_edge_probability=float(params.get("min_edge_probability", ProbabilityOverlayConfig.min_edge_probability)),
        min_trend_state_prob=float(params.get("min_trend_state_prob", ProbabilityOverlayConfig.min_trend_state_prob)),
        min_range_state_prob=float(params.get("min_range_state_prob", ProbabilityOverlayConfig.min_range_state_prob)),
        min_breakout_state_prob=float(
            params.get("min_breakout_state_prob", ProbabilityOverlayConfig.min_breakout_state_prob)
        ),
        max_transition_state_prob=float(
            params.get("max_transition_state_prob", ProbabilityOverlayConfig.max_transition_state_prob)
        ),
        max_state_entropy=float(params.get("max_state_entropy", ProbabilityOverlayConfig.max_state_entropy)),
        transition_risk_threshold=float(
            params.get("transition_risk_threshold", ProbabilityOverlayConfig.transition_risk_threshold)
        ),
        uncertainty_threshold=float(params.get("uncertainty_threshold", ProbabilityOverlayConfig.uncertainty_threshold)),
        changepoint_prob_threshold=float(
            params.get("changepoint_prob_threshold", ProbabilityOverlayConfig.changepoint_prob_threshold)
        ),
        max_staleness_bars=int(params.get("max_staleness_bars", ProbabilityOverlayConfig.max_staleness_bars)),
        btc_d_conflict_weight=float(
            params.get("btc_d_conflict_weight", ProbabilityOverlayConfig.btc_d_conflict_weight)
        ),
        total3_confirmation_weight=float(
            params.get("total3_confirmation_weight", ProbabilityOverlayConfig.total3_confirmation_weight)
        ),
        market_alignment_weight=float(
            params.get("market_alignment_weight", ProbabilityOverlayConfig.market_alignment_weight)
        ),
        beta_weight=float(params.get("beta_weight", ProbabilityOverlayConfig.beta_weight)),
        context_staleness_penalty=float(
            params.get("context_staleness_penalty", ProbabilityOverlayConfig.context_staleness_penalty)
        ),
    )


def build_probability_overlay(
    feature_frame: pd.DataFrame,
    *,
    horizon: int,
    config: ProbabilityOverlayConfig | None = None,
    state_frame: pd.DataFrame | None = None,
    use_state_support: bool = True,
    use_transition_gate: bool = True,
    use_external_context: bool = True,
) -> ProbabilityOverlayFrame:
    """Build the shared shadow/runtime overlay used before MoE routing."""
    cfg = config or ProbabilityOverlayConfig()
    state_frame = state_frame.copy() if state_frame is not None else build_state_proxy_frame(feature_frame)
    adjusted = playbook_probability_frame(feature_frame, horizon=horizon)
    if use_state_support:
        adjusted = apply_state_support_overlay(adjusted, state_frame=state_frame, config=cfg)
    if use_external_context:
        adjusted = apply_external_context_overlay(feature_frame, edge_probabilities=adjusted, config=cfg)
    transition_risk = transition_risk_series(feature_frame, state_frame=state_frame)
    gate_active = pd.Series(True, index=feature_frame.index, dtype=bool)
    if use_transition_gate:
        adjusted, transition_risk, gate_active = apply_transition_overlay(
            feature_frame,
            edge_probabilities=adjusted,
            state_frame=state_frame,
            config=cfg,
        )
    return ProbabilityOverlayFrame(
        adjusted_probabilities=adjusted.fillna(0.0),
        state_frame=state_frame,
        transition_risk=transition_risk.astype(float),
        gate_active=gate_active.astype(bool),
    )


def build_state_proxy_frame(feature_frame: pd.DataFrame) -> pd.DataFrame:
    """Proxy state probabilities derived from deterministic RegimeV2 evidence.

    This is an interpretable shadow/research proxy, not a true HMM posterior or
    calibrated latent-state model.
    """
    trend = _clip01(
        _numeric_series(feature_frame.get("trend_strength"), feature_frame.index)
        * (0.5 + 0.5 * _numeric_series(feature_frame.get("trend_confidence"), feature_frame.index))
    )
    range_state = _clip01(
        _numeric_series(feature_frame.get("range_quality"), feature_frame.index)
        * (1.0 - _numeric_series(feature_frame.get("breakout_quality"), feature_frame.index))
    )
    chop = _clip01(_numeric_series(feature_frame.get("chop_risk"), feature_frame.index))
    breakout = _clip01(
        _numeric_series(feature_frame.get("breakout_quality"), feature_frame.index)
        * (1.0 + 0.2 * _clip01(_numeric_series(feature_frame.get("volume_confirmation"), feature_frame.index)))
    )
    vol_shock = _clip01(_numeric_series(feature_frame.get("shock_risk"), feature_frame.index))
    transition = transition_risk_series(feature_frame)

    raw = pd.DataFrame(
        {
            "trend": trend,
            "range": range_state,
            "chop": chop,
            "breakout": breakout,
            "vol_shock": vol_shock,
            "transition": transition,
        },
        index=feature_frame.index,
    )
    quality = feature_frame.get("row_quality_usable")
    if quality is not None:
        unusable = ~quality.fillna(False).astype(bool)
        raw.loc[unusable, :] = 0.0

    mass = raw.sum(axis=1)
    uniform = pd.DataFrame({name: 1.0 / len(raw.columns) for name in raw.columns}, index=raw.index)
    probs = raw.div(mass.replace(0.0, np.nan), axis=0).where(mass.gt(0.0), uniform).fillna(1.0 / len(raw.columns))
    probs.columns = (
        "p_trend_state",
        "p_range_state",
        "p_chop_state",
        "p_breakout_state",
        "p_vol_shock_state",
        "p_transition_state",
    )
    probs["state_entropy"] = state_entropy(probs.loc[:, probs.columns[:6]])
    dominant = probs.loc[:, probs.columns[:6]].idxmax(axis=1)
    probs["dominant_state"] = dominant.str.removeprefix("p_").str.removesuffix("_state")
    probs["dominant_state_prob"] = probs.loc[:, probs.columns[:6]].max(axis=1)
    return probs


def playbook_probability_frame(feature_frame: pd.DataFrame, *, horizon: int) -> pd.DataFrame:
    """Extract playbook probability columns into a normalized dataframe."""
    return pd.DataFrame(
        {
            playbook: _clip01(_numeric_series(feature_frame.get(playbook_probability_column(playbook, horizon)), feature_frame.index))
            for playbook in PLAYBOOKS
        },
        index=feature_frame.index,
    )


def apply_state_support_overlay(
    edge_probabilities: pd.DataFrame,
    *,
    state_frame: pd.DataFrame,
    config: ProbabilityOverlayConfig,
) -> pd.DataFrame:
    """Gate and smooth playbook probabilities using proxy state support."""
    gate_mask = (
        (state_frame["p_transition_state"] <= float(config.max_transition_state_prob))
        & (state_frame["state_entropy"] <= float(config.max_state_entropy))
    )
    state_support = pd.DataFrame(
        {
            "trend_following": state_frame["p_trend_state"],
            "breakout": state_frame["p_breakout_state"],
            "mean_reversion": state_frame[["p_range_state", "p_chop_state"]].max(axis=1),
            "countertrend": _clip01(
                state_frame[["p_range_state", "p_chop_state"]].max(axis=1) * (1.0 - state_frame["p_trend_state"])
            ),
            "scalping": _clip01(0.5 * state_frame["p_chop_state"] + 0.5 * (1.0 - state_frame["state_entropy"])),
        },
        index=edge_probabilities.index,
    )
    thresholds = {
        "trend_following": float(config.min_trend_state_prob),
        "breakout": float(config.min_breakout_state_prob),
        "mean_reversion": float(config.min_range_state_prob),
        "countertrend": float(config.min_range_state_prob),
        "scalping": float(config.min_range_state_prob),
    }
    adjusted = pd.DataFrame(index=edge_probabilities.index)
    for playbook in PLAYBOOKS:
        eligible = (
            gate_mask
            & (state_support[playbook] >= thresholds[playbook])
            & (edge_probabilities[playbook] >= float(config.min_edge_probability))
        )
        adjusted[playbook] = np.where(
            eligible,
            0.5 * edge_probabilities[playbook] + 0.5 * state_support[playbook],
            0.0,
        )
    return adjusted.fillna(0.0)


def apply_transition_overlay(
    feature_frame: pd.DataFrame,
    *,
    edge_probabilities: pd.DataFrame,
    state_frame: pd.DataFrame,
    config: ProbabilityOverlayConfig,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Suppress playbook probabilities when transition risk is elevated."""
    transition_risk = transition_risk_series(feature_frame, state_frame=state_frame)
    best = edge_probabilities.max(axis=1)
    gate_active = (
        (best >= float(config.min_edge_probability))
        & (state_frame["p_transition_state"] <= float(config.max_transition_state_prob))
        & (state_frame["state_entropy"] <= float(config.max_state_entropy))
        & (transition_risk <= float(config.transition_risk_threshold))
        & (_numeric_series(feature_frame.get("uncertainty"), feature_frame.index) <= float(config.uncertainty_threshold))
        & (
            _numeric_series(feature_frame.get("changepoint_prob"), feature_frame.index)
            <= float(config.changepoint_prob_threshold)
        )
    )
    adjusted = edge_probabilities.mul((1.0 - transition_risk).clip(lower=0.0), axis=0)
    adjusted = adjusted.mul(gate_active.astype(float), axis=0)
    return adjusted.fillna(0.0), transition_risk.astype(float), gate_active.astype(bool)


def apply_external_context_overlay(
    feature_frame: pd.DataFrame,
    *,
    edge_probabilities: pd.DataFrame,
    config: ProbabilityOverlayConfig,
) -> pd.DataFrame:
    """Adjust playbook probabilities using optional cross-asset context."""
    total3 = _clip_signed(_numeric_series(feature_frame.get("total3_confirmation"), feature_frame.index))
    market_alignment = _clip_signed(_numeric_series(feature_frame.get("market_alignment_score"), feature_frame.index))
    btc_d_conflict = _clip01(_numeric_series(feature_frame.get("btc_d_conflict_score"), feature_frame.index))
    coverage = _clip01(_numeric_series(feature_frame.get("external_context_coverage_ratio"), feature_frame.index))
    staleness = _numeric_series(
        feature_frame.get("external_context_staleness_bars"),
        feature_frame.index,
    ).fillna(float(config.max_staleness_bars))
    staleness_ratio = (staleness / max(float(config.max_staleness_bars), 1.0)).clip(lower=0.0)
    beta_signal = (
        _numeric_series(feature_frame.get("asset_beta_btc"), feature_frame.index).abs()
        + _numeric_series(feature_frame.get("asset_beta_eth"), feature_frame.index).abs()
    ) / 2.0
    beta_signal = _clip01(beta_signal / 2.0)
    penalty = (
        float(config.btc_d_conflict_weight) * btc_d_conflict
        + float(config.context_staleness_penalty) * staleness_ratio * (1.0 - coverage + 1.0)
    ).clip(lower=0.0)

    adjusted = pd.DataFrame(index=edge_probabilities.index)
    adjusted["trend_following"] = _clip01(
        edge_probabilities["trend_following"]
        * (
            1.0
            + float(config.total3_confirmation_weight) * total3.clip(lower=0.0)
            + float(config.market_alignment_weight) * market_alignment.clip(lower=0.0)
            + float(config.beta_weight) * beta_signal * market_alignment.clip(lower=0.0)
        )
        * (1.0 - penalty)
    )
    adjusted["breakout"] = _clip01(
        edge_probabilities["breakout"]
        * (
            1.0
            + float(config.total3_confirmation_weight) * total3.clip(lower=0.0)
            + 0.5 * float(config.market_alignment_weight) * market_alignment.clip(lower=0.0)
        )
        * (1.0 - penalty)
    )
    adjusted["mean_reversion"] = _clip01(
        edge_probabilities["mean_reversion"]
        * (
            1.0
            + float(config.btc_d_conflict_weight) * btc_d_conflict
            + float(config.market_alignment_weight) * (-market_alignment).clip(lower=0.0)
        )
        * (1.0 - float(config.context_staleness_penalty) * staleness_ratio)
    )
    adjusted["countertrend"] = _clip01(
        edge_probabilities["countertrend"]
        * (
            1.0
            + 0.5 * float(config.btc_d_conflict_weight) * btc_d_conflict
            + float(config.market_alignment_weight) * (-market_alignment).clip(lower=0.0)
        )
        * (1.0 - float(config.context_staleness_penalty) * staleness_ratio)
    )
    adjusted["scalping"] = _clip01(
        edge_probabilities["scalping"] * (1.0 - 0.5 * float(config.context_staleness_penalty) * staleness_ratio)
    )
    unavailable = coverage <= 0.0
    adjusted.loc[unavailable, :] = edge_probabilities.loc[unavailable, :]
    return adjusted.fillna(0.0)


def transition_risk_series(
    frame: pd.DataFrame,
    *,
    state_frame: pd.DataFrame | None = None,
) -> pd.Series:
    """Combine changepoint, uncertainty, and proxy transition inputs."""
    transition_inputs = [
        _clip01(_numeric_series(frame.get("structural_break_risk"), frame.index)),
        _clip01(_numeric_series(frame.get("uncertainty"), frame.index)),
        _clip01(_numeric_series(frame.get("changepoint_prob"), frame.index)),
        _clip01(_numeric_series(frame.get("cp_recent_max"), frame.index)),
        _clip01(_numeric_series(frame.get("transition_risk_raw"), frame.index)),
    ]
    if state_frame is not None and "p_transition_state" in state_frame.columns:
        transition_inputs.append(_clip01(_numeric_series(state_frame.get("p_transition_state"), frame.index)))
    return pd.concat(transition_inputs, axis=1).max(axis=1).fillna(0.0)


def state_entropy(state_frame: pd.DataFrame) -> pd.Series:
    """Normalized categorical entropy for proxy state probabilities."""
    probs = state_frame.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_probs = np.where(probs > 0.0, np.log(probs), 0.0)
    entropy = -(probs * log_probs).sum(axis=1)
    max_entropy = np.log(probs.shape[1]) if probs.shape[1] else 1.0
    normalized = np.clip(entropy / max(max_entropy, 1e-9), 0.0, 1.0)
    return pd.Series(normalized, index=state_frame.index, dtype=float)


def _numeric_series(values: pd.Series | None, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(0.0, index=index, dtype=float)
    return pd.to_numeric(values.reindex(index), errors="coerce").fillna(0.0)


def _clip01(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _clip_signed(values: pd.Series, *, lower: float = -1.0, upper: float = 1.0) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").fillna(0.0).clip(lower, upper)


__all__ = [
    "ProbabilityOverlayConfig",
    "ProbabilityOverlayFrame",
    "apply_external_context_overlay",
    "apply_state_support_overlay",
    "apply_transition_overlay",
    "build_probability_overlay",
    "build_state_proxy_frame",
    "overlay_config_from_params",
    "playbook_probability_frame",
    "state_entropy",
    "transition_risk_series",
]
