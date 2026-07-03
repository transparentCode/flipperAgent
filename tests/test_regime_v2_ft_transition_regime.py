"""Tests for Phase 7N feature-driven transition regime."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_transition_regime import (
    apply_ft_transition_regime,
    build_ft_transition_regime_matrix_report,
    build_ft_transition_regime_report,
    render_ft_transition_regime_markdown,
)
from libs.models.regime_v2.scripts.report_ft_transition_regime import _parse_args


def _refined() -> pd.DataFrame:
    rows = []
    for i in range(4):
        weak = i == 2
        active = i in {1, 2, 3}
        rows.append(
            {
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_base": "WAIT_COMPRESSION",
                "playbook_state_group": "executable" if active else "wait",
                "playbook_state_reason": "confirmed" if active else "unit",
                "playbook_state_is_executable": active,
                "playbook_state_is_wait": not active,
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "down" if weak else "up",
                "breakout_followthrough_score": 0.35,
                "breakout_followthrough_follow_score": 0.25 if weak else 1.0,
                "breakout_followthrough_hold_score": 0.20 if weak else 1.0,
                "breakout_followthrough_direction_return_score": 0.20 if weak else 1.0,
                "breakout_followthrough_reversal_penalty": 0.75 if weak else 0.10,
                "breakout_followthrough_volume_score": 0.10,
                "ft_context_gate_score": 0.76,
                "ft_context_gate_market_phase": "compressed_wait",
                "ft_context_gate_horizon_bias": "wait_for_expansion",
            }
        )
    return pd.DataFrame(rows)


def test_transition_regime_reverses_feature_driven_row_without_split():
    out = apply_ft_transition_regime(_refined(), min_transition_edge=0.05, min_reversal_penalty=0.60)

    assert bool(out.loc[2, "ft_transition_regime_applied"]) is True
    assert out.loc[2, "ft_transition_regime_original_direction"] == "down"
    assert out.loc[2, "breakout_followthrough_direction"] == "up"
    assert out.loc[2, "ft_transition_regime_reason"] == "transition_regime_signature"
    assert bool(out.loc[1, "ft_transition_regime_applied"]) is False


def test_transition_regime_report_matrix_and_markdown():
    out = apply_ft_transition_regime(_refined(), min_transition_edge=0.05, min_reversal_penalty=0.60)
    report = build_ft_transition_regime_report(out, asset="BNBUSDT", timeframe="1h", threshold=0.25)
    matrix = build_ft_transition_regime_matrix_report(
        [
            {
                "summary": {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "threshold": 0.25,
                    "active_total": 3,
                    "flagged_count": 1,
                    "applied_count": 1,
                    "passed_split_count": 2,
                    "split_count": 4,
                    "ready": False,
                    "avg_split_directional_return": 0.1,
                    "worst_split_directional_return": -0.1,
                },
                "transition_regime_report": report,
                "walkforward_report": {"splits": []},
            }
        ]
    )
    md = render_ft_transition_regime_markdown(matrix)

    assert report["summary"]["applied_count"] == 1
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7N Follow-Through Transition Regime Matrix" in md


def test_transition_regime_cli_defaults_and_args():
    args = _parse_args(["--asset", "BNBUSDT", "--threshold", "0.25", "--action", "tag_only", "--min-transition-edge", "0.2"])
    assert args.asset == ["BNBUSDT"]
    assert args.threshold == [0.25]
    assert args.action == ["tag_only"]
    assert args.min_transition_edge == [0.2]

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.action == ["reverse_direction", "suppress", "tag_only"]
    assert defaults.min_transition_edge == [0.10, 0.18, 0.25]
