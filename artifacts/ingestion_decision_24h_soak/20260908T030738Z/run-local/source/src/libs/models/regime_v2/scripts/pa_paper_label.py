"""Label PA paper guardrail records with Binance future returns."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import pandas as pd

from libs.models.regime_v2.scripts.compare_binance_native import fetch_binance_native_ohlcv
from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _min_since_for_pair, _pairs_from_records
from libs.selection.regime_v2_pa_paper_report import (
    build_pa_paper_outcome_report,
    label_pa_paper_outcomes,
    load_pa_paper_decisions,
    render_pa_paper_outcome_report_markdown,
    write_labeled_pa_paper_outcomes,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    payload = asyncio.run(_run(args))
    text = json.dumps(_json_safe(payload["report"]), indent=2, sort_keys=True)
    print(text)
    if args.output_jsonl:
        write_labeled_pa_paper_outcomes(payload["labeled"], args.output_jsonl)
    if args.report_json:
        Path(args.report_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_json).write_text(text + "\n", encoding="utf-8")
    if args.report_md:
        Path(args.report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_md).write_text(render_pa_paper_outcome_report_markdown(payload["report"]), encoding="utf-8")
    return 0


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    records, invalid = load_pa_paper_decisions(args.log)
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
    labeled = label_pa_paper_outcomes(
        records,
        ohlcv_by_pair,
        horizon_bars=args.horizon_bars,
        fee_bps=args.fee_bps,
    )
    report = build_pa_paper_outcome_report(
        labeled,
        source_path=args.output_jsonl or args.log,
        invalid_record_count=invalid,
    )
    report["source_log"] = args.log
    report["pairs"] = [f"{asset}|{timeframe}" for asset, timeframe in pairs]
    report["fetch_errors"] = fetch_errors
    return {"labeled": labeled, "report": report}


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label PA paper records with Binance OHLCV outcomes.")
    parser.add_argument("--log", default="logs/regime_v2_pa_asset_paper_decisions.jsonl")
    parser.add_argument("--limit", type=int, default=1200)
    parser.add_argument("--horizon-bars", type=int, default=12)
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument("--output-jsonl", default="research/regime_v2_pa_paper_outcomes.jsonl")
    parser.add_argument("--report-json", default="research/regime_v2_pa_paper_outcome_report.json")
    parser.add_argument("--report-md", default="research/regime_v2_pa_paper_outcome_report.md")
    return parser.parse_args(argv)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(val) for val in value]
    if isinstance(value, tuple):
        return [_json_safe(val) for val in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


if __name__ == "__main__":
    raise SystemExit(main())
