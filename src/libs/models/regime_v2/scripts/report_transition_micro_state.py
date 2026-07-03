"""Offline Phase 7V transition micro-state split runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    build_transition_micro_state_matrix_report,
    build_transition_micro_state_retest_report,
    render_transition_micro_state_markdown,
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
        Path(args.output_md).write_text(render_transition_micro_state_markdown(payload["matrix_report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    reports = []
    for asset in args.asset:
        for timeframe in args.timeframe:
            ohlcv = await fetch_binance_native_ohlcv(symbol=asset, timeframe=timeframe, limit=args.limit, since=None, until=None)
            series = RegimeV2Orchestrator.create(asset, timeframe).analyze_series(ohlcv)
            context = build_playbook_context_frame(series)
            states = build_playbook_state_frame(context)
            reports.append(
                build_transition_micro_state_retest_report(
                    series,
                    context,
                    states,
                    ohlcv,
                    asset=asset,
                    timeframe=timeframe,
                    horizons=tuple(args.horizon),
                    fees_bps=tuple(args.fee_bps),
                    lookback_bars=args.lookback_bars,
                    min_candidate_score=args.min_candidate_score,
                    min_context_score=args.min_context_score,
                    max_risk_score=args.max_risk_score,
                    max_conflict_count=args.max_conflict_count,
                    min_wick_score=args.min_wick_score,
                    min_attempt_score=args.min_attempt_score,
                )
            )
    matrix = build_transition_micro_state_matrix_report(reports)
    return {
        "phase": "phase_7v_transition_micro_state_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": args.limit,
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7V transition micro-state split.")
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--timeframe", action="append", default=None)
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--lookback-bars", type=int, default=8)
    parser.add_argument("--min-candidate-score", type=float, default=0.62)
    parser.add_argument("--min-context-score", type=float, default=0.70)
    parser.add_argument("--max-risk-score", type=float, default=0.72)
    parser.add_argument("--max-conflict-count", type=int, default=1)
    parser.add_argument("--min-wick-score", type=float, default=0.35)
    parser.add_argument("--min-attempt-score", type=float, default=0.50)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--output-json", default="research/regime_v2_phase7v_transition_micro_state.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7v_transition_micro_state.md")
    args = parser.parse_args(argv)
    args.asset = args.asset or ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    args.timeframe = args.timeframe or ["1h"]
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
