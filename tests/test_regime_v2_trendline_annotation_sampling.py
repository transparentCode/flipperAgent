from __future__ import annotations

import json

from libs.models.regime_v2.scripts.plan_trendline_annotation_sampling import _parse_args
from libs.selection.regime_v2_trendline_annotation_sampling import (
    AnnotationSamplingConfig,
    build_annotation_sampling_plan,
    render_annotation_sampling_plan_markdown,
)


def _target_report() -> dict:
    return {
        "summary": {"labeled_count": 800, "records_after_filter": 800},
        "targets": [
            {
                "field": "trendline_confidence_annotation",
                "value": "breakout_watch",
                "count": 13,
                "asset_timeframe": {"SOLUSDT|4h": 8, "BNBUSDT|1h": 2, "ETHUSDT|4h": 2, "BTCUSDT|4h": 1},
            }
        ],
    }


def test_annotation_sampling_plan_estimates_needed_pair_runs():
    plan = build_annotation_sampling_plan(
        _target_report(),
        config=AnnotationSamplingConfig(
            symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"),
            timeframes=("1h", "4h"),
            max_records_per_pair=200,
            batch_size=3,
            target_rows=100,
            min_hit_rate=0.005,
            output_root="research/tl15",
        ),
    )

    target = plan["target"]
    assert target["current_count"] == 13
    assert target["deficit"] == 87
    assert target["observed_hit_rate"] == 13 / 800
    assert target["estimated_shadow_rows_needed"] == 5354
    assert target["pair_runs_needed"] == 27
    assert len(plan["selected_pair_runs"]) == 8
    assert plan["selected_pair_runs"][0]["pair"] == "SOLUSDT:4h"
    assert len(plan["batches"]) == 3
    assert "--pair SOLUSDT:4h" in plan["commands"][0]
    assert "research/tl15/batch_01_records.jsonl" in plan["commands"][0]


def test_annotation_sampling_plan_handles_already_satisfied_target():
    report = _target_report()
    report["targets"][0]["count"] = 120

    plan = build_annotation_sampling_plan(
        report,
        config=AnnotationSamplingConfig(symbols=("BTCUSDT",), timeframes=("4h",), target_rows=100),
    )

    assert plan["target"]["deficit"] == 0
    assert plan["selected_pair_runs"] == []
    assert plan["commands"] == []
    assert "already satisfied" in plan["recommendation"]


def test_annotation_sampling_plan_markdown_contains_commands():
    plan = build_annotation_sampling_plan(
        _target_report(),
        config=AnnotationSamplingConfig(symbols=("SOLUSDT",), timeframes=("4h",), batch_size=1, target_rows=20),
    )

    md = render_annotation_sampling_plan_markdown(plan)

    assert "# RegimeV2 Trendline Annotation Sampling Plan" in md
    assert "## Selected Pair Runs" in md
    assert "SOLUSDT:4h" in md
    assert "collect_shadow_binance" in md


def test_annotation_sampling_cli_parse_args():
    args = _parse_args(
        [
            "--target-report",
            "research/tl14/annotation_targets.json",
            "--target-field",
            "trendline_risk_context",
            "--target-value",
            "upper_channel_pressure_watch",
            "--symbols",
            "BTCUSDT,ETHUSDT",
            "--timeframes",
            "1h,4h",
            "--target-rows",
            "150",
            "--batch-size",
            "2",
            "--output-json",
            "research/tl15/plan.json",
            "--output-md",
            "research/tl15/plan.md",
        ]
    )

    assert args.target_report == "research/tl14/annotation_targets.json"
    assert args.target_field == "trendline_risk_context"
    assert args.target_value == "upper_channel_pressure_watch"
    assert args.symbols == "BTCUSDT,ETHUSDT"
    assert args.timeframes == "1h,4h"
    assert args.target_rows == 150
    assert args.batch_size == 2


def test_annotation_sampling_cli_generates_files(tmp_path):
    target_report = tmp_path / "targets.json"
    target_report.write_text(json.dumps(_target_report()), encoding="utf-8")
    out_json = tmp_path / "plan.json"
    out_md = tmp_path / "plan.md"

    from libs.models.regime_v2.scripts.plan_trendline_annotation_sampling import main

    rc = main(
        [
            "--target-report",
            str(target_report),
            "--symbols",
            "SOLUSDT",
            "--timeframes",
            "4h",
            "--target-rows",
            "20",
            "--output-json",
            str(out_json),
            "--output-md",
            str(out_md),
        ]
    )

    assert rc == 0
    assert out_json.exists()
    assert out_md.exists()
    assert "SOLUSDT:4h" in out_md.read_text(encoding="utf-8")
