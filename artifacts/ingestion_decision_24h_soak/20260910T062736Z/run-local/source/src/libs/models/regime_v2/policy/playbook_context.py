"""Richer deterministic playbook context for RegimeV2 Phase 7A.

This module does not change policy permissions. It annotates existing evidence
and policy output with explainable context that can later drive a redesigned
playbook policy after enough offline validation exists.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from libs.models.regime_v2.contracts import RegimeEvidence, RegimePolicy

_PLAYBOOK_SCORE_KEYS = (
    "trend_score",
    "breakout_score",
    "mean_reversion_score",
    "scalping_score",
    "countertrend_score",
)


def evidence_policy_to_context(evidence: RegimeEvidence, policy: RegimePolicy) -> dict[str, Any]:
    """Return deterministic diagnostic context for one evidence/policy pair."""
    playbook_scores = _playbook_scores(policy)
    dominant_playbook, dominant_score = _dominant_playbook(playbook_scores)
    conflict_tags = _conflict_tags(evidence, policy)
    risk_state, risk_score = _risk_state(evidence, policy)
    phase = _market_phase(evidence, policy, dominant_playbook=dominant_playbook, risk_state=risk_state)
    horizon_bias = _horizon_bias(evidence, policy, risk_state=risk_state, phase=phase)
    context_alignment = _context_alignment(evidence)
    return {
        "market_phase": phase,
        "risk_state": risk_state,
        "risk_score": round(risk_score, 4),
        "dominant_playbook": dominant_playbook,
        "dominant_playbook_score": round(dominant_score, 4),
        "horizon_bias": horizon_bias,
        "context_alignment": context_alignment,
        "conflict_tags": tuple(conflict_tags),
        "conflict_count": len(conflict_tags),
        "is_playbook_active": _any_playbook_allowed(policy),
        "is_context_confirmed": context_alignment in {"aligned", "neutral_or_missing"},
        "playbook_scores": playbook_scores,
        "recommended_next_step": _recommended_next_step(
            risk_state=risk_state,
            phase=phase,
            dominant_playbook=dominant_playbook,
            conflict_tags=conflict_tags,
            horizon_bias=horizon_bias,
        ),
    }


def build_playbook_context_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Build context columns from an analyze_series-style dataframe.

    The input may contain raw evidence columns plus `policy_*` columns produced by
    `RegimeV2Orchestrator.analyze_series`.
    """
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        evidence = _row_to_evidence(row)
        policy = _row_to_policy(row)
        context = evidence_policy_to_context(evidence, policy)
        rows.append(_flatten_context(context))
    return pd.DataFrame(rows, index=frame.index)


def _playbook_scores(policy: RegimePolicy) -> dict[str, float]:
    return {
        "trend": float(policy.trend_score),
        "breakout": float(policy.breakout_score),
        "mean_reversion": float(policy.mean_reversion_score),
        "scalping": float(policy.scalping_score),
        "countertrend": float(policy.countertrend_score),
    }


def _dominant_playbook(scores: Mapping[str, float]) -> tuple[str, float]:
    if not scores:
        return "none", 0.0
    name, score = max(scores.items(), key=lambda item: item[1])
    if score <= 0.05:
        return "none", float(score)
    return name, float(score)


def _risk_state(evidence: RegimeEvidence, policy: RegimePolicy) -> tuple[str, float]:
    risk_score = max(
        float(evidence.uncertainty),
        float(evidence.shock_risk),
        float(evidence.liquidity_stress),
        float(evidence.false_breakout_risk) * 0.75,
        float(evidence.structural_break_risk) * 0.60,
    )
    if policy.no_trade_reason or evidence.uncertainty >= 0.80 or evidence.shock_risk >= 0.85 or evidence.liquidity_stress >= 0.85:
        return "blocked", risk_score
    if risk_score >= 0.60:
        return "watch", risk_score
    return "ok", risk_score


def _market_phase(evidence: RegimeEvidence, policy: RegimePolicy, *, dominant_playbook: str, risk_state: str) -> str:
    if risk_state == "blocked":
        if evidence.shock_risk >= 0.80:
            return "shock_no_trade"
        if evidence.liquidity_stress >= 0.80:
            return "liquidity_no_trade"
        return "uncertain_no_trade"
    if evidence.shock_risk >= 0.70:
        return "shock_watch"
    if policy.displacement_breakout_score >= 0.35 and policy.breakout_score >= 0.25:
        return "displacement_breakout"
    if policy.retest_breakout_score >= 0.30 and policy.breakout_score >= 0.20:
        return "retest_breakout"
    if policy.breakout_setup_score >= 0.30 or evidence.pre_breakout_setup_score >= 0.55:
        return "breakout_setup"
    if dominant_playbook == "trend" and evidence.trend_direction in {"bull", "bear"}:
        return f"{evidence.trend_direction}_trend"
    if dominant_playbook == "mean_reversion":
        return "range_reversion"
    if evidence.range_quality >= 0.60 and evidence.chop_risk >= 0.55:
        return "range_chop"
    if evidence.compression_score >= 0.70:
        return "compressed_wait"
    return "neutral_context"


