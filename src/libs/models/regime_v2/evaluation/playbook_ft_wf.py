"""Walk-forward validation for Phase 7F follow-through candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import (
    build_breakout_followthrough_outcome_matrix,
)

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_ft_walkforward_report(
    refined_state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    split_count: int = 4,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
) -> dict[str, Any]:
    """Validate a refined 7F candidate on chronological walk-forward splits."""
    splits = _split_frame(refined_state_df, int(split_count))
    split_reports = []
    for index, split in enumerate(splits, start=1):
        split_reports.append(
            _split_report(
                split,
                ohlcv,
                split_index=index,
                total_splits=len(splits),
                horizons=tuple(int(h) for h in horizons),
                fees_bps=tuple(float(f) for f in fees_bps),
                min_split_support=int(min_split_support),
                min_passing_rate=float(min_passing_rate),
                min_avg_return=float(min_avg_return),
                max_worst_loss=float(max_worst_loss),
            )
        )
    passed = [row for row in split_reports if row.get("split_passed")]
    support_failures = [row for row in split_reports if "low_support" in row.get("failure_reasons", [])]
    negative_failures = [row for row in split_reports if "avg_return_too_low" in row.get("failure_reasons", []) or "worst_cell_too_negative" in row.get("failure_reasons", [])]
    active_total = int(sum(int(row.get("active_count") or 0) for row in split_reports))
    return {
        "phase": "phase_7h_ft_walkforward",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "split_count": len(split_reports),
            "passed_split_count": len(passed),
            "failed_split_count": len(split_reports) - len(passed),
            "active_total": active_total,
            "min_split_support": int(min_split_support),
            "min_passing_rate": float(min_passing_rate),
            "min_avg_return": float(min_avg_return),
            "max_worst_loss": float(max_worst_loss),
            "ready": len(split_reports) > 0 and len(passed) == len(split_reports),
            "recommendation": "walkforward_candidate" if len(split_reports) > 0 and len(passed) == len(split_reports) else "hold_off_walkforward_unstable",
            "support_failure_count": len(support_failures),
            "negative_failure_count": len(negative_failures),
            "direction_distribution": _aggregate_directions(split_reports),
            "avg_split_directional_return": _mean(row.get("avg_directional_net_return") for row in split_reports),
            "worst_split_directional_return": _min(row.get("worst_directional_net_return") for row in split_reports),
        },
        "splits": split_reports,
    }


def build_ft_walkforward_matrix_report(
    variant_reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize multiple threshold walk-forward reports."""
    variants = [dict(report.get("summary", {})) | {"splits": list(report.get("splits", []))} for report in variant_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            int(row.get("active_total") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7h_ft_walkforward_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "walkforward_candidate_found" if ready else "hold_off_walkforward_unstable",
        },
        "variants": variants,
    }


