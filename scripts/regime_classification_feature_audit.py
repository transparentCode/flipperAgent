#!/usr/bin/env python
"""Run RegimeClassification feature ablation audit."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.models.regime_classification.optimization.feature_audit import (  # noqa: E402
    run_feature_ablation_audit,
)
from libs.models.regime_classification.optimization.settings import (  # noqa: E402
    load_regime_optimization_settings,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Feature ablation audit for RegimeClassification descriptors.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--asset", default=None, help="Asset label for --input-csv mode")
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--timeframe", default=None, help="Timeframe for --input-csv mode")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--input-csv", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--fold-bars", type=int, default=None)
    parser.add_argument("--step-bars", type=int, default=None)
    parser.add_argument("--target-kinds", nargs="+", default=None)
    parser.add_argument(
        "--feature-set",
        action="append",
        default=None,
        help="Comma-separated descriptor set; repeat to define audit candidates.",
    )
    args = parser.parse_args()

    prob_override: dict[str, Any] = {}
    if args.target_kinds is not None:
        prob_override["target_kinds"] = args.target_kinds
    if args.feature_set is not None:
        prob_override["feature_sets"] = [
            [col.strip() for col in raw.split(",") if col.strip()]
            for raw in args.feature_set
        ]
    settings = load_regime_optimization_settings(
        {"probability_ladder": prob_override} if prob_override else None
    )

    reports: list[dict[str, Any]] = []
    if args.input_csv:
        asset = args.asset or (args.assets[0] if args.assets else "")
        timeframe = args.timeframe or (args.timeframes[0] if args.timeframes else "1h")
        reports.append(
            _run_one(_load_csv(args.input_csv), asset, timeframe, settings, args)
        )
    else:
        for asset in args.assets:
            for timeframe in args.timeframes:
                reports.append(
                    _run_one(
                        _fetch_frame(asset, timeframe, args.days),
                        asset,
                        timeframe,
                        settings,
                        args,
                    )
                )

    payload = {"reports": reports, "panel_summary": _panel_summary(reports)}
    text = json.dumps(payload, indent=2, default=_json_default)
    print(text)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def _run_one(
    frame: pd.DataFrame,
    asset: str,
    timeframe: str,
    settings: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    return run_feature_ablation_audit(
        frame,
        asset=asset,
        timeframe=timeframe,
        settings=settings,
        rolling=args.rolling,
        fold_bars=args.fold_bars,
        step_bars=args.step_bars,
    )


def _fetch_frame(asset: str, timeframe: str, days: int) -> pd.DataFrame:
    since_ms = int((time.time() - days * 86_400) * 1000)
    limit = max(_bars_for_timeframe(timeframe, days), 500)
    frame = fetch_historical_ohlcv(
        symbol=asset,
        timeframe=timeframe,
        since=since_ms,
        limit=limit,
    )
    if "timestamp" in frame.columns:
        frame.index = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame


def _load_csv(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    for col in ("datetime", "timestamp", "time"):
        if col in frame.columns:
            if col == "timestamp":
                frame.index = pd.to_datetime(frame[col], unit="ms", utc=True)
            else:
                frame.index = pd.to_datetime(frame[col], utc=True)
            break
    return frame


def _bars_for_timeframe(timeframe: str, days: int) -> int:
    suffix = timeframe[-1].lower()
    value = int(timeframe[:-1])
    if suffix == "m":
        return int(days * 24 * 60 / value)
    if suffix == "h":
        return int(days * 24 / value)
    if suffix == "d":
        return int(days / value)
    return days * 24


def _panel_summary(reports: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {"keep": 0, "drop": 0, "conditional_by_asset_tf": 0}
    for report in reports:
        for feature in report.get("features", []):
            action = str(feature.get("action", "drop"))
            counts[action] = counts.get(action, 0) + 1
    return {"total_reports": len(reports), "action_counts": counts}


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
