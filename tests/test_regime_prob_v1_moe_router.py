from __future__ import annotations

import pandas as pd

from libs.models.regime_prob_v1.moe import (
    MoERouterConfig,
    build_moe_router_frame,
    route_playbooks,
)


def test_route_playbooks_uses_edge_probabilities_with_policy_gates():
    decision = route_playbooks(
        {
            "trend_following": 0.74,
            "breakout": 0.81,
            "mean_reversion": 0.61,
            "scalping": 0.20,
            "countertrend": 0.58,
        },
        policy_allows={
            "trend_following": True,
            "breakout": False,
            "mean_reversion": True,
            "scalping": True,
            "countertrend": False,
        },
        policy_scores={
            "trend_following": 0.70,
            "breakout": 0.85,
            "mean_reversion": 0.40,
            "scalping": 0.25,
            "countertrend": 0.15,
        },
        config=MoERouterConfig(min_edge_probability=0.55),
    )

    assert decision.recommended_playbook == "trend_following"
    assert decision.weights["breakout"] == 0.0
    assert decision.weights["countertrend"] == 0.0
    assert decision.weights["trend_following"] > decision.weights["mean_reversion"] > 0.0
    assert abs(sum(decision.weights.values()) - 1.0) < 1e-9
    assert "policy_disallow" in decision.diagnostics["gate_reasons"]["breakout"]


def test_route_playbooks_returns_none_when_all_edges_fail_threshold():
    decision = route_playbooks(
        {
            "trend_following": 0.52,
            "breakout": 0.51,
            "mean_reversion": 0.40,
            "scalping": 0.20,
            "countertrend": 0.30,
        },
        policy_allows={name: True for name in ("trend_following", "breakout", "mean_reversion", "scalping", "countertrend")},
        policy_scores={name: 0.5 for name in ("trend_following", "breakout", "mean_reversion", "scalping", "countertrend")},
        config=MoERouterConfig(min_edge_probability=0.55),
    )

    assert decision.recommended_playbook is None
    assert all(weight == 0.0 for weight in decision.weights.values())
    assert decision.diagnostics["normalization_mass"] == 0.0


def test_build_moe_router_frame_emits_weight_columns_and_recommendation():
    frame = pd.DataFrame(
        [
            {
                "trend_following_p_edge_h3": 0.72,
                "breakout_p_edge_h3": 0.66,
                "mean_reversion_p_edge_h3": 0.30,
                "scalping_p_edge_h3": 0.40,
                "countertrend_p_edge_h3": 0.20,
                "policy_allow_trend_following": True,
                "policy_allow_breakout": True,
                "policy_allow_mean_reversion": True,
                "policy_allow_scalping": False,
                "policy_allow_countertrend": False,
                "policy_trend_score": 0.62,
                "policy_breakout_score": 0.44,
                "policy_mean_reversion_score": 0.22,
                "policy_scalping_score": 0.10,
                "policy_countertrend_score": 0.11,
            },
            {
                "trend_following_p_edge_h3": 0.40,
                "breakout_p_edge_h3": 0.42,
                "mean_reversion_p_edge_h3": 0.41,
                "scalping_p_edge_h3": 0.35,
                "countertrend_p_edge_h3": 0.39,
                "policy_allow_trend_following": True,
                "policy_allow_breakout": True,
                "policy_allow_mean_reversion": True,
                "policy_allow_scalping": True,
                "policy_allow_countertrend": True,
                "policy_trend_score": 0.40,
                "policy_breakout_score": 0.41,
                "policy_mean_reversion_score": 0.39,
                "policy_scalping_score": 0.35,
                "policy_countertrend_score": 0.32,
            },
        ],
        index=pd.date_range("2026-01-01", periods=2, freq="h", tz="UTC"),
    )

    routed = build_moe_router_frame(
        frame,
        horizon=3,
        config=MoERouterConfig(min_edge_probability=0.55),
    )

    assert routed.loc[frame.index[0], "recommended_playbook"] == "trend_following"
    assert routed.loc[frame.index[0], "moe_weight_trend_following"] > routed.loc[frame.index[0], "moe_weight_breakout"]
    assert routed.loc[frame.index[1], "recommended_playbook"] is None
    assert routed.loc[frame.index[1], "moe_active_count"] == 0
