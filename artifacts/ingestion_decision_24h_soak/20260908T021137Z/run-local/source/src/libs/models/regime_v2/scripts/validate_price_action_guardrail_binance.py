"""Validate PriceAction direction-aware guardrail candidate using Binance candles.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.validate_price_action_guardrail_binance \
        --log logs/regime_v2_shadow_decisions.jsonl \
        --direction 1 \
        --limit 1000 \
        --horizon 3 --horizon 6 --horizon 12 --horizon 24 \
        --fee-bps 2 --fee-bps 5 --fee-bps 10 \
        --rolling-window 30 \
        --min-window 10 \
        --output-json research/regime_v2_price_action_guardrail_validation.json \
        --output-md research/regime_v2_price_action_guardrail_validation.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _min_since_for_pair, _pairs_from_records
from libs.selection.regime_v2_price_action_guardrail_validation import (
    build_price_action_guardrail_validation,
    render_price_action_guardrail_validation_markdown,
)
from libs.selection.regime_v2_shadow_report import load_regime_v2_shadow_decisions


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
        Path(args.output_md).write_text(render_price_action_guardrail_validation_markdown(payload), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    records, invalid = load_regime_v2_shadow_decisions(args.log)
    pairs = _pairs_from_records(records)
    ohlcv_by_pair: dict[tuple[str, str], pd.DataFrame] = {}
    fetch_errors: dict[str, str] = {}
    for asset, timeframe in pairs:
        try:
            ohlcv_by_pair[(asset, timeframe)] = await fetch_binance_native_ohlcv(
                symbol=asset,
                timeframe=timeframe,
                limit=args.limit,
                since=_min_since_for_pair(records, asset, timeframe),
                until=None,
            )
        except Exception as exc:
            fetch_errors[f"{asset}|{timeframe}"] = str(exc)

    report = build_price_action_guardrail_validation(
        records,
        ohlcv_by_pair,
        direction=args.direction,
        horizons=tuple(args.horizon),
        fees_bps=tuple(args.fee_bps),
        rolling_window=args.rolling_window,
        min_window=args.min_window,
    )
    report["source_log"] = args.log
    report["source_invalid_shadow_records"] = invalid
    report["pairs"] = [f"{asset}|{timeframe}" for asset, timeframe in pairs]
    report["fetch_errors"] = fetch_errors
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate PriceAction direction-aware guardrail using Binance OHLCV.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl")
    parser.add_argument("--direction", type=int, default=1)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--horizon", action="append", type=int, default=None)
    parser.add_argument("--fee-bps", action="append", type=float, default=None)
    parser.add_argument("--rolling-window", type=int, default=30)
    parser.add_argument("--min-window", type=int, default=10)
    parser.add_argument("--output-json", default="research/regime_v2_price_action_guardrail_validation.json")
    parser.add_argument("--output-md", default="research/regime_v2_price_action_guardrail_validation.md")
    args = parser.parse_args(argv)
    args.horizon = args.horizon or [3, 6, 12, 24]
    args.fee_bps = args.fee_bps or [2.0, 5.0, 10.0]
    return args


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
