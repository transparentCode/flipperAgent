"""Tests for Phase 7R setup-transition pruning discovery."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_setup_prune import (
    apply_setup_transition_prune,
    build_setup_transition_prune_matrix_report,
    build_setup_transition_prune_report,
    render_setup_transition_prune_markdown,
)
from libs.models.regime_v2.scripts.report_transition_setup_prune import _parse_args, _phase_mode_arg, _continuation_arg


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "breakout_transition_active": True,
                "breakout_transition_direction": "up",
                "breakout_transition_state": "FAILED_BREAKOUT_REVERSAL_SETUP",
                "breakout_transition_score": 0.7,
                "breakout_transition_continuation_score": 0.4,
                "breakout_followthrough_active": True,
                "setup_transition_up_score": 0.75,
                "setup_transition_down_score": 0.20,
                "setup_transition_volatility": 0.01,
                "ft_context_gate_market_phase": "breakout_setup",
            },
            {
                "breakout_transition_active": True,
                "breakout_transition_direction": "down",
                "breakout_transition_state": "FAILED_BREAKOUT_REVERSAL_SETUP",
                "breakout_transition_score": 0.7,
                "breakout_transition_continuation_score": 0.9,
                "breakout_followthrough_active": True,
                "setup_transition_up_score": 0.55,
                "setup_transition_down_score": 0.50,
                "setup_transition_volatility": 0.05,
                "ft_context_gate_market_phase": "compressed_wait",
            },
            {
                "breakout_transition_active": False,
                "breakout_transition_direction": "none",
                "breakout_transition_state": "NO_BREAKOUT_TRANSITION",
                "breakout_transition_score": 0.0,
                "breakout_transition_continuation_score": 0.0,
                "breakout_followthrough_active": False,
                "setup_transition_up_score": 0.0,
                "setup_transition_down_score": 0.0,
                "setup_transition_volatility": 0.02,
                "ft_context_gate_market_phase": "compressed_wait",
            },
        ]
    )


def test_apply_setup_transition_prune_flags_reasons():
    out = apply_setup_transition_prune(
        _candidates(),
        min_score_gap=0.20,
        max_continuation_score=0.8,
        max_volatility_quantile=1.0,
        allowed_market_phases=("breakout_setup",),
    )

    assert int(out["setup_transition_pre_prune_active"].sum()) == 2
    assert int(out["setup_transition_post_prune_active"].sum()) == 1
    assert bool(out.loc[0, "breakout_followthrough_active"]) is True
    assert bool(out.loc[1, "breakout_followthrough_active"]) is False
    assert "phase_pruned" in out.loc[1, "setup_transition_prune_tags"]


def test_prune_report_matrix_and_markdown():
    out = apply_setup_transition_prune(_candidates(), min_score_gap=0.20, max_continuation_score=0.8)
    report = build_setup_transition_prune_report(out, asset="ETHUSDT", timeframe="1h", config={"unit": True})
    matrix = build_setup_transition_prune_matrix_report(
        [
            {
                "summary": {
                    "asset": "ETHUSDT",
                    "timeframe": "1h",
                    "pre_active_count": report["summary"]["pre_active_count"],
                    "post_active_count": report["summary"]["post_active_count"],
                    "pruned_count": report["summary"]["pruned_count"],
                    "pruned_rate": report["summary"]["pruned_rate"],
                    "state_distribution": report["summary"]["state_distribution"],
                    "direction_distribution": report["summary"]["direction_distribution"],
                    "phase_distribution": report["summary"]["phase_distribution"],
                    "prune_reason_distribution": report["summary"]["prune_reason_distribution"],
                    "passed_split_count": 2,
                    "split_count": 4,
                    "ready": False,
                    "recommendation": "unit",
                    "avg_split_directional_return": 0.1,
                    "worst_split_directional_return": -0.1,
                    "passing_cell_count": 1,
                },
                "prune_report": report,
                "outcome_matrix": {"summary": {}},
                "walkforward_report": {"splits": []},
            }
        ]
    )
    md = render_setup_transition_prune_markdown(matrix)

    assert report["summary"]["pre_active_count"] == 2
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7R Setup Transition Prune Matrix" in md


def test_prune_cli_defaults_and_helpers():
    args = _parse_args(["--asset", "ETHUSDT", "--min-score-gap", "0.1", "--max-continuation-score", "0.75", "--phase-mode", "breakout_setup"])
    assert args.asset == ["ETHUSDT"]
    assert args.min_score_gap == [0.1]
    assert args.max_continuation_score == [0.75]
    assert args.phase_mode == ["breakout_setup"]
    assert _continuation_arg(-1.0) is None
    assert _continuation_arg(0.7) == 0.7
    assert _phase_mode_arg("all") is None
    assert _phase_mode_arg("compressed_wait") == ("compressed_wait",)

    defaults = _parse_args([])
    assert defaults.asset == ["ETHUSDT", "BNBUSDT", "BTCUSDT"]
    assert defaults.min_score_gap == [0.0, 0.15, 0.25]
    assert defaults.max_volatility_quantile == [1.0, 0.85, 0.70]
