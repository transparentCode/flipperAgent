"""Run built-in trend-model candidate ablation on Binance candles."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation import (
    RegimeComparisonConfig,
    RegimeV2TrendOverlayConfig,
    TrendCandidateExportConfig,
    TrendFamilyAblationConfig,
    export_builtin_trend_candidates,
    run_regime_comparison,
    run_regime_v2_trend_selection_overlay,
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
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.symbol,
        timeframe=args.timeframe,
        limit=args.limit,
        since=_parse_millis(args.since),
        until=_parse_millis(args.until),
    )
    comparison = run_regime_comparison(
        ohlcv,
        asset=args.symbol,
        timeframe=args.timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=args.horizon_bars,
            include_legacy_regime=False,
            include_regime_classification=False,
        ),
    )
    candidates = export_builtin_trend_candidates(
        ohlcv,
        asset=args.symbol.upper(),
        timeframe=args.timeframe,
        config=TrendCandidateExportConfig(
            models=tuple(args.model) if args.model else TrendCandidateExportConfig.models,
            min_abs_edge=args.min_abs_edge,
            include_flat=args.include_flat,
        ),
    )
    result = run_trend_family_ablation(
        comparison.frame,
        candidates,
        config=TrendFamilyAblationConfig(
            min_count=args.min_count,
            fee_bps=args.fee_bps,
            trend_score_floor=args.trend_score_floor,
            top_quantile=args.top_quantile,
            require_direction_agreement=not args.no_direction_agreement,
            model_names=tuple(args.model_name) if args.model_name else TrendFamilyAblationConfig.model_names,
        ),
    )
    overlay_result = run_regime_v2_trend_selection_overlay(
        comparison.frame,
        candidates,
        config=RegimeV2TrendOverlayConfig(
            min_count=args.min_count,
            fee_bps=args.fee_bps,
            trend_score_floor=args.trend_score_floor,
            top_k=args.top_k,
            aligned_boost=args.aligned_boost,
            conflict_penalty=args.conflict_penalty,
            suppress_conflicts=args.suppress_conflicts,
            target_model_names=tuple(args.overlay_model_name) if args.overlay_model_name else RegimeV2TrendOverlayConfig.target_model_names,
        ),
    )
    if args.output_candidates_csv:
        candidates.to_csv(args.output_candidates_csv, index=False)
    return {
        "symbol": args.symbol.upper(),
        "timeframe": args.timeframe,
        "ohlcv_rows": int(len(ohlcv)),
        "candidate_rows": int(len(candidates)),
        "candidate_counts": candidates["model_name"].value_counts().sort_index().to_dict() if not candidates.empty else {},
        "comparison_summary": comparison.summary,
        "trend_family_summary": result.summary,
        "trend_family_metrics": [metric.to_dict() for metric in result.metrics],
        "selection_overlay_summary": overlay_result.summary,
        "selection_overlay_baseline": overlay_result.baseline.to_dict(),
        "selection_overlay_overlay": overlay_result.overlay.to_dict(),
        "selection_overlay_gated": overlay_result.gated.to_dict(),
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate built-in trend models with RegimeV2 filters on Binance data.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--since", default=None)
    parser.add_argument("--until", default=None)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help=(
            "Built-in model to export: Momentum, TrendFollowing, PriceAction, "
            "Trendline, SqueezeBreakout, RegimePullbackScorer."
        ),
    )
    parser.add_argument("--model-name", action="append", default=None, help="Candidate model name to evaluate after export.")
    parser.add_argument("--min-abs-edge", type=float, default=0.0)
    parser.add_argument("--include-flat", action="store_true")
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--trend-score-floor", type=float, default=0.24)
    parser.add_argument("--top-quantile", type=float, default=0.90)
    parser.add_argument("--no-direction-agreement", action="store_true")
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument("--aligned-boost", type=float, default=0.35)
    parser.add_argument("--conflict-penalty", type=float, default=0.70)
    parser.add_argument("--suppress-conflicts", action="store_true")
    parser.add_argument("--overlay-model-name", action="append", default=None)
    parser.add_argument("--output-candidates-csv", default=None)
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
