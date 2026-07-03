"""Tests for Phase 7I follow-through failure diagnostics."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_diag import (
    build_ft_failure_diagnostics,
    build_ft_failure_diagnostics_matrix,
    render_ft_failure_diagnostics_markdown,
)
from libs.models.regime_v2.scripts.report_ft_diag import _parse_args


def _ohlcv(n: int = 12, falling: bool = False) -> pd.DataFrame:
    idx = pd.RangeIndex(0, n)
    close = [100 - i if falling else 100 + i for i in range(n)]
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
    for i in range(n):
        active = i in {0, 1, 3, 4, 6, 7, 9, 10}
        rows.append(
            {
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "up" if active else "none",
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_base": "BREAKOUT_SETUP" if active else "WAIT_COMPRESSION",
                "breakout_followthrough_hold_score": 0.30 if i in {3, 4} else 0.80,
                "breakout_followthrough_follow_score": 0.30 if i in {3, 4} else 0.80,
                "breakout_followthrough_direction_return_score": 0.20 if i in {3, 4} else 0.80,
                "breakout_followthrough_reversal_penalty": 0.60 if i in {3, 4} else 0.10,
                "breakout_followthrough_false_risk": 0.20,
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def test_ft_failure_diagnostics_identifies_target_failed_split():
    report = build_ft_failure_diagnostics(
        _state_df(),
        _ohlcv(falling=True),
        asset="BNBUSDT",
        timeframe="1h",
        threshold=0.25,
        split_count=4,
        failed_split_indices=(2,),
        horizons=(1,),
        fees_bps=(2.0,),
    )

    assert report["summary"]["target_failed_split_count"] == 1
    assert report["summary"]["target_active_total"] == 2
    split2 = report["splits"][1]
    assert split2["target_failed_split"] is True
    assert "weak_boundary_hold" in split2["hypotheses"]
    assert "high_reversal_pressure" in split2["hypotheses"]


def test_ft_failure_diagnostics_matrix_and_markdown():
    one = build_ft_failure_diagnostics(
        _state_df(),
        _ohlcv(falling=True),
        threshold=0.25,
        split_count=4,
        failed_split_indices=(2, 3),
        horizons=(1,),
        fees_bps=(2.0,),
    )
    two = build_ft_failure_diagnostics(
        _state_df(),
        _ohlcv(falling=True),
        threshold=0.30,
        split_count=4,
        failed_split_indices=(2, 3),
        horizons=(1,),
        fees_bps=(2.0,),
    )
    matrix = build_ft_failure_diagnostics_matrix([one, two])
    md = render_ft_failure_diagnostics_markdown(matrix)

    assert matrix["summary"]["variant_count"] == 2
    assert matrix["summary"]["thresholds"] == [0.25, 0.3]
    assert "# RegimeV2 Phase 7I Failure Diagnostics Matrix" in md


def test_ft_diag_cli_defaults_and_args():
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
            "--failed-split",
            "2",
            "--split-count",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "5",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.failed_split == [2]
    assert args.split_count == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.failed_split == [2, 3]