def _horizon_bias(evidence: RegimeEvidence, policy: RegimePolicy, *, risk_state: str, phase: str) -> str:
    if risk_state == "blocked":
        return "none"
    if evidence.shock_risk >= 0.65 or evidence.volatility_state == "shock":
        return "short_or_flat"
    if phase in {"displacement_breakout", "retest_breakout"} and evidence.false_breakout_risk <= 0.45:
        return "mid_to_long"
    if (
        evidence.trend_strength >= 0.62
        and evidence.trend_persistence >= 0.50
        and evidence.chop_risk <= 0.45
        and policy.trend_score >= 0.24
    ):
        return "long"
    if evidence.mean_reversion_score >= 0.65 or evidence.range_quality >= 0.65:
        return "short_to_mid"
    if evidence.compression_score >= 0.70:
        return "wait_for_expansion"
    return "mid"


def _context_alignment(evidence: RegimeEvidence) -> str:
    if abs(evidence.market_context_score) < 0.10 and abs(evidence.breadth_confirmation) < 0.10:
        return "neutral_or_missing"
    if evidence.trend_direction == "bull":
        return "aligned" if evidence.market_context_score >= -0.05 else "against"
    if evidence.trend_direction == "bear":
        return "aligned" if evidence.market_context_score <= 0.05 else "against"
    if evidence.market_context_score >= 0.35 or evidence.breadth_confirmation >= 0.35:
        return "risk_on_without_trend"
    if evidence.market_context_score <= -0.35 or evidence.breadth_confirmation <= -0.35:
        return "risk_off_without_trend"
    return "mixed"


def _conflict_tags(evidence: RegimeEvidence, policy: RegimePolicy) -> list[str]:
    tags: list[str] = []
    if evidence.trend_strength >= 0.55 and evidence.chop_risk >= 0.55:
        tags.append("trend_chop_conflict")
    if policy.breakout_score >= 0.20 and evidence.false_breakout_risk >= 0.55:
        tags.append("breakout_false_break_risk")
    if policy.breakout_score >= 0.20 and evidence.shock_risk >= 0.60:
        tags.append("breakout_shock_conflict")
    if policy.mean_reversion_score >= 0.20 and evidence.structural_break_risk >= 0.55:
        tags.append("mean_reversion_break_risk")
    if evidence.liquidity_stress >= 0.60:
        tags.append("liquidity_stress")
    if evidence.uncertainty >= 0.65:
        tags.append("uncertainty_high")
    if _context_alignment(evidence) in {"against", "mixed"}:
        tags.append("context_not_confirmed")
    if evidence.compression_score >= 0.75 and policy.breakout_score <= 0.10:
        tags.append("compression_without_breakout")
    if not _any_playbook_allowed(policy) and not policy.no_trade_reason:
        tags.append("no_allowed_playbook")
    return list(dict.fromkeys(tags))


def _any_playbook_allowed(policy: RegimePolicy) -> bool:
    return any(
        [
            policy.allow_trend_following,
            policy.allow_breakout,
            policy.allow_mean_reversion,
            policy.allow_scalping,
            policy.allow_countertrend,
        ]
    )


def _recommended_next_step(
    *,
    risk_state: str,
    phase: str,
    dominant_playbook: str,
    conflict_tags: list[str],
    horizon_bias: str,
) -> str:
    if risk_state == "blocked":
        return "skip_or_reduce_until_risk_clears"
    if "breakout_false_break_risk" in conflict_tags or "breakout_shock_conflict" in conflict_tags:
        return "require_retest_or_confirmation"
    if "trend_chop_conflict" in conflict_tags:
        return "prefer_smaller_size_or_wait_for_resolution"
    if horizon_bias in {"long", "mid_to_long"} and dominant_playbook in {"trend", "breakout"}:
        return "long_horizon_candidate"
    if dominant_playbook == "mean_reversion":
        return "mean_reversion_candidate"
    if phase == "compressed_wait":
        return "watch_for_breakout_expansion"
    return "observe_or_shadow_only"


