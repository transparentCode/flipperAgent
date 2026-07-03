"""Tests for Phase 7Y transition micro-state context diagnostics."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    MICRO_STATE_BREAKOUT_SETUP,
    MICRO_STATE_COMPRESSION_OBSERVE,
)
from libs.models.regime_v2.evaluation.playbook_transition_micro_state_context_diag import (
    build_transition_micro_state_context_diag_matrix_report,
    build_transition_micro_state_context_diag_report,
    render_transition_micro_state_context_diag_markdown,
)
from libs.models.regime_v2.scripts.report_transition_micro_state_context_diag import _parse_args


def _micro_df() -> pd.DataFrame:
    rows = []
    for i in range(8):
        rows.append(
            {
                "breakout_transition_active": True,
                "breakout_transition_micro_state": MICRO_STATE_BREAKOUT_SETUP if i < 4 else MICRO_STATE_COMPRESSION_OBSERVE,
                "breakout_transition_score": 0.4 if i < 4 else 0.8,
                "breakout_transition_continuation_score": 0.3 if i < 4 else 0.7,
                "setup_transition_score_gap": 0.2,
                "setup_transition_volatility": 0.01 if i < 4 else 0.03,
            }
        )
    return pd.DataFrame(rows)


def _robust_report():
    return {
        "windows": [
            {"window_id": "full", "start": 0, "end": 8, "support_ok": True, "breakout_better": False},
            {"window_id": "w1", "start": 0, "end": 4, "support_ok": False, "breakout_better": True},
        ]
    }


def test_context_diag_report_matrix_and_markdown():
    report = build_transition_micro_state_context_diag_report(
        _micro_df(),
        _robust_report(),
        asset="ETHUSDT",
        timeframe="1h",
        min_state_active=2,
        score_advantage_threshold=0.1,
    )
    matrix = build_transition_micro_state_context_diag_matrix_report([{"summary": report["summary"], "context_diag_report": report}])
    md = render_transition_micro_state_context_diag_markdown(matrix)

    assert report["phase"] == "phase_7y_transition_micro_state_context_diag"
    assert report["summary"]["mixed_window_count"] == 1
    assert report["summary"]["candidate_tag_count"] >= 1
    assert matrix["summary"]["variant_count"] == 1
    assert "# RegimeV2 Phase 7Y Context Tag Matrix" in md


def test_context_diag_cli_defaults_and_args():
    args = _parse_args(["--asset", "ETHUSDT", "--window-size", "120", "--min-state-active", "4"])
    assert args.asset == ["ETHUSDT"]
    assert args.window_size == 120
    assert args.min_state_active == 4

    defaults = _parse_args([])
    assert defaults.asset == ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    assert defaults.output_json.endswith("phase7y_transition_micro_state_context_diag.json")
