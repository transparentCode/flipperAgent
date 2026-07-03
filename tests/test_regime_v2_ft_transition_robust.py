"""Tests for Phase 7M transition-rule robustness validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_transition_robust import (
    build_ft_transition_multi_asset_robust_report,
    build_ft_transition_robust_report,
    build_ft_transition_window_specs,
    render_ft_transition_robust_markdown,
)
from libs.models.regime_v2.scripts.report_ft_transition_robust import _parse_args


def _ohlcv(n: int = 16) -> pd.DataFrame:
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


def _analysis(n: int = 16) -> pd.DataFrame:
    rows = []
    for _ in range(n):
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


def _context(n: int = 16) -> pd.DataFrame:
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


def _states(n: int = 16) -> pd.DataFrame:
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


def test_ft_transition_window_specs_full_rolling_and_tail():
    specs = build_ft_transition_window_specs(10, window_size=4, step_size=3, include_full_window=True)

    assert specs[0]["window_id"] == "full"
    assert specs[0]["is_full"] is True
    assert {spec["window_id"] for spec in specs if not spec["is_full"]} >= {"w1_0_4", "w2_3_7", "w3_6_10"}
    assert all(spec["end_pos"] <= 10 for spec in specs)


def test_ft_transition_robust_report_smoke_and_markdown():
    report = build_ft_transition_robust_report(
        _analysis(),
        _context(),
        _states(),
        _ohlcv(),
        asset="BNBUSDT",
        timeframe="1h",
        thresholds=(0.25,),
        target_split_indices=(1, 2),
        actions=("reverse_direction",),
        window_size=8,
        step_size=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        min_applied_support=1,
    )
    md = render_ft_transition_robust_markdown(report)

    assert report["phase"] == "phase_7m_ft_transition_robustness"
    assert report["summary"]["asset"] == "BNBUSDT"
    assert report["summary"]["variant_count"] > 0
    assert report["summary"]["target_splits"] == [1, 2]
    assert "# RegimeV2 Phase 7M Follow-Through Transition Robustness" in md


def test_ft_transition_multi_asset_robust_report_combines_summaries():
    one = {
        "phase": "phase_7m_ft_transition_robustness",
        "summary": {
            "asset": "BNBUSDT",
            "timeframe": "1h",
            "robust_ready": True,
            "recommendation": "candidate_reusable_signature",
            "ready_rate": 0.7,
            "non_full_ready_rate": 0.6,
            "applied_support": 3,
        },
        "variants": [{"ready": True, "applied_count": 1}],
    }
    two = {
        "phase": "phase_7m_ft_transition_robustness",
        "summary": {
            "asset": "ETHUSDT",
            "timeframe": "1h",
            "robust_ready": False,
            "recommendation": "hold_off_transition_rule_not_robust",
            "ready_rate": 0.2,
            "non_full_ready_rate": 0.0,
            "applied_support": 0,
        },
        "variants": [{"ready": False, "applied_count": 0}],
    }
    combined = build_ft_transition_multi_asset_robust_report([one, two])
    md = render_ft_transition_robust_markdown(combined)

    assert combined["phase"] == "phase_7m_ft_transition_multi_asset_robustness"
    assert combined["summary"]["report_count"] == 2
    assert combined["summary"]["robust_ready_report_count"] == 1
    assert combined["summary"]["recommendation"] == "hold_off_transition_rule_not_robust"
    assert "# RegimeV2 Phase 7M Multi-Asset Transition Robustness" in md


def test_ft_transition_robust_cli_defaults_and_args():
    args = _parse_args(
        [
            "--asset",
            "BNBUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--threshold",
            "0.25",
            "--target-split",
            "2",
            "--action",
            "reverse_direction",
            "--transition-direction",
            "down",
            "--window-size",
            "120",
            "--step-size",
            "60",
            "--no-full-window",
            "--min-ready-rate",
            "0.7",
            "--min-non-full-ready-rate",
            "0.6",
            "--min-applied-support",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
        ]
    )
    assert args.asset == ["BNBUSDT"]
    assert args.timeframe == ["4h"]
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.target_split == [2]
    assert args.action == ["reverse_direction"]
    assert args.transition_direction == ["down"]
    assert args.window_size == 120
    assert args.step_size == 60
    assert args.no_full_window is True
    assert args.min_ready_rate == 0.7
    assert args.min_non_full_ready_rate == 0.6
    assert args.min_applied_support == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.timeframe == ["1h"]
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.target_split == [1, 2, 3, 4]
    assert defaults.action == ["reverse_direction", "suppress"]