def render_ft_walkforward_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for one walk-forward report or matrix report."""
    phase = report.get("phase")
    if phase == "phase_7h_ft_walkforward_matrix":
        return _render_matrix(report)
    return _render_single(report)


def _split_report(
    split: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    split_index: int,
    total_splits: int,
    horizons: Sequence[int],
    fees_bps: Sequence[float],
    min_split_support: int,
    min_passing_rate: float,
    min_avg_return: float,
    max_worst_loss: float,
) -> dict[str, Any]:
    active = split[split.get("breakout_followthrough_active") == True]
    matrix = build_breakout_followthrough_outcome_matrix(split, ohlcv, horizons=horizons, fees_bps=fees_bps)
    cells = [dict(cell) for cell in matrix.get("cells", [])]
    passing = [cell for cell in cells if _cell_pass(cell, min_avg_return)]
    values = [float(cell.get("avg_directional_net_return")) for cell in cells if cell.get("avg_directional_net_return") is not None]
    avg = sum(values) / len(values) if values else None
    worst = min(values) if values else None
    pass_rate = float(len(passing)) / float(len(cells)) if cells else 0.0
    directions = _directions(active)
    reasons = []
    if int(len(active)) < min_split_support:
        reasons.append("low_support")
    if pass_rate < min_passing_rate:
        reasons.append("low_passing_rate")
    if avg is None or avg < min_avg_return:
        reasons.append("avg_return_too_low")
    if worst is None or worst < -abs(max_worst_loss):
        reasons.append("worst_cell_too_negative")
    if len([value for value in directions.values() if int(value) > 0]) < 1:
        reasons.append("no_direction")
    return {
        "split_index": int(split_index),
        "split_count": int(total_splits),
        "start_timestamp": str(split.index[0]) if len(split) else None,
        "end_timestamp": str(split.index[-1]) if len(split) else None,
        "row_count": int(len(split)),
        "active_count": int(len(active)),
        "direction_distribution": directions,
        "cell_count": len(cells),
        "passing_cell_count": len(passing),
        "passing_cell_rate": pass_rate,
        "avg_directional_net_return": avg,
        "worst_directional_net_return": worst,
        "best_cell": matrix.get("summary", {}).get("best_cell"),
        "worst_cell": matrix.get("summary", {}).get("worst_cell"),
        "split_passed": not reasons,
        "failure_reasons": reasons,
    }


def _split_frame(frame: pd.DataFrame, split_count: int) -> list[pd.DataFrame]:
    if frame.empty:
        return []
    count = max(1, int(split_count))
    size = len(frame)
    splits = []
    for index in range(count):
        start = int(round(index * size / count))
        end = int(round((index + 1) * size / count))
        splits.append(frame.iloc[start:end].copy())
    return [split for split in splits if len(split) > 0]


def _cell_pass(cell: Mapping[str, Any], min_avg_return: float) -> bool:
    avg = cell.get("avg_directional_net_return")
    pos = cell.get("directional_positive_rate")
    count = int(cell.get("labeled_count") or 0)
    if avg is None or pos is None or count <= 0:
        return False
    return float(avg) > float(min_avg_return) and float(pos) >= 0.50


def _directions(frame: pd.DataFrame) -> dict[str, int]:
    if frame.empty or "breakout_followthrough_direction" not in frame.columns:
        return {}
    return dict(Counter(str(value) for value in frame["breakout_followthrough_direction"].dropna().tolist()).most_common())


def _aggregate_directions(splits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for split in splits:
        counter.update(dict(split.get("direction_distribution", {})))
    return dict(counter.most_common())


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "threshold": row.get("threshold"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "active_total": row.get("active_total"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
        "ready": row.get("ready"),
        "recommendation": row.get("recommendation"),
    }


def _render_single(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7H Follow-Through Walk-Forward",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
        f"- Active total: {summary.get('active_total')}",
        f"- Ready: {summary.get('ready')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
        "## Splits",
        "",
        "| Split | Rows | Active | Passing | Avg dir | Worst dir | Ready | Reasons |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for split in report.get("splits", []):
        lines.append(
            "| {idx} | {rows} | {active} | {passing}/{cells} | {avg} | {worst} | {ready} | {reasons} |".format(
                idx=split.get("split_index"),
                rows=split.get("row_count"),
                active=split.get("active_count"),
                passing=split.get("passing_cell_count"),
                cells=split.get("cell_count"),
                avg=split.get("avg_directional_net_return"),
                worst=split.get("worst_directional_net_return"),
                ready=split.get("split_passed"),
                reasons=",".join(split.get("failure_reasons", [])) or "none",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_matrix(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7H Follow-Through Walk-Forward Matrix",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Thresholds: {summary.get('thresholds', [])}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        f"- Best ready variant: {summary.get('best_ready_variant')}",
        "",
        "## Variants",
        "",
        "| Threshold | Passed | Active | Avg split dir | Worst split dir | Ready |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {thr} | {passed}/{splits} | {active} | {avg} | {worst} | {ready} |".format(
                thr=row.get("threshold"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                active=row.get("active_total"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _mean(values) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return sum(nums) / len(nums) if nums else None


def _min(values) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return min(nums) if nums else None


__all__ = ["build_ft_walkforward_matrix_report", "build_ft_walkforward_report", "render_ft_walkforward_markdown"]
