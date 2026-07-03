"""Tests for Phase 7A playbook context report helpers."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_context_report import (
    build_playbook_context_report,
    render_playbook_context_report_markdown,
)
from libs.models.regime_v2.scripts.report_playbook_context import _parse_args


def test_playbook_context_report_summarizes_distributions():
    df = pd.DataFrame(
        [
            {
                "playbook_context_market_phase": "bull_trend",
                "playbook_context_risk_state": "ok",
                "playbook_context_risk_score": 0.2,
                "playbook_context_dominant_playbook": "trend",
                "playbook_context_horizon_bias": "long",
                "playbook_context_alignment": "aligned",
                "playbook_context_conflict_tags": "",
                "playbook_context_conflict_count": 0,
                "playbook_context_is_active": True,
                "playbook_context_is_confirmed": True,
                "playbook_context_next_step": "long_horizon_candidate",
            },
            {
                "playbook_context_market_phase": "displacement_breakout",
                "playbook_context_risk_state": "watch",
                "playbook_context_risk_score": 0.65,
                "playbook_context_dominant_playbook": "breakout",
                "playbook_context_horizon_bias": "mid_to_long",
                "playbook_context_alignment": "neutral_or_missing",
                "playbook_context_conflict_tags": "breakout_false_break_risk;context_not_confirmed",
                "playbook_context_conflict_count": 2,
                "playbook_context_is_active": True,
                "playbook_context_is_confirmed": True,
                "playbook_context_next_step": "require_retest_or_confirmation",
            },
        ],
        index=[1, 2],
    )

    report = build_playbook_context_report(df, asset="BNBUSDT", timeframe="1h", source="unit")

    assert report["summary"]["row_count"] == 2
    assert report["summary"]["active_context_rate"] == 1.0
    assert report["summary"]["dominant_playbook"] == {"trend": 1, "breakout": 1}
    assert report["summary"]["top_conflict_tags"]["breakout_false_break_risk"] == 1
    assert len(report["recent_context"]) == 2


def test_playbook_context_report_markdown_and_cli_args():
    df = pd.DataFrame(
        [
            {
                "playbook_context_market_phase": "neutral_context",
                "playbook_context_risk_state": "ok",
                "playbook_context_risk_score": 0.1,
                "playbook_context_dominant_playbook": "none",
                "playbook_context_horizon_bias": "mid",
                "playbook_context_alignment": "neutral_or_missing",
                "playbook_context_conflict_tags": "",
                "playbook_context_conflict_count": 0,
                "playbook_context_is_active": False,
                "playbook_context_is_confirmed": True,
                "playbook_context_next_step": "observe_or_shadow_only",
            }
        ]
    )
    report = build_playbook_context_report(df)
    md = render_playbook_context_report_markdown(report)
    assert "# RegimeV2 Phase 7A Playbook Context Report" in md
    assert "dominant_playbook" in md

    args = _parse_args(
        [
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--limit",
            "100",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.limit == 100
    assert args.output_json == "out.json"
    assert args.output_md == "out.md"
