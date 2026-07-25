"""Trendlines-first public workflow wrapper for pipeline optimization."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from libs.models.trendlines.workflows.common import WorkflowStudyStatus, decide_pipeline_promotion
from libs.models.trendlines.workflows.pipeline.evaluation import (
    run_pipeline_with_params,
    search_pipeline_parameters,
    walk_forward_evaluate,
)
from libs.models.trendlines.workflows.pipeline.temporal_spec import (
    build_pipeline_optimization_spec,
    resolve_pipeline_temporal_plan,
)
from libs.models.trendlines.workflows.pipeline.support import (
    _index_to_date_str,
    build_pipeline_artifact_ref,
    build_pipeline_data_request,
    build_pipeline_split_manifest_ref,
)
from libs.models.trendlines.workflows.pipeline import data_fetch
from libs.models.trendlines.workflows.pipeline.config_apply import build_yaml_snippet
from libs.models.trendlines.workflows.pipeline.reporting import print_results, print_pipeline_yaml_snippet


__all__ = [
    "build_pipeline_artifact_ref",
    "build_pipeline_data_request",
    "build_pipeline_optimization_spec",
    "build_pipeline_split_manifest_ref",
    "main",
    "optimize_timeframe",
    "parse_args",
    "resolve_pipeline_temporal_plan",
    "run_pipeline_with_params",
    "search_pipeline_parameters",
    "walk_forward_evaluate",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimize trendline pipeline parameters per asset and timeframe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m libs.models.trendlines.cli pipeline-opt -a BTCUSDT -t 1h,4h -l 120
    python -m libs.models.trendlines.cli pipeline-opt -a SOLUSDT -t 15m,1h --start-date 2025-01-01
    python -m libs.models.trendlines.cli pipeline-opt -a ETHUSDT -t 4h --train-bars 400 --test-bars 100
        """,
    )

    parser.add_argument("-a", "--asset", type=str, default="BTCUSDT", help="Trading pair (default: BTCUSDT)")
    parser.add_argument("-t", "--timeframes", type=str, default="1h,4h", help="Comma-separated timeframes")
    parser.add_argument("-l", "--lookback", type=int, default=120, help="Lookback days when --start-date is omitted")
    parser.add_argument("--start-date", type=str, default=None, help="Start date for data window (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default=None, help="End date for data window (YYYY-MM-DD)")
    parser.add_argument("--train-bars", type=int, default=None, help="Training window size in bars")
    parser.add_argument("--test-bars", type=int, default=None, help="Test window size in bars")
    parser.add_argument("--step-bars", type=int, default=None, help="Step size between windows")
    parser.add_argument("--extractor", type=str, default="fractal", choices=["fractal", "rdp_zigzag"], help="Extractor to sweep")
    parser.add_argument("--output", type=str, default=None, help="Optional output path for result JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    return parser.parse_args()


def optimize_timeframe(
    df: pd.DataFrame,
    asset: str,
    timeframe: str,
    extractor_name: str,
    train_bars: int,
    test_bars: int,
    step_bars: Optional[int] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    data_request = build_pipeline_data_request(
        asset,
        (timeframe,),
        start_date=_index_to_date_str(df.index[0]) if len(df.index) else None,
        end_date=_index_to_date_str(df.index[-1]) if len(df.index) else None,
        metadata={
            "n_input_bars": len(df),
            "provided_dataset": True,
            "engine": "trendlines",
        },
    )
    temporal_split, manifest = resolve_pipeline_temporal_plan(
        len(df),
        timeframe,
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
    )
    artifact_ref = build_pipeline_artifact_ref(asset, timeframe, temporal_split)
    split_manifest_ref = build_pipeline_split_manifest_ref(asset, timeframe, manifest)
    experiment_spec = build_pipeline_optimization_spec(
        asset=asset,
        timeframe=timeframe,
        extractor_name=extractor_name,
        dataset=data_request,
        artifact=artifact_ref,
        temporal_split=temporal_split,
    )
    result = search_pipeline_parameters(
        df,
        asset,
        timeframe,
        extractor_name,
        manifest,
        quiet=quiet,
    )
    promotion = decide_pipeline_promotion(result)

    if result["n_windows"] <= 0:
        study_status = WorkflowStudyStatus.FAILED.value
    elif promotion.should_promote:
        study_status = WorkflowStudyStatus.COMPLETED_VALID.value
    else:
        study_status = WorkflowStudyStatus.COMPLETED_NO_VALID_OPTIMUM.value

    result.update(
        {
            "study_status": study_status,
            "promotion_result": promotion.to_dict(),
            "dataset_request": data_request.to_dict(),
            "experiment_spec": experiment_spec.to_dict(),
            "pipeline_artifact_ref": artifact_ref.to_dict(),
            "split_manifest_ref": split_manifest_ref.to_dict(),
            "workflow_stages": {
                "dataset_fetch": {
                    "status": "provided_dataset",
                    "request": data_request.to_dict(),
                },
                "temporal_split_resolution": {
                    "status": "completed",
                    "spec": temporal_split.to_dict(),
                    "n_folds": len(manifest.folds),
                    "spec_hash": temporal_split.spec_hash,
                },
                "trendlines_pipeline_evaluation": {
                    "status": "completed" if result["n_windows"] > 0 else "failed",
                    "n_windows": result["n_windows"],
                },
                "parameter_search": {
                    "status": "completed" if result["n_windows"] > 0 else "failed",
                    "best_fitness": result["best_fitness"],
                },
                "promotion_decision": promotion.to_dict(),
                "artifact_persistence": {
                    "status": "pending_explicit",
                    "requires_explicit_call": True,
                },
            },
        }
    )
    return result


def _run_pipeline_cli(args) -> int:
    if (args.train_bars is None) != (args.test_bars is None):
        raise ValueError("train_bars and test_bars must be provided together")

    request = build_pipeline_data_request(
        args.asset,
        args.timeframes,
        lookback_days=None if args.start_date else args.lookback,
        start_date=args.start_date,
        end_date=args.end_date,
        source="binance",
        metadata={"command": "pipeline-opt", "module": "libs.models.trendlines.cli"},
    )
    frames, dataset_manifest = data_fetch.fetch_pipeline_workflow_data(request, quiet=args.quiet)

    results: Dict[str, Dict[str, Any]] = {}
    for timeframe in request.timeframes:
        frame = frames[timeframe]
        if args.train_bars is None:
            temporal_split, _ = resolve_pipeline_temporal_plan(
                len(frame),
                timeframe,
                step_bars=args.step_bars,
            )
            train_bars = temporal_split.train_bars
            test_bars_val = temporal_split.test_bars
            step_bars_val = temporal_split.step_bars
        else:
            train_bars = args.train_bars
            test_bars_val = args.test_bars
            step_bars_val = args.step_bars or args.test_bars

        results[timeframe] = optimize_timeframe(
            frame,
            asset=args.asset,
            timeframe=timeframe,
            extractor_name=args.extractor,
            train_bars=train_bars,
            test_bars=test_bars_val,
            step_bars=step_bars_val,
            quiet=args.quiet,
        )

    print_results(results, args.asset, quiet=args.quiet)
    yaml_snippet = build_yaml_snippet(results, args.asset)
    print_pipeline_yaml_snippet(yaml_snippet, quiet=args.quiet)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "asset": args.asset,
            "dataset_manifest": dataset_manifest.to_dict(),
            "results": results,
            "yaml_snippet": yaml_snippet,
        }
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return 0


def main() -> int:
    args = parse_args()
    return _run_pipeline_cli(args)


if __name__ == "__main__":
    sys.exit(main())