"""Offline Phase 7F direction-aware breakout follow-through report CLI."""

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
    render_breakout_followthrough_markdown,
    render_breakout_followthrough_outcome_markdown,
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
        Path(args.output_md).write_text(render_breakout_followthrough_markdown(payload["followthrough_report"]), encoding="utf-8")
    if args.outcome_json:
        Path(args.outcome_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.outcome_json).write_text(json.dumps(_json_safe(payload["outcome_matrix"]), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.outcome_md:
        Path(args.outcome_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.outcome_md).write_text(render_breakout_followthrough_outcome_markdown(payload["outcome_matrix"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        limit=args.limit,
        since=None,
        until=None,
    )
    series = RegimeV2Orchestrator.create(args.asset, args.timeframe).analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    states = build_playbook_state_frame(context)
    refined = build_breakout_followthrough_frame(
        series,
        states,
        ohlcv,
        breakout_window=args.breakout_window,
        hold_bars=args.hold_bars,
        follow_bars=args.follow_bars,
        min_followthrough_score=args.min_followthrough_score,
        max_false_breakout_risk=args.max_false_breakout_risk,
        max_shock_risk=args.max_shock_risk,
    )
    report = build_breakout_followthrough_report(refined, asset=args.asset, timeframe=args.timeframe, source="binance_native_ohlcv")
    matrix = build_breakout_followthrough_outcome_matrix(
        refined,
        ohlcv,
        horizons=tuple(args.horizon),
        fees_bps=tuple(args.fee_bps),
    )
    return {
        "phase": "phase_7f_breakout_followthrough_report",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": int(len(ohlcv)),
        "followthrough_report": report,
        "outcome_matrix": matrix,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate direction-aware breakout follow-through report.")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--breakout-window", type=int, default=20)
    parser.add_argument("--hold-bars", type=int, default=2)
    parser.add_argument("--follow-bars", type=int, default=3)
    parser.add_argument("--min-followthrough-score", type=float, default=0.25)
    parser.add_argument("--max-false-breakout-risk", type=float, default=0.65)
    parser.add_argument("--max-shock-risk", type=float, default=0.80)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--output-json", default="research/regime_v2_phase7f_breakout_followthrough.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7f_breakout_followthrough.md")
    parser.add_argument("--outcome-json", default="research/regime_v2_phase7f_breakout_followthrough_outcomes.json")
    parser.add_argument("--outcome-md", default="research/regime_v2_phase7f_breakout_followthrough_outcomes.md")
    args = parser.parse_args(argv)
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
