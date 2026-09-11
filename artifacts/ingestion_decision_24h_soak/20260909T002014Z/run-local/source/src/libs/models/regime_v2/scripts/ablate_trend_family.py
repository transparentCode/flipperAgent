"""Run RegimeV2 trend-family ablation on candidate CSV exports."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.evaluation import (
    RegimeComparisonConfig,
    TrendFamilyAblationConfig,
    run_regime_comparison,
    run_trend_family_ablation,
)
from libs.models.regime_v2.scripts.compare_binance_native import (
    _parse_millis,
    fetch_binance_native_ohlcv,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    candidates = pd.read_csv(args.candidate_csv)
    comparison = await _load_comparison(args)
    model_names = tuple(args.model_name) if args.model_name else TrendFamilyAblationConfig.model_names
    result = run_trend_family_ablation(
        comparison,
        candidates,
        config=TrendFamilyAblationConfig(
            min_count=args.min_count,
            fee_bps=args.fee_bps,
            trend_score_floor=args.trend_score_floor,
            top_quantile=args.top_quantile,
            require_direction_agreement=not args.no_direction_agreement,
            model_names=model_names,
        ),
    )
    return {
        "candidate_csv": args.candidate_csv,
        "comparison_rows": int(len(comparison)),
        "candidate_rows": int(len(candidates)),
        "summary": result.summary,
        "metrics": [metric.to_dict() for metric in result.metrics],
    }


async def _load_comparison(args: argparse.Namespace) -> pd.DataFrame:
    if args.comparison_csv:
        frame = pd.read_csv(args.comparison_csv)
        if args.timestamp_column and args.timestamp_column in frame.columns:
            frame[args.timestamp_column] = pd.to_datetime(frame[args.timestamp_column], utc=True)
            frame = frame.set_index(args.timestamp_column)
        return frame

    if args.symbol is None or args.timeframe is None:
        raise ValueError("Either --comparison-csv or both --symbol and --timeframe are required")
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
    )
    comparison_result = run_regime_comparison(
        ohlcv,
        asset=args.symbol,
        timeframe=args.timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=args.horizon_bars,
            include_legacy_regime=False,
            include_regime_classification=False,
        ),
    )
    return comparison_result.frame


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate trend-family candidates with RegimeV2 filters.")
    parser.add_argument("--candidate-csv", required=True)
    parser.add_argument("--comparison-csv", default=None)
    parser.add_argument("--timestamp-column", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--model-name", action="append", default=None)
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--trend-score-floor", type=float, default=0.24)
    parser.add_argument("--top-quantile", type=float, default=0.90)
    parser.add_argument("--no-direction-agreement", action="store_true")
    parser.add_argument("--output-json", default=None)
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