def _flatten_context(context: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        "playbook_context_market_phase": context["market_phase"],
        "playbook_context_risk_state": context["risk_state"],
        "playbook_context_risk_score": context["risk_score"],
        "playbook_context_dominant_playbook": context["dominant_playbook"],
        "playbook_context_dominant_score": context["dominant_playbook_score"],
        "playbook_context_horizon_bias": context["horizon_bias"],
        "playbook_context_alignment": context["context_alignment"],
        "playbook_context_conflict_tags": ";".join(context["conflict_tags"]),
        "playbook_context_conflict_count": context["conflict_count"],
        "playbook_context_is_active": context["is_playbook_active"],
        "playbook_context_is_confirmed": context["is_context_confirmed"],
        "playbook_context_next_step": context["recommended_next_step"],
    }
    for name, score in dict(context.get("playbook_scores", {})).items():
        out[f"playbook_context_score_{name}"] = float(score)
    return out


def _row_to_evidence(row: pd.Series) -> RegimeEvidence:
    return RegimeEvidence(
        timestamp=row.name,
        asset=str(row.get("asset", "")),
        timeframe=str(row.get("timeframe", "")),
        trend_direction=str(row.get("trend_direction", "neutral")),
        trend_strength=_float(row.get("trend_strength")),
        trend_persistence=_float(row.get("trend_persistence")),
        trend_confidence=_float(row.get("trend_confidence")),
        volatility_percentile=_float(row.get("volatility_percentile"), 50.0),
        volatility_state=str(row.get("volatility_state", "normal")),
        compression_score=_float(row.get("compression_score")),
        shock_risk=_float(row.get("shock_risk")),
        mean_reversion_score=_float(row.get("mean_reversion_score")),
        range_quality=_float(row.get("range_quality")),
        chop_risk=_float(row.get("chop_risk")),
        structural_break_risk=_float(row.get("structural_break_risk")),
        breakout_quality=_float(row.get("breakout_quality")),
        false_breakout_risk=_float(row.get("false_breakout_risk")),
        market_context_score=_float(row.get("market_context_score")),
        breadth_confirmation=_float(row.get("breadth_confirmation")),
        liquidity_stress=_float(row.get("liquidity_stress")),
        confidence=_float(row.get("confidence")),
        uncertainty=_float(row.get("uncertainty"), 1.0),
        summary_label=str(row.get("summary_label", "unknown")),
        pre_breakout_setup_score=_float(row.get("pre_breakout_setup_score")),
        displacement_breakout_score=_float(row.get("displacement_breakout_score")),
        post_breakout_retest_score=_float(row.get("post_breakout_retest_score")),
    )


def _row_to_policy(row: pd.Series) -> RegimePolicy:
    return RegimePolicy(
        allow_trend_following=bool(row.get("policy_allow_trend_following", row.get("allow_trend_following", False))),
        allow_breakout=bool(row.get("policy_allow_breakout", row.get("allow_breakout", False))),
        allow_mean_reversion=bool(row.get("policy_allow_mean_reversion", row.get("allow_mean_reversion", False))),
        allow_scalping=bool(row.get("policy_allow_scalping", row.get("allow_scalping", False))),
        allow_countertrend=bool(row.get("policy_allow_countertrend", row.get("allow_countertrend", False))),
        max_position_scale=_float(row.get("policy_max_position_scale", row.get("max_position_scale"))),
        stop_multiplier=_float(row.get("policy_stop_multiplier", row.get("stop_multiplier")), 1.0),
        target_multiplier=_float(row.get("policy_target_multiplier", row.get("target_multiplier")), 1.0),
        holding_period_prior=int(_float(row.get("policy_holding_period_prior", row.get("holding_period_prior")), 1.0)),
        trend_score=_float(row.get("policy_trend_score", row.get("trend_score"))),
        breakout_score=_float(row.get("policy_breakout_score", row.get("breakout_score"))),
        mean_reversion_score=_float(row.get("policy_mean_reversion_score", row.get("mean_reversion_score"))),
        scalping_score=_float(row.get("policy_scalping_score", row.get("scalping_score"))),
        countertrend_score=_float(row.get("policy_countertrend_score", row.get("countertrend_score"))),
        breakout_setup_score=_float(row.get("policy_breakout_setup_score", row.get("breakout_setup_score"))),
        displacement_breakout_score=_float(row.get("policy_displacement_breakout_score", row.get("displacement_breakout_score"))),
        retest_breakout_score=_float(row.get("policy_retest_breakout_score", row.get("retest_breakout_score"))),
        no_trade_reason=_none_if_blank(row.get("policy_no_trade_reason", row.get("no_trade_reason"))),
        reasons=(),
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _none_if_blank(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return None if not text or text.lower() == "nan" else text


__all__ = ["build_playbook_context_frame", "evidence_policy_to_context"]
