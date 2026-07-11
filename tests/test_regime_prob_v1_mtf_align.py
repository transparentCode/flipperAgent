from __future__ import annotations

import pandas as pd

from libs.models.regime_prob_v1 import (
    MTFAlignConfig,
    MTFFusionConfig,
    align_mtf_probability_frames,
    apply_mtf_weight_overlay,
    build_mtf_context_frame,
    build_mtf_fused_weight_frame,
)


def test_align_mtf_probability_frames_uses_backward_completed_bars_only():
    base_index = pd.date_range("2026-01-01 00:00:00", periods=8, freq="h", tz="UTC")
    htf = pd.DataFrame(
        {
            "p_trend_state": [0.30, 0.80],
            "state_entropy": [1.1, 0.6],
            "trend_following_p_edge_h3": [0.35, 0.82],
        },
        index=pd.to_datetime(
            [
                "2026-01-01 03:00:00+00:00",
                "2026-01-01 07:00:00+00:00",
            ]
        ),
    )

    aligned = align_mtf_probability_frames(
        base_index,
        {"4h": htf},
        base_timeframe="1h",
        config=MTFAlignConfig(),
    )

    assert aligned.loc[base_index[2], "mtf_4h_p_trend_state"] != 0.80
    assert aligned.loc[base_index[5], "mtf_4h_p_trend_state"] == 0.30
    assert aligned.loc[base_index[7], "mtf_4h_p_trend_state"] == 0.80


def test_build_mtf_context_frame_derives_confirmation_and_conflict():
    index = pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC")
    aligned = pd.DataFrame(
        {
            "mtf_4h_available": [True, True],
            "mtf_4h_p_trend_state": [0.85, 0.20],
            "mtf_4h_p_range_state": [0.10, 0.70],
            "mtf_4h_p_chop_state": [0.05, 0.45],
            "mtf_4h_p_breakout_state": [0.70, 0.10],
            "mtf_4h_p_vol_shock_state": [0.05, 0.70],
            "mtf_4h_p_transition_state": [0.10, 0.80],
            "mtf_4h_state_entropy": [0.50, 1.20],
            "mtf_4h_trend_following_p_edge_h3": [0.88, 0.25],
            "mtf_4h_breakout_p_edge_h3": [0.72, 0.20],
            "mtf_4h_mean_reversion_p_edge_h3": [0.10, 0.75],
        },
        index=index,
    )

    context = build_mtf_context_frame(aligned, higher_timeframes=("4h",), horizon=3)

    assert context.loc[index[0], "mtf_trend_confirmation"] > context.loc[index[1], "mtf_trend_confirmation"]
    assert context.loc[index[1], "mtf_mr_confirmation"] > context.loc[index[0], "mtf_mr_confirmation"]
    assert context.loc[index[1], "mtf_conflict_score"] > 0.0
    assert context.loc[index[1], "mtf_transition_max"] == 0.80


def test_apply_mtf_weight_overlay_boosts_confirmed_trend_and_penalizes_conflict():
    fused = apply_mtf_weight_overlay(
        {
            "trend_following": 0.45,
            "breakout": 0.20,
            "mean_reversion": 0.20,
            "countertrend": 0.10,
            "scalping": 0.05,
        },
        {
            "mtf_trend_confirmation": 0.85,
            "mtf_breakout_confirmation": 0.40,
            "mtf_mr_confirmation": 0.10,
            "mtf_conflict_score": 0.10,
            "mtf_entropy_max": 0.40,
            "mtf_transition_max": 0.05,
        },
        config=MTFFusionConfig(),
    )

    assert abs(sum(fused.values()) - 1.0) < 1e-9
    assert fused["trend_following"] > 0.45
    assert fused["mean_reversion"] < 0.20


def test_build_mtf_fused_weight_frame_emits_prefixed_weight_columns():
    index = pd.date_range("2026-01-01", periods=1, freq="h", tz="UTC")
    router_frame = pd.DataFrame(
        {
            "moe_weight_trend_following": [0.50],
            "moe_weight_breakout": [0.20],
            "moe_weight_mean_reversion": [0.15],
            "moe_weight_scalping": [0.10],
            "moe_weight_countertrend": [0.05],
        },
        index=index,
    )
    mtf_context = pd.DataFrame(
        {
            "mtf_trend_confirmation": [0.80],
            "mtf_breakout_confirmation": [0.30],
            "mtf_mr_confirmation": [0.10],
            "mtf_conflict_score": [0.05],
            "mtf_entropy_max": [0.30],
            "mtf_transition_max": [0.05],
        },
        index=index,
    )

    fused = build_mtf_fused_weight_frame(router_frame, mtf_context, config=MTFFusionConfig())

    assert "mtf_moe_weight_trend_following" in fused.columns
    assert fused.loc[index[0], "mtf_recommended_playbook"] == "trend_following"
    assert fused.loc[index[0], "mtf_moe_weight_trend_following"] > fused.loc[index[0], "mtf_moe_weight_mean_reversion"]
