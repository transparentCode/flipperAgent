"""Tests for Phase 6R PA paper snapshot coverage reports."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_snapshots import _parse_args
from libs.selection.regime_v2_pa_paper_snapshots import (
    build_pa_paper_snapshot_report,
    render_pa_paper_snapshot_markdown,
)


def _row(*, changed: bool = True, with_snapshots: bool = True, paper_top: str = "Momentum") -> dict:
    row = {
        "paper_active": True,
        "selection_changed": changed,
        "candidate_snapshot_schema_version": 1 if with_snapshots else None,
        "baseline_selected_model": "PriceAction",
        "baseline_selection_score": 0.9,
    }
    if with_snapshots:
        row["baseline_ranked_candidates"] = [
            {"rank": 1, "model_name": "PriceAction", "selection_score": 0.9},
            {"rank": 2, "model_name": "Momentum", "selection_score": 0.7},
        ]
        row["paper_ranked_candidates"] = [{"rank": 1, "model_name": paper_top, "selection_score": 0.7}]
    else:
        row["baseline_ranked_candidates"] = []
        row["paper_ranked_candidates"] = []
    return row


def test_snapshot_report_full_coverage_and_alternate_ready():
    report = build_pa_paper_snapshot_report([_row(), _row(paper_top="TrendFollowing")])

    assert report["summary"]["total_records"] == 2
    assert report["summary"]["snapshot_coverage_rate"] == 1.0
    assert report["summary"]["changed_alternate_coverage_rate"] == 1.0
    assert report["summary"]["alternate_action_ready"] is True
    assert report["distributions"]["baseline_top_model"] == {"PriceAction": 2}
    assert report["distributions"]["changed_paper_top_model"] == {"Momentum": 1, "TrendFollowing": 1}


def test_snapshot_report_missing_snapshots_not_ready():
    report = build_pa_paper_snapshot_report([_row(), _row(with_snapshots=False)])

    assert report["summary"]["total_records"] == 2
    assert report["summary"]["both_snapshot_count"] == 1
    assert report["summary"]["snapshot_coverage_rate"] == 0.5
    assert report["summary"]["changed_alternate_coverage_rate"] == 0.5
    assert report["summary"]["alternate_action_ready"] is False


def test_snapshot_report_markdown_and_cli_args():
    report = build_pa_paper_snapshot_report([_row()])
    md = render_pa_paper_snapshot_markdown(report)
    assert "# RegimeV2 Phase 6R PA Paper Snapshot Coverage" in md
    assert "Alternate action ready" in md

    args = _parse_args(["--log", "custom.jsonl", "--output-json", "out.json", "--output-md", "out.md"])
    assert args.log == "custom.jsonl"
    assert args.output_json == "out.json"
    assert args.output_md == "out.md"

    defaults = _parse_args([])
    assert defaults.log.endswith("pa_asset_paper_decisions.jsonl")
