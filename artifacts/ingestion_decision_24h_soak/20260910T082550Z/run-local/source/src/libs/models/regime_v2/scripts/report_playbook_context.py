"""Offline Phase 7A playbook context report CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from libs.models.regime_v2.evaluation.playbook_context_report import (
    build_playbook_context_report,
    render_playbook_context_report_markdown,
)
from libs.models.regime_v2.orchestrator import RegimeV2Orchestrator
from libs.models.regime_v2.policy import build_playbook_context_frame
from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv


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
        Path(args.output_md).write_text(render_playbook_context_report_markdown(report), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    ohlcv = await fetch_binance_native_ohlcv(
        symbol=args.asset,
        timeframe=args.timeframe,
        limit=args.limit,
        since=None,
        until=None,
    )
    orchestrator = RegimeV2Orchestrator.create(args.asset, args.timeframe)
    series = orchestrator.analyze_series(ohlcv)
    context = build_playbook_context_frame(series)
    report = build_playbook_context_report(
        context,
        asset=args.asset,
        timeframe=args.timeframe,
        source="binance_native_ohlcv",
    )
    report["input_rows"] = int(len(ohlcv))
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an offline playbook context report.")
    parser.add_argument("--asset", default="BNBUSDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=720)
    parser.add_argument("--output-json", default="research/regime_v2_phase7a_playbook_context.json")
    parser.add_argument("--output-md", default="research/regime_v2_phase7a_playbook_context.md")
    return parser.parse_args(argv)


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
