"""Tests for Phase 7E breakout-confirmation refinement."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_confirmation import (
    build_breakout_confirmation_frame,
    build_breakout_confirmation_report,
    render_breakout_confirmation_markdown,
)
from libs.models.regime_v2.scripts.report_breakout_confirmation import _parse_args


def _analysis() -> pd.DataFrame:
    idx = pd.RangeIndex(0, 8)
    return pd.DataFrame(
        {
            "displacement_breakout_score": [0.0, 0.0, 0.0, 0.0, 0.55, 0.60, 0.65, 0.10],
            "post_breakout_retest_score": [0.0, 0.0, 0.0, 0.0, 0.10, 0.15, 0.20, 0.0],
            "policy_retest_breakout_score": [0.0, 0.0, 0.0, 0.0, 0.10, 0.15, 0.20, 0.0],
            "range_expansion_z": [0.0, 0.0, 0.0, 0.0, 1.5, 2.0, 2.5, 0.0],
            "false_breakout_risk": [0.2] * 8,
            "shock_risk": [0.1] * 8,
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
            "open": [100, 100, 100, 100, 105, 108, 110, 109],
            "high": [101, 101, 101, 101, 106, 109, 111, 110],
            "low": [99, 99, 99, 99, 104, 107, 109, 108],
            "close": [100, 100, 100, 100, 105, 108, 110, 109],
            "volume": [10, 10, 10, 10, 40, 50, 60, 20],
        },
        index=idx,
    )


def test_breakout_confirmation_promotes_eligible_setup_rows():
    refined = build_breakout_confirmation_frame(
        _analysis(),
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        min_confirmation_score=0.20,
        max_false_breakout_risk=0.65,
    )

    assert refined["breakout_confirmation_active"].sum() >= 1
    confirmed = refined[refined["breakout_confirmation_active"] == True]
    assert set(confirmed["playbook_state"]) == {"BREAKOUT_CONFIRMATION"}
    assert set(confirmed["playbook_state_group"]) == {"executable"}
    assert set(confirmed["breakout_confirmation_direction"]) == {"up"}


def test_breakout_confirmation_blocks_noneligible_and_risky_rows():
    analysis = _analysis()
    analysis.loc[5, "false_breakout_risk"] = 0.90
    refined = build_breakout_confirmation_frame(
        analysis,
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        min_confirmation_score=0.20,
        max_false_breakout_risk=0.65,
    )

    assert refined.loc[7, "breakout_confirmation_reason"] == "not_eligible_state"
    assert refined.loc[5, "breakout_confirmation_reason"] in {"false_breakout_risk_high", "score_below_threshold"}


def test_breakout_confirmation_report_markdown_and_cli_defaults():
    refined = build_breakout_confirmation_frame(
        _analysis(),
        _states(),
        _ohlcv(),
        breakout_window=3,
        hold_bars=2,
        min_confirmation_score=0.20,
    )
    report = build_breakout_confirmation_report(refined, asset="BNBUSDT", timeframe="1h", source="unit")
    md = render_breakout_confirmation_markdown(report)
    assert report["summary"]["row_count"] == 8
    assert "# RegimeV2 Phase 7E Breakout Confirmation Refinement" in md

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
            "--min-confirmation-score",
            "0.4",
            "--max-false-breakout-risk",
            "0.5",
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
    assert args.min_confirmation_score == 0.4
    assert args.max_false_breakout_risk == 0.5
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.fee_bps == [2.0, 5.0, 10.0]
