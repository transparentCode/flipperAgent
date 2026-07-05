"""Render targeted evidence for RegimeV2 trendline annotation buckets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from libs.selection.regime_v2_shadow_report import load_regime_v2_shadow_decisions
from libs.selection.regime_v2_trendline_annotation_targets import (
    AnnotationTargetThresholds,
    build_trendline_annotation_target_report,
    render_trendline_annotation_target_markdown,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    records, invalid = load_regime_v2_shadow_decisions(args.log)
    report = build_trendline_annotation_target_report(
        records,
        source_path=args.log,
        asset=args.asset,
        timeframe=args.timeframe,
        targets=_parse_targets(args.target),
        thresholds=AnnotationTargetThresholds(
            min_samples=args.min_samples,
            min_positive_lift_rate=args.min_positive_lift_rate,
            min_avg_shadow_lift=args.min_avg_shadow_lift,
        ),
    )
    report["source_invalid_shadow_records"] = invalid
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_trendline_annotation_target_markdown(report), encoding="utf-8")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report evidence quality for targeted trendline annotation buckets.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl")
    parser.add_argument("--asset", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument(
        "--target",
        action="append",
        default=None,
        help="Target as FIELD=VALUE. Repeatable. Defaults to breakout/pressure-watch buckets.",
    )
    parser.add_argument("--min-samples", type=int, default=100)
    parser.add_argument("--min-positive-lift-rate", type=float, default=0.50)
    parser.add_argument("--min-avg-shadow-lift", type=float, default=0.0)
    parser.add_argument("--output-json", default="research/trendline_annotation_targets.json")
    parser.add_argument("--output-md", default="research/trendline_annotation_targets.md")
    return parser.parse_args(argv)


def _parse_targets(values: list[str] | None) -> list[tuple[str, Any]] | None:
    if not values:
        return None
    targets: list[tuple[str, Any]] = []
    for item in values:
        if "=" not in item:
            raise ValueError(f"Invalid --target {item!r}; expected FIELD=VALUE")
        field, value = item.split("=", 1)
        targets.append((field.strip(), _parse_target_value(value.strip())))
    return targets


def _parse_target_value(value: str) -> Any:
    lower = value.lower()
    if lower in {"true", "yes"}:
        return 1.0
    if lower in {"false", "no"}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return value


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
