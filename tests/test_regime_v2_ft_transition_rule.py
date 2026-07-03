"""Tests for Phase 7L split-local transition rule."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_transition_rule import (
    apply_ft_transition_rule,
    build_ft_transition_rule_matrix_report,
    build_ft_transition_rule_report,
    build_ft_transition_rule_retest_report,
    render_ft_transition_rule_markdown,
)
from libs.models.regime_v2.scripts.report_ft_transition_rule import _parse_args


def _ohlcv(n: int = 12) -> pd.DataFrame:
    idx = pd.RangeIndex(0, n)
    close = [100 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [10] * n,
        },
        index=idx,
    )


def _analysis(n: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(n):
        rows.append(
            {
                "compression_score": 0.80,
                "pre_breakout_setup_score": 0.75,
                "displacement_breakout_score": 0.65,
                "post_breakout_retest_score": 0.50,
                "policy_breakout_setup_score": 0.70,
                "policy_displacement_breakout_score": 0.60,
                "policy_retest_breakout_score": 0.45,
                "false_breakout_risk": 0.20,
                "shock_risk": 0.10,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def _context(n: int = 12) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playbook_context_market_phase": "compressed_wait",
                "playbook_context_risk_state": "ok",
                "playbook_context_risk_score": 0.20,
                "playbook_context_dominant_playbook": "breakout",
                "playbook_context_horizon_bias": "wait_for_expansion",
                "playbook_context_alignment": "aligned",
                "playbook_context_conflict_tags": "",
                "playbook_context_conflict_count": 0,
                "playbook_context_is_confirmed": True,
                "playbook_context_score_breakout": 0.45,
            }
            for _ in range(n)
        ],
        index=pd.RangeIndex(0, n),
    )


def _states(n: int = 12) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "playbook_state": "WAIT_COMPRESSION",
                "playbook_state_group": "wait",
                "playbook_state_reason": "unit",
                "playbook_state_is_executable": False,
                "playbook_state_is_wait": True,
                "playbook_state_dominant_playbook": "breakout",
                "playbook_state_horizon_bias": "wait_for_expansion",
            }
            for _ in range(n)
        ],
        index=pd.RangeIndex(0, n),
    )


def _refined(n: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(n):
        split_2 = 3 <= i <= 5
        active = i in {1, 4, 8}
        rows.append(
            {
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_base": "WAIT_COMPRESSION",
                "playbook_state_group": "executable" if active else "wait",
                "playbook_state_reason": "breakout_followthrough_confirmed" if active else "unit",
                "playbook_state_is_executable": active,
                "playbook_state_is_wait": not active,
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "down" if active and split_2 else "up",
                "breakout_followthrough_score": 0.40,
                "breakout_followthrough_reversal_penalty": 0.70 if active and split_2 else 0.10,
                "breakout_followthrough_reason": "confirmed" if active else "inactive",
                "ft_context_gate_score": 0.75,
                "ft_context_gate_market_phase": "compressed_wait",
                "ft_context_gate_horizon_bias": "wait_for_expansion",
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def test_ft_transition_rule_reverses_only_target_split_direction():
    out = apply_ft_transition_rule(_refined(), split_count=4, target_split_indices=(2,), transition_directions=("down",))

    assert bool(out.loc[4, "ft_transition_rule_applied"]) is True
    assert out.loc[4, "ft_transition_rule_original_direction"] == "down"
    assert out.loc[4, "breakout_followthrough_direction"] == "up"
    assert out.loc[4, "breakout_followthrough_reason"] == "transition_reversal_confirmed"
    assert bool(out.loc[1, "ft_transition_rule_applied"]) is False
    assert out.loc[1, "breakout_followthrough_direction"] == "up"


def test_ft_transition_rule_can_suppress_matching_rows():
    out = apply_ft_transition_rule(_refined(), split_count=4, target_split_indices=(2,), transition_directions=("down",), action="suppress")

    assert bool(out.loc[4, "ft_transition_rule_applied"]) is True
    assert bool(out.loc[4, "breakout_followthrough_active"]) is False
    assert out.loc[4, "playbook_state"] == "WAIT_COMPRESSION"
    assert out.loc[4, "breakout_followthrough_reason"] == "transition_rule_suppressed"


def test_ft_transition_rule_report_and_markdown():
    out = apply_ft_transition_rule(_refined(), split_count=4, target_split_indices=(2,), transition_directions=("down",))
    report = build_ft_transition_rule_report(out, asset="BNBUSDT", timeframe="1h", threshold=0.25)
    md = render_ft_transition_rule_markdown(report)

    assert report["summary"]["applied_count"] == 1
    assert report["summary"]["active_total"] == 3
    assert report["summary"]["active_direction_distribution"] == {"up": 3}
    assert "# RegimeV2 Phase 7L Follow-Through Transition Rule" in md


def test_ft_transition_rule_retest_and_matrix_summary():
    one = build_ft_transition_rule_retest_report(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        asset="BNBUSDT",
        timeframe="1h",
        threshold=0.25,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        target_split_indices=(2,),
        transition_directions=("down",),
    )
    two = build_ft_transition_rule_retest_report(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        threshold=0.30,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        target_split_indices=(2,),
        transition_directions=("down",),
    )
    matrix = build_ft_transition_rule_matrix_report([one, two])
    md = render_ft_transition_rule_markdown(matrix)

    assert matrix["summary"]["variant_count"] == 2
    assert matrix["summary"]["thresholds"] == [0.25, 0.3]
    assert "# RegimeV2 Phase 7L Follow-Through Transition Rule Matrix" in md


def test_ft_transition_rule_cli_defaults_and_args():
    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--threshold",
            "0.25",
            "--split-count",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
            "--target-split",
            "2",
            "--transition-direction",
            "down",
            "--min-reversal-penalty",
            "0.65",
            "--min-transition-context-score",
            "0.72",
            "--allowed-market-phase",
            "compressed_wait",
            "--allowed-horizon-bias",
            "wait_for_expansion",
            "--action",
            "suppress",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.split_count == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]
    assert args.target_split == [2]
    assert args.transition_direction == ["down"]
    assert args.min_reversal_penalty == 0.65
    assert args.min_transition_context_score == 0.72
    assert args.allowed_market_phase == ["compressed_wait"]
    assert args.allowed_horizon_bias == ["wait_for_expansion"]
    assert args.action == "suppress"

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.target_split == [2]
    assert defaults.transition_direction == ["down"]
    assert defaults.action == "reverse_direction"
