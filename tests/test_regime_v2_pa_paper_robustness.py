"""Tests for Phase 6M PA paper robustness."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.pa_paper_robust import _parse_args
from libs.selection.regime_v2_pa_paper_robustness import (
    build_pa_paper_robustness_report,
    render_pa_paper_robustness_markdown,
)


def _record(timestamp: float, *, active: bool = True, changed: bool = True) -> dict:
    return {
        "asset": "BNBUSDT",
        "timeframe": "1h",
        "timestamp": timestamp,
        "paper_active": active,
        "selection_changed": changed,
        "baseline_selected_model": "PriceAction",
        "paper_selected_model": None if changed else "PriceAction",
        "baseline_selected_direction": 1,
        "paper_selected_direction": None if changed else 1,
    }


def _ohlcv(down: bool = True) -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0], unit="s", utc=True)
    close = [100.0, 90.0, 80.0, 70.0, 60.0, 50.0] if down else [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close, "volume": [1.0] * len(close)},
        index=index,
    )


def test_pa_paper_robustness_passes_when_cells_and_rolling_positive():
    records = [_record(1000.0), _record(1001.0), _record(1002.0), _record(1003.0)]

    report = build_pa_paper_robustness_report(
        records,
        {("BNBUSDT", "1h"): _ohlcv(down=True)},
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(2,),
        min_window=1,
        min_support=3,
        passing_cell_floor=1,
        max_negative_cells=0,
        rolling_stable_floor=1,
        min_positive_rate=0.6,
    )

    assert report["summary"]["candidate_count"] == 4
    assert report["summary"]["passing_cell_count"] == 1
    assert report["summary"]["negative_cell_count"] == 0
    assert report["summary"]["rolling_stable_cell_count"] == 1
    assert report["summary"]["paper_ready"] is True
    assert report["cells"][0]["status"] == "pass"


def test_pa_paper_robustness_fails_when_lift_negative():
    records = [_record(1000.0), _record(1001.0), _record(1002.0)]

    report = build_pa_paper_robustness_report(
        records,
        {("BNBUSDT", "1h"): _ohlcv(down=False)},
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(2,),
        min_window=1,
        min_support=1,
        passing_cell_floor=1,
        max_negative_cells=0,
        rolling_stable_floor=1,
        min_positive_rate=0.6,
    )

    assert report["summary"]["paper_ready"] is False
    assert report["summary"]["negative_cell_count"] == 1
    assert "avg_lift_below_zero" in report["cells"][0]["failure_reasons"]


def test_pa_paper_robustness_markdown_and_cli_defaults():
    report = build_pa_paper_robustness_report(
        [_record(1000.0)],
        {("BNBUSDT", "1h"): _ohlcv(down=True)},
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(1,),
        min_window=1,
    )
    md = render_pa_paper_robustness_markdown(report)
    assert "# RegimeV2 Phase 6M PA Paper Robustness Report" in md
    assert "## Cells" in md

    args = _parse_args([])
    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
    assert args.rolling_window == [20, 30, 50]
    assert args.min_support == 30
