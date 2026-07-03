"""Tests for Phase 7H follow-through walk-forward validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_wf import (
    build_ft_walkforward_matrix_report,
    build_ft_walkforward_report,
    render_ft_walkforward_markdown,
)
from libs.models.regime_v2.scripts.report_ft_wf import _parse_args


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
    for i in range(n):
        active = i in {0, 1, 3, 4, 6, 7, 9, 10}
        rows.append(
            {
                "breakout_followthrough_active": active,
                "breakout_followthrough_direction": "up" if active else "none",
                "playbook_state": "BREAKOUT_CONFIRMATION" if active else "WAIT_COMPRESSION",
                "playbook_state_group": "executable" if active else "wait",
            }
        )
    return pd.DataFrame(rows, index=pd.RangeIndex(0, n))


def test_ft_walkforward_passes_stable_splits():
    report = build_ft_walkforward_report(
        _state_df(),
        _ohlcv(),
        asset="BNBUSDT",
        timeframe="1h",
        threshold=0.25,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=2,
        min_passing_rate=0.5,
    )

    assert report["summary"]["split_count"] == 4
    assert report["summary"]["passed_split_count"] == 4
    assert report["summary"]["ready"] is True
    assert report["summary"]["active_total"] == 8


def test_ft_walkforward_fails_low_support_split():
    state = _state_df()
    state.loc[6:11, "breakout_followthrough_active"] = False
    state.loc[6:11, "breakout_followthrough_direction"] = "none"
    report = build_ft_walkforward_report(
        state,
        _ohlcv(),
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=2,
    )

    assert report["summary"]["ready"] is False
    assert report["summary"]["support_failure_count"] >= 1
    assert any("low_support" in split["failure_reasons"] for split in report["splits"])


def test_ft_walkforward_matrix_markdown_and_cli_defaults():
    one = build_ft_walkforward_report(
        _state_df(),
        _ohlcv(),
        threshold=0.25,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=2,
        min_passing_rate=0.5,
    )
    two = build_ft_walkforward_report(
        _state_df(),
        _ohlcv(),
        threshold=0.30,
        split_count=4,
        horizons=(1,),
        fees_bps=(2.0,),
        min_split_support=2,
        min_passing_rate=0.5,
    )
    matrix = build_ft_walkforward_matrix_report([one, two])
    md = render_ft_walkforward_markdown(matrix)
    assert matrix["summary"]["variant_count"] == 2
    assert "# RegimeV2 Phase 7H Follow-Through Walk-Forward Matrix" in md

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
            "--min-split-support",
            "1",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.threshold == [0.25]
    assert args.split_count == 3
    assert args.horizon == [12]
    assert args.fee_bps == [5.0]
    assert args.min_split_support == 1

    defaults = _parse_args([])
    assert defaults.asset == "BNBUSDT"
    assert defaults.timeframe == "1h"
    assert defaults.threshold == [0.25, 0.30]
    assert defaults.horizon == [3, 6, 12, 24]
