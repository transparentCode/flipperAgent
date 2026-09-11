"""Offline Phase 7G matrix runner for direction-aware breakout follow-through."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import (
    build_breakout_followthrough_frame,
    build_breakout_followthrough_outcome_matrix,
    build_breakout_followthrough_report,
)
from libs.models.regime_v2.evaluation.playbook_ft_matrix import build_ft_matrix_report, render_ft_matrix_markdown
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv

_DEFAULT_PAIRS = (("BNBUSDT", "1h"), ("BTCUSDT", "4h"), ("ETHUSDT", "4h"), ("SOLUSDT", "4h"))
_DEFAULT_THRESHOLDS = (0.20, 0.25, 0.30, 0.35)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = asyncio.run(_run(args))
    text = json.dumps(_json_safe(report), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_ft_matrix_markdown(report), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    pairs = _pairs(args)
    variants: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for asset, timeframe in pairs:
        try:
            variants.extend(await _pair_variants(args, asset=asset, timeframe=timeframe))
        except Exception as exc:  # pragma: no cover - defensive CLI isolation
            errors[f"{asset}|{timeframe}"] = f"{type(exc).__name__}: {exc}"
    report = build_ft_matrix_report(
        variants,
        min_support=args.min_support,
        min_passing_rate=args.min_passing_rate,
        min_avg_return=args.min_avg_return,
        max_cell_loss=args.max_cell_loss,
    )
    report["errors"] = errors
    report["input"] = {
        "pairs": [f"{asset}|{timeframe}" for asset, timeframe in pairs],
        "thresholds": list(args.threshold),
        "limit": args.limit,
        "horizons": list(args.horizon),
        "fees_bps": list(args.fee_bps),
        "breakout_window": args.breakout_window,
        "hold_bars": args.hold_bars,
        "follow_bars": args.follow_bars,
    }
    return report


async def _pair_variants(args: argparse.Namespace, *, asset: str, timeframe: str) -> list[dict[str, Any]]:
    ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=timeframe, limit=args.limit, since=None, until=None)
    series = RegimeV2Orchestrator.create(asset, timeframe).analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    states = build_playbook_state_frame(context)
    rows = []
    for threshold in args.threshold:
        refined = build_breakout_followthrough_frame(
            series,
            states,
            ohlcv,
            breakout_window=args.breakout_window,
            hold_bars=args.hold_bars,
            follow_bars=args.follow_bars,
            min_followthrough_score=float(threshold),
            max_false_breakout_risk=args.max_false_breakout_risk,
            max_shock_risk=args.max_shock_risk,
        )
        ft_report = build_breakout_followthrough_report(refined, asset=asset, timeframe=timeframe, source="binance_native_ohlcv")
        matrix = build_breakout_followthrough_outcome_matrix(
            refined,
            ohlcv,
            horizons=tuple(args.horizon),
            fees_bps=tuple(args.fee_bps),
        )
        rows.append(
            {
                "asset": asset,
                "timeframe": timeframe,
                "threshold": float(threshold),
                "followthrough_report": ft_report,
                "outcome_matrix": matrix,
            }
        )
    return rows


def _pairs(args: argparse.Namespace) -> list[tuple[str, str]]:
    if not args.pair:
        return list(_DEFAULT_PAIRS)
    pairs = []
    for raw in args.pair:
        if "|" in raw:
            asset, timeframe = raw.split("|", 1)
        elif ":" in raw:
            asset, timeframe = raw.split(":", 1)
        else:
            raise ValueError(f"pair must be ASSET|TIMEFRAME: {raw}")
        pairs.append((asset.upper(), timeframe))
    return pairs


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7G follow-through matrix.")
    parser.add_argument("--pair", action="append", default=None, help="Pair as ASSET|TIMEFRAME. Repeatable.")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--threshold", action="append", type=float, default=None)
    parser.add_argument("--breakout-window", type=int, default=20)
    parser.add_argument("--hold-bars", type=int, default=2)
    parser.add_argument("--follow-bars", type=int, default=3)
    parser.add_argument("--max-false-breakout-risk", type=float, default=0.65)
    parser.add_argument("--max-shock-risk", type=float, default=0.80)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--min-support", type=int, default=10)
    parser.add_argument("--min-passing-rate", type=float, default=0.60)
    parser.add_argument("--min-avg-return", type=float, default=0.0)
    parser.add_argument("--max-cell-loss", type=float, default=0.0010)
    parser.add_argument("--output-json", default="research/regime_v2_phase7g_ft_matrix.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7g_ft_matrix.md")
    args = parser.parse_args(argv)
    args.threshold = args.threshold or list(_DEFAULT_THRESHOLDS)
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    return args


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    if isinstance(value, tuple):
        return [_json_safe(val) for val in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
