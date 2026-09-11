"""Runtime and reporting contracts for RegimeProbV1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ProbabilisticRegimeOutput:
    """Bar-level probabilistic overlay output."""

    timestamp: Any
    asset: str
    timeframe: str
    p_trend_state: float
    p_range_state: float
    p_chop_state: float
    p_breakout_state: float
    p_vol_shock_state: float
    p_transition_state: float
    state_entropy: float
    dominant_state: str
    dominant_state_prob: float
    p_trend_following_edge: float
    p_breakout_edge: float
    p_mean_reversion_edge: float
    p_scalping_edge: float
    p_countertrend_edge: float
    moe_weights: dict[str, float]
    recommended_playbook: str | None
    mtf_context: dict[str, Any]
    external_context: dict[str, Any]
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegimeProbTrainingReport:
    """Offline training and audit report contract."""

    asset: str
    timeframe: str
    profile: str
    purge_bars: int
    train_range: tuple[str, str]
    calibration_range: tuple[str, str]
    validation_range: tuple[str, str]
    oos_range: tuple[str, str]
    state_model_metrics: dict[str, Any]
    edge_model_metrics: dict[str, Any]
    calibration_metrics: dict[str, Any]
    downstream_lift: dict[str, Any]
    gates: dict[str, Any]
    rejection_reasons: tuple[str, ...]
    artifacts: dict[str, Any]
    decision: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssetTimeframeProfile:
    """Asset/timeframe behavior summary used for defaults and research."""

    asset: str
    timeframe: str
    liquidity_tier: str
    volatility_tier: str
    trend_persistence_tier: str
    mean_reversion_tier: str
    breakout_followthrough_tier: str
    false_breakout_tier: str
    btc_beta_tier: str
    eth_beta_tier: str
    total2_beta_tier: str
    total3_beta_tier: str
    funding_sensitivity_tier: str
    oi_sensitivity_tier: str
    recommended_profile: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AssetTimeframeProfile",
    "ProbabilisticRegimeOutput",
    "RegimeProbTrainingReport",
]
