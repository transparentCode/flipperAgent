#!/usr/bin/env python
"""Validate TradingView CSV backfills before using them in research.

This script is intentionally offline-only: it checks already fetched CSV files
for usable history length, duplicate timestamps, monotonicity, and large gaps.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1D": 86400,
}


@dataclass(frozen=True)
class QualityReport:
    path: str
    status: str
    reasons: list[str]
    rows: int
    duplicate_timestamps: int
    start: str | None
    end: str | None
    days: float
    expected_interval_seconds: int
    gap_count: int
    max_gap_seconds: int
    sparse_allowed: bool


def infer_timeframe(path: Path) -> str:
    match = re.search(r"_(1m|5m|15m|30m|1h|2h|4h|1d|1D)(?:_|\\.)", path.name)
    if not match:
        raise ValueError(f"Cannot infer timeframe from {path}; pass --timeframe")
    return match.group(1)


def infer_expected_seconds(path: Path, timeframe: str | None = None) -> int:
    if _looks_like_funding(path):
        return 8 * 3600
    tf = timeframe or infer_timeframe(path)
    if tf not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe {tf!r}")
    return TIMEFRAME_SECONDS[tf]


def _looks_like_funding(path: Path) -> bool:
    name = path.name.upper()
    return ".P_FR" in name or "_FR_" in name or "FUNDING" in name


def load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        raise ValueError(f"{path} is missing required timestamp column")
    if "datetime" not in frame.columns:
        frame["datetime"] = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
    else:
        frame["datetime"] = pd.to_datetime(frame["datetime"], utc=True)
    return frame


def evaluate_file(
    path: Path,
    *,
    min_days: float,
    timeframe: str | None = None,
    max_gap_multiplier: float = 3.0,
    sparse_allowed: bool | None = None,
) -> QualityReport:
    expected_seconds = infer_expected_seconds(path, timeframe)
    allow_sparse = _looks_like_funding(path) if sparse_allowed is None else sparse_allowed
    reasons: list[str] = []

    try:
        frame = load_csv(path)
    except Exception as exc:
        return QualityReport(
            path=str(path),
            status="invalid",
            reasons=[str(exc)],
            rows=0,
            duplicate_timestamps=0,
            start=None,
            end=None,
            days=0.0,
            expected_interval_seconds=expected_seconds,
            gap_count=0,
            max_gap_seconds=0,
            sparse_allowed=allow_sparse,
        )

    rows = len(frame)
    if rows == 0:
        reasons.append("empty")
        return QualityReport(
            path=str(path),
            status="empty",
            reasons=reasons,
            rows=0,
            duplicate_timestamps=0,
            start=None,
            end=None,
            days=0.0,
            expected_interval_seconds=expected_seconds,
            gap_count=0,
            max_gap_seconds=0,
            sparse_allowed=allow_sparse,
        )

    duplicate_timestamps = int(frame["timestamp"].duplicated().sum())
    if duplicate_timestamps:
        reasons.append("duplicate_timestamps")

    clean = (
        frame.drop_duplicates(subset=["timestamp"], keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    start_dt = clean["datetime"].min()
    end_dt = clean["datetime"].max()
    days = float((end_dt - start_dt).total_seconds() / 86400)
    if days < min_days:
        reasons.append("insufficient_history")

    timestamps = clean["timestamp"].astype(int).to_numpy()
    deltas = [int(timestamps[idx] - timestamps[idx - 1]) for idx in range(1, len(timestamps))]
    max_gap_seconds = max(deltas) if deltas else 0
    gap_threshold = int(expected_seconds * max_gap_multiplier)
    gap_count = sum(1 for delta in deltas if delta > gap_threshold)
    if gap_count and not allow_sparse:
        reasons.append("large_gaps")

    status = "ok" if not reasons else "reject"
    return QualityReport(
        path=str(path),
        status=status,
        reasons=reasons,
        rows=rows,
        duplicate_timestamps=duplicate_timestamps,
        start=start_dt.isoformat(),
        end=end_dt.isoformat(),
        days=round(days, 3),
        expected_interval_seconds=expected_seconds,
        gap_count=gap_count,
        max_gap_seconds=max_gap_seconds,
        sparse_allowed=allow_sparse,
    )


def expand_inputs(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        matches = sorted(Path().glob(item)) if any(ch in item for ch in "*?[") else [Path(item)]
        paths.extend(match for match in matches if match.is_file())
    return sorted(dict.fromkeys(paths))


def build_manifest(reports: list[QualityReport]) -> dict[str, Any]:
    accepted = [report.path for report in reports if report.status == "ok"]
    rejected = [report.path for report in reports if report.status != "ok"]
    return {
        "summary": {
            "total": len(reports),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "accepted_paths": accepted,
        "rejected_paths": rejected,
        "reports": [asdict(report) for report in reports],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate TradingView backfill CSV quality.")
    parser.add_argument("inputs", nargs="+", help="CSV files or shell-style globs")
    parser.add_argument("--timeframe", default=None, help="Override timeframe for all non-funding files")
    parser.add_argument("--min-days", type=float, default=0.0)
    parser.add_argument("--max-gap-multiplier", type=float, default=3.0)
    parser.add_argument("--allow-sparse", action="store_true", help="Allow large gaps for every input")
    parser.add_argument("--output", default=None, help="Optional JSON manifest path")
    parser.add_argument("--no-fail", action="store_true", help="Exit 0 even if some files are rejected")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = expand_inputs(args.inputs)
    if not paths:
        raise SystemExit("No input CSV files matched")

    reports = [
        evaluate_file(
            path,
            min_days=args.min_days,
            timeframe=args.timeframe,
            max_gap_multiplier=args.max_gap_multiplier,
            sparse_allowed=True if args.allow_sparse else None,
        )
        for path in paths
    ]
    manifest = build_manifest(reports)
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    print(text)

    if manifest["summary"]["rejected"] and not args.no_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
