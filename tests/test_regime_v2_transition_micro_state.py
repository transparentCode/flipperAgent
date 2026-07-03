"""Tests for Phase 7V transition micro-state split."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    MICRO_STATE_BREAKOUT_SETUP,
    MICRO_STATE_COMPRESSION_OBSERVE,
    build_transition_micro_state_frame,
    build_transition_micro_state_matrix_report,
    build_transition_micro_state_report,
    render_transition_micro_state_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_state import _parse_args


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "breakout_transition_active": True,
                "breakout_transition_direction": "up",
                "breakout_transition_score": 0.7,
                "ft_context_gate_market_phase": "breakout_setup",
            },
            {
                "breakout_transition_active": True,
                "breakout_transition_direction": "down",
                "breakout_transition_score": 0.65,
                "ft_context_gate_market_phase": "compressed_wait",
            },
            {
                "breakout_transition_active": False,
                "breakout_transition_direction": "none",
                "breakout_transition_score": 0.0,
                "ft_context_gate_market_phase": "breakout_setup",
            },
        ]
    )


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [101, 102, 103, 104, 105, 106],
            "volume": [10] * 6,
        }
    )


def test_transition_micro_state_frame_splits_runtime_disabled_states():
    out = build_transition_micro_state_frame(_candidates())

    assert out.loc[0, "breakout_transition_micro_state"] == MICRO_STATE_BREAKOUT_SETUP
    assert out.loc[1, "breakout_transition_micro_state"] == MICRO_STATE_COMPRESSION_OBSERVE
    assert bool(out.loc[0, "breakout_transition_micro_is_research_candidate"]) is True
    assert bool(out.loc[1, "breakout_transition_micro_is_observation_only"]) is True
    assert int(out["breakout_transition_micro_runtime_enabled"].sum()) == 0


def test_transition_micro_state_report_matrix_and_markdown():
    frame = build_transition_micro_state_frame(_candidates())
    report = build_transition_micro_state_report(frame, _ohlcv(), asset="ETHUSDT", timeframe="1h", horizons=(1,), fees_bps=(0.0,))
    matrix = build_transition_micro_state_matrix_report(
        [
            {
                "summary": report["summary"],
                "micro_state_report": report,
            }
        ]
    )
    md = render_transition_micro_state_markdown(matrix)

    assert report["summary"]["runtime_enabled_count"] == 0
    assert report["summary"]["research_candidate_count"] == 1
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7V Transition Micro-State Matrix" in md


def test_transition_micro_state_cli_defaults_and_args():
    args = _parse_args(["--asset", "ETHUSDT", "--lookback-bars", "12", "--min-candidate-score", "0.6"])
    assert args.asset == ["ETHUSDT"]
    assert args.lookback_bars == 12
    assert args.min_candidate_score == 0.6

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.output_json.endswith("phase7v_transition_micro_state.json")
