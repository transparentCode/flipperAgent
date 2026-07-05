"""Create a collection plan for targeted trendline annotation evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_trendline_annotation_sampling import (
    AnnotationSamplingConfig,
    build_annotation_sampling_plan,
    render_annotation_sampling_plan_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = json.loads(Path(args.target_report).read_text(encoding="utf-8"))
    config = AnnotationSamplingConfig(
        symbols=_csv_tuple(args.symbols),
        timeframes=_csv_tuple(args.timeframes),
        max_records_per_pair=args.max_records_per_pair,
        limit=args.limit,
        warmup_bars=args.warmup_bars,
        horizon_bars=args.horizon_bars,
        batch_size=args.batch_size,
        target_rows=args.target_rows,
        min_hit_rate=args.min_hit_rate,
        output_root=args.output_root,
    )
    plan = build_annotation_sampling_plan(
        report,
        config=config,
        target_field=args.target_field,
        target_value=args.target_value,
    )
    text = json.dumps(_json_safe(plan), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_annotation_sampling_plan_markdown(plan), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan follow-up sampling for a trendline annotation target.")
    parser.add_argument("--target-report", required=True)
    parser.add_argument("--target-field", default="trendline_confidence_annotation")
    parser.add_argument("--target-value", default="breakout_watch")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,LTCUSDT")
    parser.add_argument("--timeframes", default="1h,2h,4h")
    parser.add_argument("--target-rows", type=int, default=100)
    parser.add_argument("--max-records-per-pair", type=int, default=200)
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--warmup-bars", type=int, default=120)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--min-hit-rate", type=float, default=0.005)
    parser.add_argument("--output-root", default="research/tl15")
    parser.add_argument("--output-json", default="research/tl15/sampling_plan.json")
    parser.add_argument("--output-md", default="research/tl15/sampling_plan.md")
    return parser.parse_args(argv)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
