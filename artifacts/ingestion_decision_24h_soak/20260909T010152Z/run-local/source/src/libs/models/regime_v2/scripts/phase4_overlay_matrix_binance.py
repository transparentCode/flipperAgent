"""Run RegimeV2 Phase 4 overlay-validation matrix on Binance candles.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.phase4_overlay_matrix_binance \
        --symbol BTCUSDT --symbol ETHUSDT \
        --timeframe 1h --timeframe 4h \
        --horizon-bars 6 --horizon-bars 12 \
        --fee-bps 2 --fee-bps 5 \
        --output-json research/regime_v2_phase4_matrix.json \
        --output-md research/regime_v2_phase4_matrix.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation import (
    Phase4DecisionConfig,
    Phase4OverlayMatrixConfig,
    render_phase4_overlay_matrix_markdown,
    run_phase4_overlay_matrix_async,
)
from libs.models.regime_v2.scripts.compare_binance_native import _parse_millis, fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_phase4_overlay_matrix_markdown(payload), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    since = _parse_millis(args.since)
    until = _parse_millis(args.until)

    async def fetch(asset: str, timeframe: str):
        return await fetch_binance_native_ohlcv(
            symbol=asset,
            timeframe=timeframe,
            limit=args.limit,
            since=since,
            until=until,
        )

    symbols = args.symbol or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    timeframes = args.timeframe or ["1h", "4h"]
    horizon_bars = args.horizon_bars or [6, 12]
    fee_bps = args.fee_bps or [0.0, 2.0, 5.0]

    return await run_phase4_overlay_matrix_async(
        fetch,
        config=Phase4OverlayMatrixConfig(
            assets=tuple(symbol.upper() for symbol in symbols),
            timeframes=tuple(timeframes),
            horizon_bars_values=tuple(horizon_bars),
            window_bars=args.window_bars,
            step_bars=args.step_bars,
            min_count=args.min_count,
            fee_bps_values=tuple(fee_bps),
            candidate_models=tuple(args.model) if args.model else Phase4OverlayMatrixConfig.candidate_models,
            min_abs_edge=args.min_abs_edge,
            top_k=args.top_k,
            aligned_boost=args.aligned_boost,
            conflict_penalty=args.conflict_penalty,
            trend_score_floor=args.trend_score_floor,
            breakout_score_floor=args.breakout_score_floor,
            mean_reversion_score_floor=args.mean_reversion_score_floor,
            include_window_metrics=not args.no_window_metrics,
            decision=Phase4DecisionConfig(
                min_valid_windows_per_fee=args.min_valid_windows_per_fee,
                min_positive_rate=args.min_positive_rate,
                min_mean_lift=args.min_mean_lift,
                require_all_fees=not args.any_fee_can_pass,
                min_passed_combos=args.min_passed_combos,
                min_combo_pass_rate=args.min_combo_pass_rate,
            ),
        ),
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RegimeV2 Phase 4 overlay matrix on Binance candles.")
    parser.add_argument("--symbol", action="append", default=None)
    parser.add_argument("--timeframe", action="append", default=None)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--horizon-bars", type=int, action="append", default=None)
    parser.add_argument("--window-bars", type=int, default=300)
    parser.add_argument("--step-bars", type=int, default=150)
    parser.add_argument("--min-count", type=int, default=10)
    parser.add_argument("--fee-bps", type=float, action="append", default=None)
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "Candidate model: Momentum, TrendFollowing, PriceAction, "
            "Trendline, SqueezeBreakout, RegimePullbackScorer."
        ),
    )
    parser.add_argument("--min-abs-edge", type=float, default=0.01)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--aligned-boost", type=float, default=0.35)
    parser.add_argument("--conflict-penalty", type=float, default=0.70)
    parser.add_argument("--trend-score-floor", type=float, default=0.24)
    parser.add_argument("--breakout-score-floor", type=float, default=0.24)
    parser.add_argument("--mean-reversion-score-floor", type=float, default=0.24)
    parser.add_argument("--no-window-metrics", action="store_true")

    parser.add_argument("--min-valid-windows-per-fee", type=int, default=2)
    parser.add_argument("--min-positive-rate", type=float, default=0.55)
    parser.add_argument("--min-mean-lift", type=float, default=0.0)
    parser.add_argument("--any-fee-can-pass", action="store_true")
    parser.add_argument("--min-passed-combos", type=int, default=2)
    parser.add_argument("--min-combo-pass-rate", type=float, default=0.60)

    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        return value.item()
    return value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
