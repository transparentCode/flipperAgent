#!/usr/bin/env python
"""Run an offline Optuna alpha ladder for RegimeClassification descriptors."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from libs.models.regime_classification.optimization.alpha_ladder import (
    run_alpha_ladder,
    run_rolling_alpha_ladder,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.data_fetcher import fetch_historical_ohlcv
from libs.optim_utils.two_stage_optimizer import TwoStageOptimizer


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optuna alpha ladder for RegimeClassification descriptors.",
    )
    parser.add_argument("--assets", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--asset", default=None, help="Asset label for --input-csv mode")
    parser.add_argument("--timeframes", nargs="+", default=["1h"])
    parser.add_argument("--timeframe", default=None, help="Timeframe for --input-csv mode")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--input-csv", type=str, default=None)
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--alpha-trials", type=int, default=None)
    parser.add_argument("--regime-screening-trials", type=int, default=0)
    parser.add_argument("--regime-main-trials", type=int, default=0)
    parser.add_argument("--rolling", action="store_true")
    parser.add_argument("--fold-bars", type=int, default=None)
    parser.add_argument("--step-bars", type=int, default=None)
    parser.add_argument("--show-hmm-warnings", action="store_true")
    args = parser.parse_args()

    if not args.show_hmm_warnings:
        logging.getLogger("hmmlearn").setLevel(logging.ERROR)
        logging.getLogger("hmmlearn.base").setLevel(logging.ERROR)

    reports: list[dict[str, Any]] = []
    if args.input_csv:
        asset = args.asset or (args.assets[0] if args.assets else "")
        timeframe = args.timeframe or (args.timeframes[0] if args.timeframes else "1h")
        reports.append(_run_one(_load_csv(args.input_csv), asset, timeframe, args))
    else:
        for asset in args.assets:
            for timeframe in args.timeframes:
                frame = _fetch_frame(asset, timeframe, args.days)
                reports.append(_run_one(frame, asset, timeframe, args))

    payload = {"reports": reports, "panel_summary": _summarize(reports)}
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
    args: argparse.Namespace,
) -> dict[str, Any]:
    settings_override: dict[str, Any] = {}
    if args.alpha_trials is not None:
        settings_override = {"alpha_ladder": {"n_trials": args.alpha_trials}}
    settings = load_regime_optimization_settings(settings_override)
    regime_result = None
    params = None
    frozen_overrides = None
    if args.regime_screening_trials > 0 and args.regime_main_trials > 0:
        optimizer = TwoStageOptimizer(
            screening_trials=args.regime_screening_trials,
            main_trials=args.regime_main_trials,
            convergence_patience=max(10, args.regime_main_trials // 2),
            seed=int(settings.get("study", {}).get("seed", 42)),
        )
        regime_result = optimizer.run(
            "RegimeClassification",
            frame,
            timeframe=timeframe,
            train_ratio=float(settings["benchmark_ladder"].get("train_ratio", 0.60)),
            val_ratio=float(settings["benchmark_ladder"].get("val_ratio", 0.20)),
            purge_bars=int(settings["benchmark_ladder"].get("purge_bars", 24)),
        )
        params = regime_result.best_params.get("params", {})
        frozen_overrides = regime_result.best_params.get("frozen_overrides", {})

    if args.rolling:
        report = run_rolling_alpha_ladder(
            frame,
            asset=asset,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
            settings=settings,
            fold_bars=args.fold_bars,
            step_bars=args.step_bars,
        )
    else:
        report = run_alpha_ladder(
            frame,
            asset=asset,
            timeframe=timeframe,
            params=params,
            frozen_overrides=frozen_overrides,
            settings=settings,
        )
    if regime_result is not None:
        report["regime_optimizer"] = regime_result.model_dump()
    return report


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


def _summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [row for row in reports if row.get("status") == "ok"]
    decisions: dict[str, int] = {}
    for row in usable:
        decision = row.get("panel_decision") or row.get("summary", {}).get(
            "decision",
            "reject",
        )
        decisions[decision] = decisions.get(decision, 0) + 1
    return {
        "usable_slices": len(usable),
        "total_slices": len(reports),
        "decision_counts": decisions,
        "promoted_slices": decisions.get("promote_to_downstream_research", 0),
        "rejected_slices": decisions.get("reject", 0),
    }


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)


if __name__ == "__main__":
    main()
