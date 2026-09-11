"""Offline Phase 7Y transition micro-state context tag runner."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_transition_micro_state_context_diag import (
    build_transition_micro_state_context_diag_matrix_report,
    build_transition_micro_state_context_diag_retest_report,
    render_transition_micro_state_context_diag_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame, build_playbook_state_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(json.dumps(payload["matrix_report"]["summary"], indent=2, sort_keys=True))
    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(text + "\n", encoding="utf-8")
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_md).write_text(render_transition_micro_state_context_diag_markdown(payload["matrix_report"]), encoding="utf-8")
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
                build_transition_micro_state_context_diag_retest_report(
                    series,
                    context,
                    states,
                    ohlcv,
                    asset=asset,
                    timeframe=timeframe,
                    window_size=args.window_size,
                    step_size=args.step_size,
                    min_state_active=args.min_state_active,
                    lookback_bars=args.lookback_bars,
                    min_candidate_score=args.min_candidate_score,
                    min_context_score=args.min_context_score,
                    max_risk_score=args.max_risk_score,
                    max_conflict_count=args.max_conflict_count,
                    min_wick_score=args.min_wick_score,
                    min_attempt_score=args.min_attempt_score,
                )
            )
    matrix = build_transition_micro_state_context_diag_matrix_report(reports)
    return {
        "phase": "phase_7y_transition_micro_state_context_diag_runner",
        "asset": args.asset,
        "timeframe": args.timeframe,
        "input_rows": args.limit,
        "matrix_report": matrix,
        "variant_reports": reports,
    }


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7Y transition context-tag diagnostics.")
    parser.add_argument("--asset", action="append", default=None)
    parser.add_argument("--timeframe", action="append", default=None)
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--window-size", type=int, default=360)
    parser.add_argument("--step-size", type=int, default=180)
    parser.add_argument("--min-state-active", type=int, default=6)
    parser.add_argument("--lookback-bars", type=int, default=8)
    parser.add_argument("--min-candidate-score", type=float, default=0.62)
    parser.add_argument("--min-context-score", type=float, default=0.70)
    parser.add_argument("--max-risk-score", type=float, default=0.72)
    parser.add_argument("--max-conflict-count", type=int, default=1)
    parser.add_argument("--min-wick-score", type=float, default=0.35)
    parser.add_argument("--min-attempt-score", type=float, default=0.50)
    parser.add_argument("--output-json", default="research/regime_v2_phase7y_transition_micro_state_context_diag.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7y_transition_micro_state_context_diag.md")
    args = parser.parse_args(argv)
    args.asset = args.asset or ["BNBUSDT", "ETHUSDT", "BTCUSDT"]
    args.timeframe = args.timeframe or ["1h"]
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
