"""Train and audit a RegimeProbV1 offline optimization study."""

from __future__ import annotations

import argparse

from libs.models.regime_prob_v1.optimization import render_markdown_report, run_study
from libs.models.regime_prob_v1.scripts._shared import (
    build_feature_and_labels,
    load_context_frames,
    load_ohlcv,
    write_json,
    write_text,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a RegimeProbV1 optimization study")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--profile", default="edge_calibration")
    parser.add_argument("--playbook")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--n-trials", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--since")
    parser.add_argument("--until")
    parser.add_argument("--input-csv")
    parser.add_argument("--context-csv", action="append", default=[])
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md")
    parser.add_argument("--include-threshold-sweep", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    context_frames = load_context_frames(args.context_csv)
    ohlcv = load_ohlcv(
        asset=args.asset,
        timeframe=args.timeframe,
        input_csv=args.input_csv,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    feature_frame, label_frame = build_feature_and_labels(
        ohlcv,
        asset=args.asset,
        timeframe=args.timeframe,
        external_context_frames=context_frames or None,
    )
    result = run_study(
        feature_frame,
        label_frame,
        asset=args.asset,
        timeframe=args.timeframe,
        profile=args.profile,
        playbook=args.playbook,
        horizon=int(args.horizon),
        n_trials=int(args.n_trials),
        seed=int(args.seed),
        include_threshold_sweep=bool(args.include_threshold_sweep),
    )
    write_json(args.output_json, result)
    if args.output_md:
        write_text(args.output_md, render_markdown_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
