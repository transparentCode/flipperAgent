"""Tests for Phase 7C playbook state-outcome validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_state_outcomes import (
    build_playbook_state_outcome_matrix,
    label_playbook_state_outcomes,
    render_playbook_state_outcome_matrix_markdown,
)
from libs.models.regime_v2.scripts.report_playbook_state_outcomes import _parse_args


def _state_row(state: str, group: str, phase: str = "neutral_context") -> dict:
    return {
        "playbook_state": state,
        "playbook_state_group": group,
        "playbook_state_reason": "unit",
        "playbook_state_dominant_playbook": "trend" if state == "TREND_CONTINUATION" else "none",
        "playbook_state_market_phase": phase,
        "playbook_state_horizon_bias": "long" if state == "TREND_CONTINUATION" else "mid",
        "playbook_state_conflict_tags": "",
    }


def _ohlcv() -> pd.DataFrame:
    idx = pd.RangeIndex(0, 6)
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [100, 102, 101, 105, 103, 107],
            "volume": [1, 1, 1, 1, 1, 1],
        },
        index=idx,
    )


def test_state_outcome_labeling_and_directional_trend():
    state_df = pd.DataFrame(
        [
            _state_row("TREND_CONTINUATION", "executable", "bull_trend"),
            _state_row("NO_TRADE_RISK", "risk"),
        ],
        index=[0, 1],
    )

    labeled = label_playbook_state_outcomes(state_df, _ohlcv(), horizon_bars=2, fee_bps=10)

    assert len(labeled) == 2
    assert labeled[0]["outcome_label"] == "labeled"
    assert labeled[0]["implied_side"] == 1
    assert labeled[0]["directional_net_return"] is not None
    assert labeled[1]["implied_side"] == 0
    assert labeled[1]["directional_net_return"] is None


def test_state_outcome_matrix_segments_and_summary():
    state_df = pd.DataFrame(
        [
            _state_row("NO_TRADE_RISK", "risk"),
            _state_row("WAIT_COMPRESSION", "wait"),
            _state_row("SCALP_ONLY", "executable"),
            _state_row("RANGE_REVERSION", "executable"),
        ],
        index=[0, 1, 2, 3],
    )

    matrix = build_playbook_state_outcome_matrix(
        state_df,
        _ohlcv(),
        horizons=(1, 2),
        fees_bps=(2.0,),
        large_move_bps=10,
    )

    assert matrix["summary"]["cell_count"] == 2
    first = matrix["cells"][0]
    assert first["segments"]["risk"]["count"] == 1
    assert first["segments"]["wait"]["count"] == 1
    assert first["segments"]["executable"]["count"] == 2
    assert first["segments"]["scalp_only"]["count"] == 1
    assert matrix["summary"]["best_executable_cell"] is not None


def test_state_outcome_markdown_and_cli_defaults():
    state_df = pd.DataFrame([_state_row("NO_TRADE_RISK", "risk")], index=[0])
    matrix = build_playbook_state_outcome_matrix(state_df, _ohlcv(), horizons=(1,), fees_bps=(2.0,))
    md = render_playbook_state_outcome_matrix_markdown(matrix)
    assert "# RegimeV2 Phase 7C Playbook State Outcome Matrix" in md
    assert "Best executable cell" in md

    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--horizon",
            "3",
            "--fee-bps",
            "2",
            "--large-move-bps",
            "15",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.horizon == [3]
    assert args.fee_bps == [2.0]
    assert args.large_move_bps == 15

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.fee_bps == [2.0, 5.0, 10.0]
