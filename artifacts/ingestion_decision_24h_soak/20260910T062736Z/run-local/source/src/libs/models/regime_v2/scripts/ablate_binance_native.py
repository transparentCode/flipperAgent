"""Fetch Binance candles, run RegimeV2 comparison, then downstream ablation.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.ablate_binance_native \
        --symbol BTCUSDT --timeframe 4h --limit 1000 --horizon-bars 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation import (
    DownstreamAblationConfig,
    RegimeComparisonConfig,
    run_downstream_ablation,
    run_regime_comparison,
)
from libs.models.regime_v2.scripts.compare_binance_native import (
    fetch_binance_native_ohlcv,
    _parse_millis,
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
    df = await fetch_binance_native_ohlcv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
    )
    comparison = run_regime_comparison(
        df,
        asset=args.symbol,
        timeframe=args.timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=args.horizon_bars,
            include_legacy_regime=not args.skip_legacy,
            include_regime_classification=not args.skip_regime_classification,
        ),
    )
    ablation = run_downstream_ablation(
        comparison.frame,
        config=DownstreamAblationConfig(
            top_quantile=args.top_quantile,
            score_floor=args.score_floor,
            fee_bps=args.fee_bps,
            min_count=args.min_count,
        ),
    )
    return {
        "symbol": args.symbol.upper(),
        "timeframe": args.timeframe,
        "comparison_summary": comparison.summary,
        "ablation_summary": ablation.summary,
        "ablation_metrics": [metric.to_dict() for metric in ablation.metrics],
        "comparison_errors": comparison.errors,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RegimeV2 downstream ablation on Binance candles.")
    parser.add_argument("--symbol", required=True, help="Binance USD-M futures symbol, e.g. BTCUSDT.")
    parser.add_argument("--timeframe", required=True, help="Binance interval, e.g. 1h or 4h.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None, help="Start time: epoch ms or ISO datetime.")
    parser.add_argument("--until", default=None, help="End time: epoch ms or ISO datetime.")
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--top-quantile", type=float, default=0.90)
    parser.add_argument("--score-floor", type=float, default=0.24)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--skip-legacy", action="store_true")
    parser.add_argument("--skip-regime-classification", action="store_true")
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
