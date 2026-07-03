"""Tests for Phase 7W transition micro-state robustness."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    MICRO_STATE_BREAKOUT_SETUP,
    MICRO_STATE_COMPRESSION_OBSERVE,
)
from libs.models.regime_v2.evaluation.playbook_transition_micro_state_robust import (
    build_micro_state_window_specs,
    build_transition_micro_state_robust_matrix_report,
    build_transition_micro_state_robust_report,
    render_transition_micro_state_robust_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_state_robust import _parse_args


def _micro_df() -> pd.DataFrame:
    rows = []
    for i in range(12):
        rows.append(
            {
                "breakout_transition_active": True,
                "breakout_transition_direction": "up" if i % 2 == 0 else "down",
                "breakout_transition_micro_state": MICRO_STATE_BREAKOUT_SETUP if i < 6 else MICRO_STATE_COMPRESSION_OBSERVE,
                "breakout_transition_micro_runtime_enabled": False,
            }
        )
    return pd.DataFrame(rows)


def _ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [100 + i for i in range(20)],
            "high": [101 + i for i in range(20)],
            "low": [99 + i for i in range(20)],
            "close": [100 + i for i in range(20)],
            "volume": [10] * 20,
        }
    )


def test_window_specs_include_full_and_rolling_windows():
    specs = build_micro_state_window_specs(720, window_size=360, step_size=180)
    assert specs[0]["window_id"] == "full"
    assert specs[1]["window_id"] == "w1_0_360"
    assert specs[-1]["end"] == 720


def test_micro_state_robust_report_matrix_and_markdown():
    report = build_transition_micro_state_robust_report(
        _micro_df(),
        _ohlcv(),
        asset="ETHUSDT",
        timeframe="1h",
        window_size=12,
        step_size=6,
        min_state_active=3,
        horizons=(1,),
        fees_bps=(0.0,),
    )
    matrix = build_transition_micro_state_robust_matrix_report([{"summary": report["summary"], "robust_report": report}])
    md = render_transition_micro_state_robust_markdown(matrix)

    assert report["summary"]["window_count"] >= 1
    assert report["summary"]["runtime_enabled_count"] == 0
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7W Micro-State Robustness Matrix" in md


def test_micro_state_robust_cli_defaults_and_args():
    args = _parse_args(["--asset", "ETHUSDT", "--window-size", "120", "--min-state-active", "4"])
    assert args.asset == ["ETHUSDT"]
    assert args.window_size == 120
    assert args.min_state_active == 4

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.output_json.endswith("phase7w_transition_micro_state_robust.json")
