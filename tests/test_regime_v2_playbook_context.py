"""Tests for Phase 7A richer deterministic playbook context."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.contracts import RegimeEvidence, RegimePolicy
from libs.models.regime_v2.policy.playbook_context import (
    build_playbook_context_frame,
    evidence_policy_to_context,
)


def _evidence(**overrides) -> RegimeEvidence:
    base = dict(
        timestamp=1,
        asset="BTCUSDT",
        timeframe="1h",
        trend_direction="bull",
        trend_strength=0.70,
        trend_persistence=0.65,
        trend_confidence=0.75,
        volatility_percentile=55.0,
        volatility_state="normal",
        compression_score=0.20,
        shock_risk=0.10,
        mean_reversion_score=0.15,
        range_quality=0.20,
        chop_risk=0.20,
        structural_break_risk=0.20,
        breakout_quality=0.20,
        false_breakout_risk=0.15,
        market_context_score=0.35,
        breadth_confirmation=0.25,
        liquidity_stress=0.10,
        confidence=0.80,
        uncertainty=0.15,
        summary_label="bull_trend",
        pre_breakout_setup_score=0.05,
        displacement_breakout_score=0.05,
        post_breakout_retest_score=0.05,
    )
    base.update(overrides)
    return RegimeEvidence(**base)


def _policy(**overrides) -> RegimePolicy:
    base = dict(
        allow_trend_following=True,
        allow_breakout=False,
        allow_mean_reversion=False,
        allow_scalping=False,
        allow_countertrend=False,
        max_position_scale=0.5,
        stop_multiplier=1.0,
        target_multiplier=1.2,
        holding_period_prior=12,
        trend_score=0.42,
        breakout_score=0.08,
        mean_reversion_score=0.04,
        scalping_score=0.10,
        countertrend_score=0.02,
        breakout_setup_score=0.02,
        displacement_breakout_score=0.02,
        retest_breakout_score=0.02,
        no_trade_reason=None,
        reasons=(),
    )
    base.update(overrides)
    return RegimePolicy(**base)


def test_context_identifies_confirmed_long_trend():
    context = evidence_policy_to_context(_evidence(), _policy())

    assert context["market_phase"] == "bull_trend"
    assert context["risk_state"] == "ok"
    assert context["dominant_playbook"] == "trend"
    assert context["horizon_bias"] == "long"
    assert context["context_alignment"] == "aligned"
    assert context["recommended_next_step"] == "long_horizon_candidate"
    assert context["conflict_count"] == 0


def test_context_blocks_shock_and_adds_risk_tags():
    context = evidence_policy_to_context(
        _evidence(shock_risk=0.90, uncertainty=0.85, volatility_state="shock"),
        _policy(allow_trend_following=False, trend_score=0.0, no_trade_reason="uncertainty_too_high"),
    )

    assert context["risk_state"] == "blocked"
    assert context["market_phase"] == "shock_no_trade"
    assert context["horizon_bias"] == "none"
    assert "uncertainty_high" in context["conflict_tags"]
    assert context["recommended_next_step"] == "skip_or_reduce_until_risk_clears"


def test_context_marks_breakout_false_break_conflict():
    context = evidence_policy_to_context(
        _evidence(
            trend_direction="neutral",
            trend_strength=0.20,
            breakout_quality=0.80,
            false_breakout_risk=0.70,
            displacement_breakout_score=0.70,
            market_context_score=0.0,
        ),
        _policy(
            allow_trend_following=False,
            allow_breakout=True,
            trend_score=0.02,
            breakout_score=0.36,
            displacement_breakout_score=0.42,
        ),
    )

    assert context["dominant_playbook"] == "breakout"
    assert context["market_phase"] == "displacement_breakout"
    assert "breakout_false_break_risk" in context["conflict_tags"]
    assert context["recommended_next_step"] == "require_retest_or_confirmation"


def test_context_frame_flattens_analyze_series_style_rows():
    frame = pd.DataFrame(
        [
            {
                **_evidence().to_dict(),
                **{f"policy_{k}": v for k, v in _policy().to_dict().items()},
            }
        ],
        index=pd.Index([123], name="timestamp"),
    )

    out = build_playbook_context_frame(frame)

    assert out.loc[123, "playbook_context_market_phase"] == "bull_trend"
    assert out.loc[123, "playbook_context_dominant_playbook"] == "trend"
    assert out.loc[123, "playbook_context_horizon_bias"] == "long"
    assert out.loc[123, "playbook_context_score_trend"] == 0.42
