"""Tests for Phase 6Q PA paper action comparison."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_actions import _parse_args
from libs.selection.regime_v2_pa_paper_actions import (
    build_pa_paper_action_report,
    render_pa_paper_action_markdown,
)


def _row(baseline: float, paper: float = 0.0, *, changed: bool = True) -> dict:
    return {
        "asset": "BNBUSDT",
        "timeframe": "1h",
        "paper_active": True,
        "selection_changed": changed,
        "outcome_label": "avoided_loss" if baseline < 0 and changed else "unchanged",
        "baseline_net_return": baseline,
        "paper_net_return": paper,
        "paper_minus_baseline": paper - baseline,
    }


def test_action_report_prefers_suppress_when_baseline_losses_dominate():
    rows = [_row(-0.02), _row(-0.01), _row(0.005)]

    report = build_pa_paper_action_report(rows, scales=(0.5,), changed_only=True)

    assert report["summary"]["cohort_count"] == 3
    assert report["summary"]["best_action"] == "suppress_to_paper"
    assert report["summary"]["recommendation"] == "keep_suppress_to_paper"
    suppress = [row for row in report["actions"] if row["action"] == "suppress_to_paper"][0]
    assert suppress["avoided_loss_count"] == 2
    assert suppress["missed_win_count"] == 1


def test_action_report_can_prefer_scaled_baseline_when_suppression_misses_too_much():
    rows = [_row(0.02), _row(0.01), _row(-0.001)]

    report = build_pa_paper_action_report(rows, scales=(0.5,), changed_only=True)

    assert report["summary"]["best_action"] == "keep_baseline"
    assert report["summary"]["recommendation"] == "consider_keep_baseline"
    suppress = [row for row in report["actions"] if row["action"] == "suppress_to_paper"][0]
    assert suppress["avg_action_minus_baseline"] < 0.0


def test_action_report_changed_only_filter():
    rows = [_row(-0.02, changed=True), _row(-0.02, changed=False)]

    changed_report = build_pa_paper_action_report(rows, changed_only=True)
    active_report = build_pa_paper_action_report(rows, changed_only=False)

    assert changed_report["summary"]["cohort_count"] == 1
    assert active_report["summary"]["cohort_count"] == 2


def test_action_markdown_and_cli_args():
    report = build_pa_paper_action_report([_row(-0.02)], scales=(0.25,), changed_only=True)
    md = render_pa_paper_action_markdown(report)
    assert "# RegimeV2 Phase 6Q PA Paper Action Comparison" in md
    assert "suppress_to_paper" in md

    args = _parse_args(
        [
            "--outcomes",
            "custom.jsonl",
            "--scale",
            "0.25",
            "--scale",
            "0.5",
            "--all-paper-active",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.outcomes == "custom.jsonl"
    assert args.scale == [0.25, 0.5]
    assert args.all_paper_active is True
    assert args.output_json == "out.json"
    assert args.output_md == "out.md"

    defaults = _parse_args([])
    assert defaults.scale == [0.25, 0.5, 0.75]
