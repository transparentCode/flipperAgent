"""Label RegimeV2 shadow-decision outcomes using on-demand Binance candles.

Example:
    PYTHONPATH=src python -m libs.models.regime_v2.scripts.label_shadow_outcomes_binance \
        --log logs/regime_v2_shadow_decisions.jsonl \
        --limit 700 \
        --horizon-bars 12 \
        --fee-bps 5 \
        --output-jsonl research/regime_v2_shadow_outcomes.jsonl \
        --report-json research/regime_v2_shadow_outcome_report.json \
        --report-md research/regime_v2_shadow_outcome_report.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.selection.regime_v2_shadow_outcomes import (
    build_shadow_outcome_report,
    label_shadow_decision_outcomes,
    load_labeled_shadow_outcomes,
    render_shadow_outcome_report_markdown,
    write_labeled_shadow_outcomes,
)
from libs.selection.regime_v2_shadow_report import load_regime_v2_shadow_decisions


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload), indent=2, sort_keys=True)
    print(text)
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

    labeled = label_shadow_decision_outcomes(
        records,
        ohlcv_by_pair,
        horizon_bars=args.horizon_bars,
        fee_bps=args.fee_bps,
    )
    output_jsonl = write_labeled_shadow_outcomes(labeled, args.output_jsonl)
    loaded_labeled, invalid_labeled = load_labeled_shadow_outcomes(output_jsonl)
    report = build_shadow_outcome_report(
        loaded_labeled,
        source_path=str(output_jsonl),
        invalid_record_count=invalid_labeled,
    )
    report["fetch_errors"] = fetch_errors
    report["source_invalid_shadow_records"] = invalid

    if args.report_json:
        Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_json).write_text(json.dumps(_json_safe(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.report_md:
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text(render_shadow_outcome_report_markdown(report), encoding="utf-8")

    return {
        "phase": "phase_6_shadow_outcome_labeling_binance",
        "input_log": args.log,
        "output_jsonl": str(output_jsonl),
        "report_json": args.report_json,
        "report_md": args.report_md,
        "pairs": [f"{asset}|{timeframe}" for asset, timeframe in pairs],
        "fetch_errors": fetch_errors,
        "summary": report["summary"],
    }


def _pairs_from_records(records: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    pairs = sorted({(str(record.get("asset") or "").upper(), str(record.get("timeframe") or "")) for record in records})
    return tuple((asset, timeframe) for asset, timeframe in pairs if asset and timeframe)


def _min_since_for_pair(records: list[dict[str, Any]], asset: str, timeframe: str) -> int | None:
    timestamps: list[float] = []
    for record in records:
        if str(record.get("asset") or "").upper() != asset or str(record.get("timeframe") or "") != timeframe:
            continue
        try:
            timestamps.append(float(record["timestamp"]))
        except (KeyError, TypeError, ValueError):
            continue
    if not timestamps:
        return None
    earliest_ms = int(min(timestamps) * 1000)
    return max(0, earliest_ms - 24 * 60 * 60 * 1000)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label RegimeV2 shadow outcomes using Binance OHLCV.")
    parser.add_argument("--log", default="logs/regime_v2_shadow_decisions.jsonl")
    parser.add_argument("--limit", type=int, default=700)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--output-jsonl", default="research/regime_v2_shadow_outcomes.jsonl")
    parser.add_argument("--report-json", default="research/regime_v2_shadow_outcome_report.json")
    parser.add_argument("--report-md", default="research/regime_v2_shadow_outcome_report.md")
    return parser.parse_args(argv)


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
