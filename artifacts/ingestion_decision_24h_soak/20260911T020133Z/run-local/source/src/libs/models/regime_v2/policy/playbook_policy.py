"""Playbook permission policy for RegimeV2 phase 1."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.config import PolicyConfig
from libs.models.regime_v2.contracts import RegimeEvidence, RegimePolicy
from libs.models.regime_v2.features.utils import clip01


def build_policy_frame(evidence_df: pd.DataFrame, config: PolicyConfig) -> pd.DataFrame:
    """Vectorized policy derivation from evidence dataframe."""
    rows = [evidence_to_policy(_row_to_contract(row), config).to_dict() for _, row in evidence_df.iterrows()]
    return pd.DataFrame(rows, index=evidence_df.index)


def evidence_to_policy(evidence: RegimeEvidence, config: PolicyConfig) -> RegimePolicy:
    reasons: list[str] = []

    if evidence.uncertainty >= config.high_uncertainty_no_trade:
        reasons.append("uncertainty_too_high")
    if evidence.shock_risk >= config.no_trade_shock_threshold:
        reasons.append("shock_risk_extreme")
    if evidence.liquidity_stress >= config.no_trade_liquidity_threshold:
        reasons.append("liquidity_stress_extreme")

    base_allowed = not reasons and evidence.confidence >= config.min_confidence
    if evidence.confidence < config.min_confidence:
        reasons.append("confidence_below_minimum")

    scores = _playbook_scores(evidence, config)

    score_floor = _playbook_score_floor(config)
    allow_trend = bool(base_allowed and scores["trend"] >= score_floor)
    allow_breakout = bool(base_allowed and scores["breakout"] >= score_floor)
    allow_mr = bool(base_allowed and scores["mean_reversion"] >= score_floor)
    allow_scalping = bool(base_allowed and scores["scalping"] >= score_floor)
    allow_countertrend = bool(base_allowed and scores["countertrend"] >= score_floor)

    if not any([allow_trend, allow_breakout, allow_mr, allow_scalping, allow_countertrend]) and not reasons:
        reasons.append("no_playbook_edge")

    any_allowed = any([allow_trend, allow_breakout, allow_mr, allow_scalping, allow_countertrend])
    max_position_scale = _position_scale(evidence, config, any_allowed)
    stop_multiplier = _stop_multiplier(evidence, config)
    target_multiplier = _target_multiplier(
        evidence,
        config,
        allow_trend=allow_trend,
        allow_breakout=allow_breakout,
    )
    holding_period = _holding_period(evidence, config)

    return RegimePolicy(
        allow_trend_following=allow_trend,
        allow_breakout=allow_breakout,
        allow_mean_reversion=allow_mr,
        allow_scalping=allow_scalping,
        allow_countertrend=allow_countertrend,
        max_position_scale=max_position_scale,
        stop_multiplier=stop_multiplier,
        target_multiplier=target_multiplier,
        holding_period_prior=holding_period,
        trend_score=round(scores["trend"], 4),
        breakout_score=round(scores["breakout"], 4),
        mean_reversion_score=round(scores["mean_reversion"], 4),
        scalping_score=round(scores["scalping"], 4),
        countertrend_score=round(scores["countertrend"], 4),
        breakout_setup_score=round(scores["breakout_setup"], 4),
        displacement_breakout_score=round(scores["displacement_breakout"], 4),
        retest_breakout_score=round(scores["retest_breakout"], 4),
        no_trade_reason=";".join(reasons) if reasons and not any([allow_trend, allow_breakout, allow_mr, allow_scalping, allow_countertrend]) else None,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _playbook_scores(evidence: RegimeEvidence, config: PolicyConfig) -> dict[str, float]:
    """Continuous playbook suitability scores in [0, 1].

    These are diagnostic/evaluation scores.  Boolean permissions are derived
    from them plus global risk gates, so downstream backtests can evaluate
    threshold sensitivity without recomputing evidence.
    """
    confidence_gate = evidence.confidence
    uncertainty_soft_penalty = 1.0 - config.uncertainty_soft_penalty_weight * evidence.uncertainty
    shock_gate = 1.0 - evidence.shock_risk
    liquidity_gate = 1.0 - evidence.liquidity_stress

    trend_direction_gate = 1.0 if evidence.trend_direction in {"bull", "bear"} else 0.0
    trend_score = (
        confidence_gate
        * trend_direction_gate
        * _soft_threshold(evidence.trend_strength, config.trend_min_strength, width=config.threshold_width)
        * _inverse_soft_threshold(evidence.chop_risk, config.trend_max_chop, width=config.threshold_width)
        * (config.trend_persistence_base + config.trend_persistence_weight * evidence.trend_persistence)
    )

    breakout_setup_score = (
        confidence_gate
        * _soft_threshold(evidence.pre_breakout_setup_score, config.breakout_setup_min, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.structural_break_risk,
            config.breakout_setup_max_break_risk,
            width=config.threshold_width,
        )
        * _inverse_soft_threshold(evidence.shock_risk, config.breakout_setup_max_shock, width=config.threshold_width)
    )
    displacement_breakout_score = (
        confidence_gate
        * _soft_threshold(evidence.displacement_breakout_score, config.breakout_min_quality, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.false_breakout_risk,
            config.breakout_max_false_break,
            width=config.threshold_width,
        )
        * _inverse_soft_threshold(
            evidence.shock_risk,
            config.displacement_breakout_max_shock,
            width=config.threshold_width,
        )
    )
    retest_breakout_score = (
        confidence_gate
        * _soft_threshold(evidence.post_breakout_retest_score, config.retest_breakout_min, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.false_breakout_risk,
            config.breakout_max_false_break,
            width=config.threshold_width,
        )
        * _inverse_soft_threshold(
            evidence.structural_break_risk,
            config.retest_breakout_max_break_risk,
            width=config.threshold_width,
        )
    )
    breakout_score = max(displacement_breakout_score, retest_breakout_score)

    mr_context = max(evidence.range_quality, evidence.compression_score * config.mr_context_compression_weight)
    mean_reversion_score = (
        confidence_gate
        * _soft_threshold(evidence.mean_reversion_score, config.mr_min_score, width=config.threshold_width)
        * _soft_threshold(mr_context, config.mr_context_min, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.structural_break_risk,
            config.mr_max_break_risk,
            width=config.threshold_width,
        )
    )

    scalping_score = (
        confidence_gate
        * _inverse_soft_threshold(evidence.shock_risk, config.scalping_max_shock, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.liquidity_stress,
            config.scalping_max_liquidity,
            width=config.threshold_width,
        )
        * (
            config.scalping_context_base
            + config.scalping_context_weight
            * max(evidence.trend_strength, evidence.range_quality, evidence.breakout_quality)
        )
    )

    countertrend_score = (
        confidence_gate
        * _soft_threshold(evidence.range_quality, config.countertrend_min_range, width=config.threshold_width)
        * _inverse_soft_threshold(
            evidence.trend_strength,
            config.countertrend_max_trend_strength,
            width=config.threshold_width,
        )
        * _inverse_soft_threshold(
            evidence.structural_break_risk,
            config.countertrend_max_break_risk,
            width=config.threshold_width,
        )
    )

    # Confidence is already a direct multiplier in every playbook score.
    # Using ``min(1 - uncertainty, ...)`` here double-counted uncertainty and
    # compressed valid trend setups to near zero.  Keep shock/liquidity as hard
    # gates and treat uncertainty as a softer penalty.
    global_risk_gate = clip01(min(shock_gate, liquidity_gate) * uncertainty_soft_penalty)
    return {
        "trend": float(clip01(trend_score * global_risk_gate)),
        "breakout": float(clip01(breakout_score * global_risk_gate)),
        "mean_reversion": float(clip01(mean_reversion_score * global_risk_gate)),
        "scalping": float(clip01(scalping_score * global_risk_gate)),
        "countertrend": float(clip01(countertrend_score * global_risk_gate)),
        "breakout_setup": float(clip01(breakout_setup_score * global_risk_gate)),
        "displacement_breakout": float(clip01(displacement_breakout_score * global_risk_gate)),
        "retest_breakout": float(clip01(retest_breakout_score * global_risk_gate)),
    }


def _playbook_score_floor(config: PolicyConfig) -> float:
    """Floor for continuous suitability scores.

    ``config.min_confidence`` remains the hard global confidence gate.  The
    playbook score floor is slightly lower because scores already multiply
    several soft gates and can compress valid but borderline setups.
    """
    return max(
        config.playbook_score_floor_min,
        min(config.playbook_score_floor_max, config.min_confidence * config.playbook_score_floor_confidence_mult),
    )


def _soft_threshold(value: float, threshold: float, width: float = 0.20) -> float:
    """Map threshold crossing to a smooth-ish linear score."""
    width = max(width, 1e-9)
    return float(clip01((value - threshold + width) / (2.0 * width)))


def _inverse_soft_threshold(value: float, threshold: float, width: float = 0.20) -> float:
    width = max(width, 1e-9)
    return float(clip01((threshold - value + width) / (2.0 * width)))


def _position_scale(evidence: RegimeEvidence, config: PolicyConfig, any_allowed: bool) -> float:
    if not any_allowed:
        return 0.0
    risk_penalty = max(
        evidence.uncertainty,
        evidence.shock_risk,
        evidence.liquidity_stress * config.position_scale_liquidity_penalty_weight,
    )
    scale = evidence.confidence * (1.0 - config.position_scale_risk_penalty_weight * risk_penalty)
    if (
        evidence.structural_break_risk > config.position_scale_break_risk_threshold
        and evidence.breakout_quality < config.position_scale_breakout_quality_threshold
    ):
        scale *= config.position_scale_break_risk_multiplier
    return round(float(clip01(scale)), 4)


def _stop_multiplier(evidence: RegimeEvidence, config: PolicyConfig) -> float:
    base = config.stop_base + config.stop_shock_weight * evidence.shock_risk + config.stop_break_weight * evidence.structural_break_risk
    if evidence.volatility_state in {"expanding", "shock"}:
        base += config.stop_expanding_bonus
    return round(float(max(config.stop_min, min(base, config.stop_max))), 4)


def _target_multiplier(
    evidence: RegimeEvidence,
    config: PolicyConfig,
    *,
    allow_trend: bool,
    allow_breakout: bool,
) -> float:
    base = config.target_base
    if allow_trend:
        base += config.target_trend_weight * evidence.trend_strength
    if allow_breakout:
        base += config.target_breakout_weight * evidence.breakout_quality
    if evidence.chop_risk > config.target_chop_threshold:
        base *= config.target_chop_multiplier
    return round(float(max(config.target_min, min(base, config.target_max))), 4)


def _holding_period(evidence: RegimeEvidence, config: PolicyConfig) -> int:
    base = config.base_holding_period
    if (
        evidence.trend_strength > config.holding_period_trend_strength_threshold
        and evidence.chop_risk < config.holding_period_trend_chop_max
    ):
        base = int(base * config.holding_period_trend_multiplier)
    if (
        evidence.mean_reversion_score > config.holding_period_mr_threshold
        or evidence.shock_risk > config.holding_period_shock_threshold
    ):
        base = int(base * config.holding_period_reduction_multiplier)
    return max(1, base)


def _row_to_contract(row: pd.Series) -> RegimeEvidence:
    return RegimeEvidence(
        timestamp=row.name,
        asset=str(row.get("asset", "")),
        timeframe=str(row.get("timeframe", "")),
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


__all__ = ["build_policy_frame", "evidence_to_policy"]
