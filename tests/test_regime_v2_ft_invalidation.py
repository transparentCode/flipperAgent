"""Tests for Phase 7J follow-through invalidation/cooldown retests."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_invalidation import (
    apply_ft_invalidation_filter,
    build_ft_invalidation_matrix_report,
    build_ft_invalidation_report,
    build_ft_invalidation_retest_report,
    render_ft_invalidation_markdown,
)
from libs.models.regime_v2.scripts.report_ft_invalidation import _parse_args


def _ohlcv(n: int = 12) -> pd.DataFrame:
    idx = pd.RangeIndex(0, n)
    close = [100 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1 for value in close],
            "low": [value - 1 for value in close],
            "close": close,
            "volume": [1] * n,
        },
        index=idx,
    )


def _state_df(n: int = 12) -> pd.DataFrame:
    rows = []
    active_indices = {0, 1, 3, 4, 6, 7, 9, 10}
    for i in range(n):
        active = i in active_indices
        bad = i == 3
        rows.append(
            {
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "up" if active else "none",
                "breakout_followthrough_score": 0.40 if active else 0.0,
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_group": "executable" if active else "wait",
                "playbook_state_base": "BREAKOUT_SETUP" if active else "WAIT_COMPRESSION",
                "playbook_state_is_executable": active,
                "breakout_followthrough_hold_score": 0.25 if bad else 0.80,
                "breakout_followthrough_follow_score": 0.25 if bad else 0.80,
                "breakout_followthrough_direction_return_score": 0.20 if bad else 0.80,
                "breakout_followthrough_reversal_penalty": 0.70 if bad else 0.10,
                "breakout_followthrough_false_risk": 0.20,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def test_ft_invalidation_deactivates_bad_row_and_direction_cooldown():
    filtered = apply_ft_invalidation_filter(_state_df(), cooldown_bars=2)

    assert bool(filtered.loc[3, "breakout_followthrough_active"]) is False
    assert bool(filtered.loc[3, "breakout_followthrough_invalidated"]) is True
    assert "weak_boundary_hold" in filtered.loc[3, "breakout_followthrough_invalidation_tags"]
    assert "high_reversal_pressure" in filtered.loc[3, "breakout_followthrough_invalidation_tags"]
    assert bool(filtered.loc[4, "breakout_followthrough_active"]) is False
    assert bool(filtered.loc[4, "breakout_followthrough_cooldown_suppressed"]) is True
    assert filtered.loc[4, "breakout_followthrough_invalidation_reason"] == "cooldown_suppressed"
    assert bool(filtered.loc[6, "breakout_followthrough_active"]) is True


def test_ft_invalidation_report_counts_removed_rows_and_markdown():
    filtered = apply_ft_invalidation_filter(_state_df(), cooldown_bars=2)
    report = build_ft_invalidation_report(filtered, asset="BNBUSDT", timeframe="1h", threshold=0.25)
    md = render_ft_invalidation_markdown(report)

    assert report["summary"]["active_before"] == 8
    assert report["summary"]["active_after"] == 6
    assert report["summary"]["invalidated_count"] == 1
    assert report["summary"]["cooldown_suppressed_count"] == 1
    assert "# RegimeV2 Phase 7J Follow-Through Invalidation Filter" in md


def test_ft_invalidation_retest_and_matrix_summary():
    one = build_ft_invalidation_retest_report(
        _state_df(),
        _ohlcv(),
        asset="BNBUSDT",
        timeframe="1h",
        threshold=0.25,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        cooldown_bars=2,
    )
    two = build_ft_invalidation_retest_report(
        _state_df(),
        _ohlcv(),
        threshold=0.30,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=1,
        min_passing_rate=0.5,
        cooldown_bars=2,
    )
    matrix = build_ft_invalidation_matrix_report([one, two])
    md = render_ft_invalidation_markdown(matrix)

    assert one["summary"]["removed_count"] == 2
    assert one["summary"]["active_after"] == 6
    assert matrix["summary"]["variant_count"] == 2
    assert matrix["summary"]["thresholds"] == [0.25, 0.3]
    assert "# RegimeV2 Phase 7J Follow-Through Invalidation Matrix" in md


def test_ft_invalidation_cli_defaults_and_args():
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
            "--min-hold-score",
            "0.55",
            "--max-reversal-penalty",
            "0.30",
            "--cooldown-bars",
            "4",
            "--global-cooldown",
            "--blocked-direction",
            "down",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.split_count == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]
    assert args.min_hold_score == 0.55
    assert args.max_reversal_penalty == 0.30
    assert args.cooldown_bars == 4
    assert args.global_cooldown is True
    assert args.blocked_direction == ["down"]

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.cooldown_bars == 3
    assert defaults.blocked_direction == []
