"""Validate RegimeV2 trend overlay across Binance rolling windows."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation import OverlayWindowValidationConfig, run_overlay_window_validation
from libs.models.regime_v2.scripts.compare_binance_native import _parse_millis, fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).write_text(text + "\n")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
    )
    result = run_overlay_window_validation(
        ohlcv,
        asset=args.symbol.upper(),
        timeframe=args.timeframe,
        config=OverlayWindowValidationConfig(
            horizon_bars=args.horizon_bars,
            window_bars=args.window_bars,
            step_bars=args.step_bars,
            min_count=args.min_count,
            fee_bps_values=tuple(args.fee_bps),
            candidate_models=tuple(args.model) if args.model else OverlayWindowValidationConfig.candidate_models,
            min_abs_edge=args.min_abs_edge,
            top_k=args.top_k,
            aligned_boost=args.aligned_boost,
            conflict_penalty=args.conflict_penalty,
        ),
    )
    return {
        "symbol": args.symbol.upper(),
        "timeframe": args.timeframe,
        "ohlcv_rows": int(len(ohlcv)),
        **result,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate RegimeV2 trend overlay over rolling Binance windows.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--horizon-bars", type=int, default=6)
    parser.add_argument("--window-bars", type=int, default=300)
    parser.add_argument("--step-bars", type=int, default=150)
    parser.add_argument("--min-count", type=int, default=10)
    parser.add_argument("--fee-bps", type=float, action="append", default=[0.0])
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--min-abs-edge", type=float, default=0.01)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--aligned-boost", type=float, default=0.35)
    parser.add_argument("--conflict-penalty", type=float, default=0.70)
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
