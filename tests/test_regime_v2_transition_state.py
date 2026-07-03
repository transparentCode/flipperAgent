"""Tests for Phase 7O separate breakout transition states."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_state import (
    STATE_BREAKOUT_EXHAUSTION_TRANSITION,
    STATE_FAILED_BREAKOUT_REVERSAL_SETUP,
    build_breakout_transition_outcome_matrix,
    build_breakout_transition_state_frame,
    build_breakout_transition_state_matrix_report,
    build_breakout_transition_state_report,
    label_breakout_transition_outcomes,
    render_breakout_transition_state_markdown,
)
from libs.models.regime_v2.scripts.report_transition_state import _parse_args


def _refined() -> pd.DataFrame:
    rows = []
    for i in range(4):
        weak = i == 2
        active = i in {1, 2, 3}
        rows.append(
            {
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_base": "WAIT_COMPRESSION",
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "down" if weak else "up",
                "breakout_followthrough_score": 0.35,
                "breakout_followthrough_follow_score": 0.25 if weak else 1.0,
                "breakout_followthrough_hold_score": 0.20 if weak else 1.0,
                "breakout_followthrough_direction_return_score": 0.20 if weak else 1.0,
                "breakout_followthrough_reversal_penalty": 0.75 if weak else 0.10,
                "breakout_followthrough_false_risk": 0.20,
                "breakout_followthrough_shock_risk": 0.10,
                "ft_context_gate_score": 0.76,
                "ft_context_gate_market_phase": "compressed_wait",
                "ft_context_gate_horizon_bias": "wait_for_expansion",
            }
        )
    return pd.DataFrame(rows)


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104],
            "high": [101, 102, 103, 104, 105],
            "low": [99, 100, 101, 102, 103],
            "close": [100, 101, 102, 104, 106],
            "volume": [10, 10, 10, 10, 10],
        }
    )


def test_breakout_transition_state_frame_separate_state():
    out = build_breakout_transition_state_frame(_refined(), min_transition_score=0.50, max_continuation_score=0.90)

    assert bool(out.loc[2, "breakout_transition_active"]) is True
    assert out.loc[2, "breakout_transition_state"] in {
        STATE_BREAKOUT_EXHAUSTION_TRANSITION,
        STATE_FAILED_BREAKOUT_REVERSAL_SETUP,
    }
    assert out.loc[2, "breakout_transition_direction"] == "up"
    assert out.loc[2, "playbook_state"] == "BREAKOUT_CONFIRMATION"
    assert bool(out.loc[1, "breakout_transition_active"]) is False


def test_transition_state_outcomes_report_matrix_and_markdown():
    out = build_breakout_transition_state_frame(_refined(), min_transition_score=0.50, max_continuation_score=0.90)
    report = build_breakout_transition_state_report(out, asset="BNBUSDT", timeframe="1h", threshold=0.25)
    labels = label_breakout_transition_outcomes(out, _ohlcv(), horizon_bars=1, fee_bps=2.0)
    matrix = build_breakout_transition_outcome_matrix(out, _ohlcv(), horizons=(1,), fees_bps=(2.0,))
    summary = build_breakout_transition_state_matrix_report(
        [
            {
                "summary": {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "threshold": 0.25,
                    "active_count": 1,
                    "state_distribution": report["summary"]["state_distribution"],
                    "passed_split_count": 1,
                    "split_count": 4,
                    "ready": False,
                    "recommendation": "unit",
                    "avg_split_directional_return": 0.1,
                    "worst_split_directional_return": 0.01,
                    "passing_cell_count": 1,
                },
                "transition_state_report": report,
                "outcome_matrix": matrix,
                "walkforward_report": {"splits": []},
            }
        ]
    )
    md = render_breakout_transition_state_markdown(summary)

    assert report["summary"]["active_count"] == 1
    assert labels[0]["outcome_label"] == "labeled"
    assert matrix["summary"]["cell_count"] == 1
    assert summary["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7O Breakout Transition-State Matrix" in md


def test_transition_state_cli_defaults_and_args():
    args = _parse_args(["--asset", "BNBUSDT", "--threshold", "0.25", "--min-transition-score", "0.5", "--max-continuation-score", "0.8"])
    assert args.asset == ["BNBUSDT"]
    assert args.threshold == [0.25]
    assert args.min_transition_score == [0.5]
    assert args.max_continuation_score == [0.8]

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.min_transition_score == [0.52, 0.58, 0.64]
    assert defaults.max_continuation_score == [0.72, 0.78]
