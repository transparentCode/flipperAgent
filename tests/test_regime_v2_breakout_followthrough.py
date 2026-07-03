"""Tests for Phase 7F directional breakout follow-through refinement."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import (
    build_breakout_followthrough_frame,
    build_breakout_followthrough_outcome_matrix,
    build_breakout_followthrough_report,
    label_breakout_followthrough_outcomes,
    render_breakout_followthrough_markdown,
    render_breakout_followthrough_outcome_markdown,
)
from libs.models.regime_v2.scripts.report_breakout_followthrough import _parse_args


def _analysis() -> pd.DataFrame:
    idx = pd.RangeIndex(0, 8)
    return pd.DataFrame(
        {
            "displacement_breakout_score": [0.0, 0.0, 0.0, 0.0, 0.65, 0.70, 0.75, 0.0],
            "post_breakout_retest_score": [0.0, 0.0, 0.0, 0.0, 0.10, 0.20, 0.20, 0.0],
            "false_breakout_risk": [0.10] * 8,
            "shock_risk": [0.05] * 8,
        },
        index=idx,
    )


def _states() -> pd.DataFrame:
    idx = pd.RangeIndex(0, 8)
    return pd.DataFrame(
        {
            "playbook_state": ["WAIT_COMPRESSION", "WAIT_COMPRESSION", "WAIT_COMPRESSION", "BREAKOUT_SETUP", "BREAKOUT_SETUP", "BREAKOUT_SETUP", "BREAKOUT_SETUP", "NO_TRADE_RISK"],
            "playbook_state_group": ["wait", "wait", "wait", "wait", "wait", "wait", "wait", "risk"],
            "playbook_state_reason": ["unit"] * 8,
            "playbook_state_is_executable": [False] * 8,
            "playbook_state_is_wait": [True, True, True, True, True, True, True, False],
            "playbook_state_dominant_playbook": ["none"] * 8,
        },
        index=idx,
    )


def _ohlcv() -> pd.DataFrame:
    idx = pd.RangeIndex(0, 8)
    return pd.DataFrame(
        {
            "open": [100, 100, 100, 100, 105, 108, 111, 112],
            "high": [101, 101, 101, 101, 106, 109, 112, 113],
            "low": [99, 99, 99, 99, 104, 107, 110, 111],
            "close": [100, 100, 100, 100, 105, 108, 111, 112],
            "volume": [10, 10, 10, 10, 40, 50, 60, 40],
        },
        index=idx,
    )


def test_followthrough_promotes_directional_continuation_rows():
    refined = build_breakout_followthrough_frame(
        _analysis(),
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        follow_bars=2,
        min_followthrough_score=0.15,
        max_false_breakout_risk=0.65,
    )

    active = refined[refined["breakout_followthrough_active"] == True]
    assert len(active) >= 1
    assert set(active["playbook_state"]) == {"BREAKOUT_CONFIRMATION"}
    assert set(active["breakout_followthrough_direction"]) == {"up"}
    assert set(active["playbook_state_group"]) == {"executable"}


def test_followthrough_directional_outcomes_are_side_adjusted():
    refined = build_breakout_followthrough_frame(
        _analysis(),
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        follow_bars=2,
        min_followthrough_score=0.15,
    )

    labeled = label_breakout_followthrough_outcomes(refined, _ohlcv(), horizon_bars=1, fee_bps=2)

    assert len(labeled) >= 1
    assert labeled[0]["side"] == 1
    assert labeled[0]["directional_net_return"] is not None
    assert labeled[0]["outcome_label"] == "labeled"


def test_followthrough_report_matrix_markdown_and_cli_defaults():
    refined = build_breakout_followthrough_frame(
        _analysis(),
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        follow_bars=2,
        min_followthrough_score=0.15,
    )
    report = build_breakout_followthrough_report(refined, asset="BNBUSDT", timeframe="1h", source="unit")
    matrix = build_breakout_followthrough_outcome_matrix(refined, _ohlcv(), horizons=(1,), fees_bps=(2.0,))
    assert report["summary"]["row_count"] == 8
    assert matrix["summary"]["cell_count"] == 1
    assert "# RegimeV2 Phase 7F Breakout Follow-Through Refinement" in render_breakout_followthrough_markdown(report)
    assert "# RegimeV2 Phase 7F Breakout Follow-Through Outcomes" in render_breakout_followthrough_outcome_markdown(matrix)

    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--breakout-window",
            "10",
            "--hold-bars",
            "3",
            "--follow-bars",
            "4",
            "--min-followthrough-score",
            "0.3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.breakout_window == 10
    assert args.hold_bars == 3
    assert args.follow_bars == 4
    assert args.min_followthrough_score == 0.3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.fee_bps == [2.0, 5.0, 10.0]
