"""Tests for Phase 7D playbook state-transition validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_state_transitions import (
    build_playbook_state_transition_matrix,
    label_playbook_state_transitions,
    render_playbook_state_transition_matrix_markdown,
)
from libs.models.regime_v2.scripts.report_playbook_state_transitions import _parse_args


def _state_row(state: str, group: str) -> dict:
    return {
        "playbook_state": state,
        "playbook_state_group": group,
        "playbook_state_reason": "unit",
        "playbook_state_dominant_playbook": "none",
        "playbook_state_market_phase": "neutral_context",
        "playbook_state_horizon_bias": "mid",
        "playbook_state_conflict_tags": "",
    }


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100, 101, 102, 103, 104, 105, 106, 107],
            "high": [101, 102, 103, 104, 105, 106, 107, 108],
            "low": [99, 100, 101, 102, 103, 104, 105, 106],
            "close": [100, 101, 103, 102, 106, 104, 108, 107],
            "volume": [1, 1, 1, 1, 1, 1, 1, 1],
        },
        index=pd.RangeIndex(0, 8),
    )


def test_transition_labeling_identifies_key_intents():
    states = pd.DataFrame(
        [
            _state_row("WAIT_COMPRESSION", "wait"),
            _state_row("BREAKOUT_SETUP", "wait"),
            _state_row("SCALP_ONLY", "executable"),
            _state_row("NO_TRADE_RISK", "risk"),
            _state_row("SCALP_ONLY", "executable"),
            _state_row("WAIT_COMPRESSION", "wait"),
        ],
        index=[0, 1, 2, 3, 4, 5],
    )

    labeled = label_playbook_state_transitions(states, _ohlcv(), transition_bars=1, outcome_horizon_bars=2)

    assert labeled[0]["transition_intent"] == "compression_to_setup"
    assert labeled[2]["transition_intent"] == "scalp_exit"
    assert labeled[3]["transition_intent"] == "risk_recovery"
    assert labeled[0]["state_changed"] is True
    assert labeled[0]["outcome_label"] == "labeled"


def test_transition_matrix_segments_and_summary():
    states = pd.DataFrame(
        [
            _state_row("WAIT_COMPRESSION", "wait"),
            _state_row("BREAKOUT_SETUP", "wait"),
            _state_row("SCALP_ONLY", "executable"),
            _state_row("NO_TRADE_RISK", "risk"),
            _state_row("SCALP_ONLY", "executable"),
            _state_row("WAIT_COMPRESSION", "wait"),
        ],
        index=[0, 1, 2, 3, 4, 5],
    )

    matrix = build_playbook_state_transition_matrix(
        states,
        _ohlcv(),
        transition_bars=(1, 2),
        outcome_horizons=(2,),
        large_move_bps=10,
    )

    assert matrix["summary"]["cell_count"] == 2
    first = matrix["cells"][0]
    assert first["segments"]["wait_to_any"]["count"] >= 1
    assert first["segments"]["wait_to_setup"]["count"] == 1
    assert first["segments"]["scalp_exit"]["count"] >= 1
    assert matrix["summary"]["wait_large_move_cell"] is not None


def test_transition_markdown_and_cli_defaults():
    states = pd.DataFrame([_state_row("WAIT_COMPRESSION", "wait"), _state_row("BREAKOUT_SETUP", "wait")], index=[0, 1])
    matrix = build_playbook_state_transition_matrix(states, _ohlcv(), transition_bars=(1,), outcome_horizons=(1,))
    md = render_playbook_state_transition_matrix_markdown(matrix)
    assert "# RegimeV2 Phase 7D Playbook State Transition Matrix" in md
    assert "Highest wait large-move cell" in md

    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--transition-bars",
            "3",
            "--outcome-horizon",
            "12",
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
    assert args.transition_bars == [3]
    assert args.outcome_horizon == [12]
    assert args.large_move_bps == 15

    defaults = _parse_args([])
    assert defaults.transition_bars == [1, 3, 6]
    assert defaults.outcome_horizon == [3, 6, 12, 24]
