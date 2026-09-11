"""Trendlines boundary drift monitor.

This workflow runs the canonical trendlines pipeline, adapts the fit result to a
boundary result, and compares the resulting quality snapshot against a stored
baseline.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
from binance.um_futures import UMFutures

from libs.models.trendlines import execute_trendline_pipeline
from libs.models.trendlines.boundary import build_boundary_result_from_trendline_result
from libs.models.trendlines.config import EvaluationConfig

_eval_cfg = EvaluationConfig()


logger = logging.getLogger("trendlines.workflow.drift_monitor")

_HIGHER_IS_BETTER = {
    "mean_score",
    "mean_touch_count",
    "mean_r_squared",
    "best_support_score",
    "best_support_r_squared",
    "best_support_inlier_ratio",
    "best_support_coverage",
    "best_support_fit_span_bars",
    "best_resistance_score",
    "best_resistance_r_squared",
    "best_resistance_inlier_ratio",
    "best_resistance_coverage",
    "best_resistance_fit_span_bars",
}

_LOWER_IS_BETTER = {
    "hull_width_atr",
    "best_support_cut_fraction",
    "best_resistance_cut_fraction",
}


def _fetch_futures_klines(
    asset: str,
    timeframe: str,
    *,
    limit: int = 1000,
) -> pd.DataFrame:
    client = UMFutures()
    klines = client.klines(symbol=asset, interval=timeframe, limit=limit)

    frame = pd.DataFrame(
        klines,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )
    numeric_columns = ["open", "high", "low", "close", "volume", "quote_volume"]
    frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric)
    frame["open_time"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    frame.set_index("open_time", inplace=True)
    return frame


def _extract_ray_snapshot(ray, prefix: str) -> Dict[str, float]:
    snapshot = {
        f"{prefix}_score": 0.0,
        f"{prefix}_r_squared": 0.0,
        f"{prefix}_inlier_ratio": 0.0,
        f"{prefix}_coverage": 0.0,
        f"{prefix}_cut_fraction": 0.0,
        f"{prefix}_fit_span_bars": 0.0,
    }
    if ray is None:
        return snapshot

    metadata = ray.metadata or {}
    fit_start = metadata.get("fit_start_index")
    fit_end = metadata.get("fit_end_index")
    fit_span_bars = 0.0
    if fit_start is not None and fit_end is not None:
        fit_span_bars = float(max(int(fit_end) - int(fit_start), 0))

    snapshot.update(
        {
            f"{prefix}_score": float(ray.score),
            f"{prefix}_r_squared": float(ray.r_squared),
            f"{prefix}_inlier_ratio": float(metadata.get("inlier_ratio", 0.0)),
            f"{prefix}_coverage": float(metadata.get("coverage", 0.0)),
            f"{prefix}_cut_fraction": float(metadata.get("cut_fraction", 0.0)),
            f"{prefix}_fit_span_bars": fit_span_bars,
        }
    )
    return snapshot


def build_monitor_snapshot(result) -> Dict[str, float]:
    metrics = asdict(result.quality_metrics) if result.quality_metrics is not None else {}
    metrics.update(_extract_ray_snapshot(result.best_support, "best_support"))
    metrics.update(_extract_ray_snapshot(result.best_resistance, "best_resistance"))
    return metrics


def load_baseline(path: str) -> Optional[Dict[str, float]]:
    from os import path as os_path

    if not os_path.exists(path):
        return None
    with open(path, "r") as handle:
        return json.load(handle)


def save_baseline(path: str, metrics: Dict[str, float]) -> None:
    from os import makedirs
    from os import path as os_path

    makedirs(os_path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        json.dump(metrics, handle, indent=2)
    logger.info("Baseline saved to %s", path)


def compare(
    current: Dict[str, float],
    baseline: Dict[str, float],
    threshold: float | None = None,
) -> Dict[str, Dict[str, float | str]]:
    resolved_threshold = threshold if threshold is not None else _eval_cfg.drift_monitor.threshold
    report: Dict[str, Dict[str, float | str]] = {}
    for key in _HIGHER_IS_BETTER:
        if key not in baseline:
            continue
        base_val = baseline[key]
        curr_val = current.get(key, 0.0)
        if base_val > 1e-9:
            delta_pct = (curr_val - base_val) / base_val
            if delta_pct < -resolved_threshold:
                report[key] = {
                    "baseline": base_val,
                    "current": curr_val,
                    "delta_pct": round(delta_pct * 100, 1),
                    "verdict": "DEGRADED",
                }

    for key in _LOWER_IS_BETTER:
        if key not in baseline:
            continue
        base_val = baseline[key]
        curr_val = current.get(key, 0.0)
        ref_val = base_val if abs(base_val) > 1e-9 else 1e-9
        delta_pct = (curr_val - base_val) / ref_val
        if delta_pct > resolved_threshold:
            report[key] = {
                "baseline": base_val,
                "current": curr_val,
                "delta_pct": round(delta_pct * 100, 1),
                "verdict": "DEGRADED",
            }

    return report


def _run_boundary_pipeline(asset: str, timeframe: str, df: pd.DataFrame):
    trendline_result, trendline_config = execute_trendline_pipeline(df)
    return build_boundary_result_from_trendline_result(
        df,
        asset=asset,
        timeframe=timeframe,
        trendline_result=trendline_result,
        trendline_config=trendline_config,
    )


def run_monitor(
    asset: str,
    timeframe: str,
    df: pd.DataFrame,
    baseline_path: str,
    threshold: float | None = None,
    update_baseline: bool = False,
) -> Dict[str, Any]:
    """Run the drift monitor on a single asset/timeframe and return a report."""
    resolved_threshold = threshold if threshold is not None else _eval_cfg.drift_monitor.threshold

    result = _run_boundary_pipeline(asset, timeframe, df)

    if not result.is_valid or result.quality_metrics is None:
        logger.warning("%s/%s: invalid result — cannot monitor drift", asset, timeframe)
        return {"status": "INVALID", "detail": "Pipeline returned is_valid=False"}

    current = build_monitor_snapshot(result)

    baseline = load_baseline(baseline_path)
    if baseline is None:
        logger.info("No baseline found at %s — creating initial baseline.", baseline_path)
        save_baseline(baseline_path, current)
        return {"status": "BASELINE_CREATED", "metrics": current}

    report = compare(current, baseline, resolved_threshold)

    if report:
        logger.warning(
            "%s/%s DRIFT DETECTED — %d metric(s) degraded beyond %.0f%%:",
            asset,
            timeframe,
            len(report),
            resolved_threshold * 100,
        )
        for key, detail in report.items():
            logger.warning(
                "  %-25s  baseline=%.4f  current=%.4f  delta=%.1f%%",
                key,
                detail["baseline"],
                detail["current"],
                detail["delta_pct"],
            )
    else:
        logger.info("%s/%s: all metrics within threshold (%.0f%%)", asset, timeframe, resolved_threshold * 100)

    if update_baseline:
        save_baseline(baseline_path, current)

    return {
        "status": "DRIFT" if report else "HEALTHY",
        "current": current,
        "baseline": baseline,
        "drift_report": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Trendlines boundary drift monitor")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--csv", help="Path to OHLCV CSV file (alternative to Binance)")
    parser.add_argument("--baseline-file", default="trendlines_boundary_baseline.json")
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Number of Binance futures klines to fetch when --csv is omitted",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Fractional threshold for drift detection (default from config)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite baseline with current metrics after comparison",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s  %(message)s",
    )

    if args.csv:
        df = pd.read_csv(args.csv, index_col=0, parse_dates=True)
    else:
        logger.info(
            "Fetching %s %s futures klines directly from Binance (%d bars)",
            args.asset,
            args.timeframe,
            args.limit,
        )
        df = _fetch_futures_klines(args.asset, args.timeframe, limit=args.limit)

    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is None:
        df.index = df.index.tz_localize(timezone.utc)
    elif isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index.tz_convert(timezone.utc)

    result = run_monitor(
        asset=args.asset,
        timeframe=args.timeframe,
        df=df,
        baseline_path=args.baseline_file,
        threshold=args.threshold,
        update_baseline=args.update_baseline,
    )

    if not args.quiet:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()