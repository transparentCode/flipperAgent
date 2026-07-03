"""Tests for Phase 7P setup-origin transition candidates."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_setup import (
    build_setup_transition_candidate_frame,
    build_setup_transition_candidate_report,
    build_setup_transition_matrix_report,
    render_setup_transition_markdown,
)
from libs.models.regime_v2.scripts.report_transition_setup import _parse_args


def _analysis() -> pd.DataFrame:
    return pd.DataFrame([{} for _ in range(8)])


def _context() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playbook_context_market_phase": "compressed_wait",
                "playbook_context_risk_state": "ok",
                "playbook_context_risk_score": 0.2,
                "playbook_context_dominant_playbook": "breakout",
                "playbook_context_horizon_bias": "wait_for_expansion",
                "playbook_context_alignment": "aligned",
                "playbook_context_conflict_tags": "",
                "playbook_context_conflict_count": 0,
                "playbook_context_is_active": True,
                "playbook_context_is_confirmed": True,
                "playbook_context_score_breakout": 0.8,
            }
            for _ in range(8)
        ]
    )


def _states() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playbook_state": "WAIT_COMPRESSION",
                "playbook_state_group": "wait",
                "playbook_state_reason": "unit",
                "playbook_state_is_executable": False,
                "playbook_state_is_wait": True,
            }
            for _ in range(8)
        ]
    )


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100, 100, 99, 98, 97, 96, 95, 94],
            "high": [101, 101, 100, 99, 98, 97, 96, 96],
            "low": [99, 98, 97, 96, 95, 94, 90, 92],
            "close": [100, 99, 98, 97, 96, 95, 95, 95],
            "volume": [10] * 8,
        }
    )


def test_setup_transition_candidate_frame_emits_separate_candidate():
    out = build_setup_transition_candidate_frame(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        lookback_bars=3,
        min_candidate_score=0.45,
        min_wick_score=0.10,
    )

    assert "breakout_transition_active" in out.columns
    assert int(out["breakout_transition_active"].sum()) >= 1
    assert set(out[out["breakout_transition_active"] == True]["breakout_transition_direction"]) <= {"up", "down"}
    assert "breakout_followthrough_active" in out.columns


def test_setup_transition_report_matrix_and_markdown():
    out = build_setup_transition_candidate_frame(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        lookback_bars=3,
        min_candidate_score=0.45,
        min_wick_score=0.10,
    )
    report = build_setup_transition_candidate_report(out, asset="BNBUSDT", timeframe="1h")
    matrix = build_setup_transition_matrix_report(
        [
            {
                "summary": {
                    "asset": "BNBUSDT",
                    "timeframe": "1h",
                    "active_count": report["summary"]["active_count"],
                    "state_distribution": report["summary"]["state_distribution"],
                    "direction_distribution": report["summary"]["direction_distribution"],
                    "passed_split_count": 1,
                    "split_count": 4,
                    "ready": False,
                    "recommendation": "unit",
                    "avg_split_directional_return": 0.1,
                    "worst_split_directional_return": -0.1,
                    "passing_cell_count": 1,
                },
                "candidate_report": report,
                "outcome_matrix": {"summary": {}},
                "walkforward_report": {"splits": []},
            }
        ]
    )
    md = render_setup_transition_markdown(matrix)

    assert report["summary"]["row_count"] == 8
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7P Setup Transition Matrix" in md


def test_setup_transition_cli_defaults_and_args():
    args = _parse_args(["--asset", "BNBUSDT", "--lookback-bars", "5", "--min-candidate-score", "0.6"])
    assert args.asset == ["BNBUSDT"]
    assert args.lookback_bars == [5]
    assert args.min_candidate_score == [0.6]

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.lookback_bars == [8, 12, 20]
    assert defaults.min_candidate_score == [0.58, 0.62, 0.66]
