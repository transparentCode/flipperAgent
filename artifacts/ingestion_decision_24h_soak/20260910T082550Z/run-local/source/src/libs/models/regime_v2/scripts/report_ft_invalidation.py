"""Offline Phase 7J invalidation/cooldown retest runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import build_breakout_followthrough_frame
from libs.models.regime_v2.evaluation.playbook_ft_invalidation import (
    build_ft_invalidation_matrix_report,
    build_ft_invalidation_retest_report,
    render_ft_invalidation_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_ft_invalidation_markdown(payload["matrix_report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(symbol=args.asset, timeframe=args.timeframe, limit=args.limit, since=None, until=None)
    series = RegimeV2Orchestrator.create(args.asset, args.timeframe).analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    states = build_playbook_state_frame(context)
    reports = []
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
        reports.append(
            build_ft_invalidation_retest_report(
                refined,
                ohlcv,
                asset=args.asset,
                timeframe=args.timeframe,
                threshold=float(threshold),
                split_count=args.split_count,
                horizons=tuple(args.horizon),
                fees_bps=tuple(args.fee_bps),
                min_split_support=args.min_split_support,
                min_passing_rate=args.min_passing_rate,
                min_avg_return=args.min_avg_return,
                max_worst_loss=args.max_worst_loss,
                min_hold_score=args.min_hold_score,
                min_follow_score=args.min_follow_score,
                min_direction_return_score=args.min_direction_return_score,
                max_reversal_penalty=args.max_reversal_penalty,
                cooldown_bars=args.cooldown_bars,
                cooldown_by_direction=not args.global_cooldown,
                blocked_directions=tuple(args.blocked_direction),
            )
        )
    matrix = build_ft_invalidation_matrix_report(reports)
    return {
        "phase": "phase_7j_ft_invalidation_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": int(len(ohlcv)),
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7J follow-through invalidation/cooldown retest.")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--threshold", action="append", type=float, default=None)
    parser.add_argument("--split-count", type=int, default=4)
    parser.add_argument("--breakout-window", type=int, default=20)
    parser.add_argument("--hold-bars", type=int, default=2)
    parser.add_argument("--follow-bars", type=int, default=3)
    parser.add_argument("--max-false-breakout-risk", type=float, default=0.65)
    parser.add_argument("--max-shock-risk", type=float, default=0.80)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--min-split-support", type=int, default=2)
    parser.add_argument("--min-passing-rate", type=float, default=0.60)
    parser.add_argument("--min-avg-return", type=float, default=0.0)
    parser.add_argument("--max-worst-loss", type=float, default=0.0010)
    parser.add_argument("--min-hold-score", type=float, default=0.50)
    parser.add_argument("--min-follow-score", type=float, default=0.50)
    parser.add_argument("--min-direction-return-score", type=float, default=0.40)
    parser.add_argument("--max-reversal-penalty", type=float, default=0.35)
    parser.add_argument("--cooldown-bars", type=int, default=3)
    parser.add_argument("--global-cooldown", action="store_true")
    parser.add_argument("--blocked-direction", action="append", default=None)
    parser.add_argument("--output-json", default="research/regime_v2_phase7j_ft_invalidation.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7j_ft_invalidation.md")
    args = parser.parse_args(argv)
    args.threshold = args.threshold or [0.25, 0.30]
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    args.blocked_direction = args.blocked_direction or []
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
