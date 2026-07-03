"""Offline Phase 7K pre-confirmation context-gate retest runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_ft_context_gate import (
    build_ft_context_gate_matrix_report,
    build_ft_context_gate_retest_report,
    render_ft_context_gate_markdown,
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
        Path(args.output_md).write_text(render_ft_context_gate_markdown(payload["matrix_report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(symbol=args.asset, timeframe=args.timeframe, limit=args.limit, since=None, until=None)
    series = RegimeV2Orchestrator.create(args.asset, args.timeframe).analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    states = build_playbook_state_frame(context)
    reports = []
    for threshold in args.threshold:
        reports.append(
            build_ft_context_gate_retest_report(
                series,
                context,
                states,
                ohlcv,
                asset=args.asset,
                timeframe=args.timeframe,
                threshold=float(threshold),
                split_count=args.split_count,
                breakout_window=args.breakout_window,
                hold_bars=args.hold_bars,
                follow_bars=args.follow_bars,
                max_false_breakout_risk=args.max_false_breakout_risk,
                max_shock_risk=args.max_shock_risk,
                horizons=tuple(args.horizon),
                fees_bps=tuple(args.fee_bps),
                min_split_support=args.min_split_support,
                min_passing_rate=args.min_passing_rate,
                min_avg_return=args.min_avg_return,
                max_worst_loss=args.max_worst_loss,
                min_context_score=args.min_context_score,
                max_risk_score=args.max_risk_score,
                max_conflict_count=args.max_conflict_count,
                allow_watch_risk=not args.block_watch_risk,
                require_breakout_playbook=args.require_breakout_playbook,
                require_confirmed_context=args.require_confirmed_context,
            )
        )
    matrix = build_ft_context_gate_matrix_report(reports)
    return {
        "phase": "phase_7k_ft_context_gate_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": int(len(ohlcv)),
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7K pre-confirmation follow-through context gate.")
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
    parser.add_argument("--min-context-score", type=float, default=0.70)
    parser.add_argument("--max-risk-score", type=float, default=0.72)
    parser.add_argument("--max-conflict-count", type=int, default=1)
    parser.add_argument("--block-watch-risk", action="store_true")
    parser.add_argument("--require-breakout-playbook", action="store_true")
    parser.add_argument("--require-confirmed-context", action="store_true")
    parser.add_argument("--output-json", default="research/regime_v2_phase7k_ft_context_gate.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7k_ft_context_gate.md")
    args = parser.parse_args(argv)
    args.threshold = args.threshold or [0.25, 0.30]
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
