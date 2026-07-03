"""Compact diagnostics for Phase 7I failed follow-through windows."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import label_breakout_followthrough_outcomes


def build_ft_failure_diagnostics(
    refined_state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    split_count: int = 4,
    failed_split_indices: Sequence[int] | None = None,
    horizons: Sequence[int] = (3, 6, 12, 24),
    fees_bps: Sequence[float] = (2.0, 5.0, 10.0),
) -> dict[str, Any]:
    failed = set(int(value) for value in failed_split_indices or [])
    splits = []
    for idx, frame in enumerate(_split(refined_state_df, split_count), start=1):
        item = _split_item(frame, ohlcv, idx=idx, horizons=horizons, fees_bps=fees_bps)
        item["target_failed_split"] = idx in failed if failed else bool(item["hypotheses"])
        splits.append(item)
    targets = [item for item in splits if item["target_failed_split"]]
    return {
        "phase": "phase_7i_ft_failure_diagnostics",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "split_count": len(splits),
            "target_failed_split_count": len(targets),
            "active_total": sum(int(item["active_count"]) for item in splits),
            "target_active_total": sum(int(item["active_count"]) for item in targets),
            "dominant_hypotheses": _hypothesis_counts(targets),
            "target_direction_distribution": _aggregate(targets, "direction_distribution"),
            "recommendation": _recommend(targets),
        },
        "splits": splits,
    }


def build_ft_failure_diagnostics_matrix(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    variants = [dict(report.get("summary", {})) | {"splits": list(report.get("splits", []))} for report in reports]
    targets = [split for variant in variants for split in variant.get("splits", []) if split.get("target_failed_split")]
    return {
        "phase": "phase_7i_ft_failure_diagnostics_matrix",
        "summary": {
            "variant_count": len(variants),
            "thresholds": sorted({float(variant.get("threshold") or 0.0) for variant in variants}),
            "dominant_hypotheses": _hypothesis_counts(targets),
            "recommendation": "add_invalidation_or_context_filter_before_retest",
        },
        "variants": variants,
    }


def render_ft_failure_diagnostics_markdown(report: Mapping[str, Any]) -> str:
    if report.get("phase") == "phase_7i_ft_failure_diagnostics_matrix":
        summary = dict(report.get("summary", {}))
        return "\n".join(
            [
                "# RegimeV2 Phase 7I Failure Diagnostics Matrix",
                "",
                f"- Recommendation: {summary.get('recommendation')}",
                f"- Dominant hypotheses: {summary.get('dominant_hypotheses')}",
                "",
            ]
        )
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7I Failure Diagnostics",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Target failed splits: {summary.get('target_failed_split_count')}",
        f"- Dominant hypotheses: {summary.get('dominant_hypotheses')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
        "| Split | Active | Directions | Short avg | Long avg | Worst | Target | Hypotheses |",
        "|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for item in report.get("splits", []):
        worst = item.get("worst_cell") or {}
        lines.append(
            f"| {item.get('split_index')} | {item.get('active_count')} | {item.get('direction_distribution')} | "
            f"{item.get('short_avg')} | {item.get('long_avg')} | {worst.get('avg')} | "
            f"{item.get('target_failed_split')} | {','.join(item.get('hypotheses', [])) or 'none'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _split_item(frame: pd.DataFrame, ohlcv: pd.DataFrame, *, idx: int, horizons: Sequence[int], fees_bps: Sequence[float]) -> dict[str, Any]:
    active = frame[frame.get("breakout_followthrough_active") == True].copy()
    cells = []
    records = []
    for horizon in horizons:
        for fee in fees_bps:
            rows = label_breakout_followthrough_outcomes(active, ohlcv, horizon_bars=int(horizon), fee_bps=float(fee))
            records.extend(rows)
            cells.append(_cell(rows, int(horizon), float(fee)))
    features = _feature_means(active)
    directions = _counts(active.get("breakout_followthrough_direction", pd.Series(dtype=object)).dropna().tolist())
    direction_metrics = _group(records, "breakout_followthrough_direction")
    short_avg = _mean(cell["avg"] for cell in cells if cell["horizon"] <= 6)
    long_avg = _mean(cell["avg"] for cell in cells if cell["horizon"] >= 12)
    hypotheses = _hypotheses(features, direction_metrics, short_avg, long_avg, cells)
    return {
        "split_index": idx,
        "start_timestamp": str(frame.index[0]) if len(frame) else None,
        "end_timestamp": str(frame.index[-1]) if len(frame) else None,
        "row_count": len(frame),
        "active_count": len(active),
        "direction_distribution": directions,
        "feature_means": features,
        "short_avg": short_avg,
        "long_avg": long_avg,
        "best_cell": max(cells, key=lambda cell: cell["avg"] if cell["avg"] is not None else -999, default=None),
        "worst_cell": min(cells, key=lambda cell: cell["avg"] if cell["avg"] is not None else 999, default=None),
        "direction_metrics": direction_metrics,
        "hypotheses": hypotheses,
    }


def _cell(records: list[dict[str, Any]], horizon: int, fee: float) -> dict[str, Any]:
    labeled = [row for row in records if row.get("outcome_label") == "labeled"]
    return {
        "horizon": horizon,
        "fee_bps": fee,
        "count": len(labeled),
        "avg": _mean(row.get("directional_net_return") for row in labeled),
        "pos_rate": _rate(sum(1 for row in labeled if row.get("directional_positive")), len(labeled)),
    }


def _feature_means(frame: pd.DataFrame) -> dict[str, float | None]:
    cols = [
        "breakout_followthrough_hold_score",
        "breakout_followthrough_follow_score",
        "breakout_followthrough_direction_return_score",
        "breakout_followthrough_reversal_penalty",
        "breakout_followthrough_false_risk",
    ]
    return {col: _mean(frame[col].tolist()) if col in frame.columns else None for col in cols}


def _group(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        if row.get("outcome_label") == "labeled":
            groups.setdefault(str(row.get(key)), []).append(row)
    return {
        name: {
            "count": len(rows),
            "avg": _mean(row.get("directional_net_return") for row in rows),
            "pos_rate": _rate(sum(1 for row in rows if row.get("directional_positive")), len(rows)),
        }
        for name, rows in sorted(groups.items())
    }


def _hypotheses(features: Mapping[str, Any], direction_metrics: Mapping[str, Mapping[str, Any]], short_avg: float | None, long_avg: float | None, cells: Sequence[Mapping[str, Any]]) -> list[str]:
    tags = []
    if short_avg is not None and short_avg < 0:
        tags.append("short_horizon_directional_failure")
    if long_avg is not None and long_avg < 0:
        tags.append("long_horizon_directional_failure")
    worst = min((cell["avg"] for cell in cells if cell["avg"] is not None), default=None)
    if worst is not None and worst < -0.005:
        tags.append("large_worst_cell_loss")
    if float(features.get("breakout_followthrough_hold_score") or 0) < 0.5:
        tags.append("weak_boundary_hold")
    if float(features.get("breakout_followthrough_follow_score") or 0) < 0.5:
        tags.append("weak_followthrough")
    if float(features.get("breakout_followthrough_direction_return_score") or 0) < 0.4:
        tags.append("weak_directional_return_score")
    if float(features.get("breakout_followthrough_reversal_penalty") or 0) > 0.35:
        tags.append("high_reversal_pressure")
    bad = [name for name, row in direction_metrics.items() if row.get("avg") is not None and float(row.get("avg")) < 0]
    if bad:
        tags.append("direction_specific_failure:" + "+".join(sorted(bad)))
    return tags


def _split(frame: pd.DataFrame, split_count: int) -> list[pd.DataFrame]:
    size = len(frame)
    count = max(1, int(split_count))
    return [frame.iloc[int(round(i * size / count)) : int(round((i + 1) * size / count))].copy() for i in range(count)]


def _aggregate(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(dict(row.get(key, {})))
    return dict(counter.most_common())


def _hypothesis_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(row.get("hypotheses", []))
    return dict(counter.most_common())


def _recommend(targets: Sequence[Mapping[str, Any]]) -> str:
    counts = _hypothesis_counts(targets)
    if any(str(key).startswith("direction_specific_failure") for key in counts):
        return "add_direction_specific_invalidation_filter"
    if counts.get("high_reversal_pressure") or counts.get("weak_boundary_hold"):
        return "add_post_confirmation_hold_or_reversal_filter"
    if counts.get("long_horizon_directional_failure"):
        return "limit_horizon_or_add_long_horizon_exit"
    return "collect_more_failure_context"


def _counts(values) -> dict[str, int]:
    return dict(Counter(str(value) for value in values if value is not None).most_common())


def _mean(values) -> float | None:
    nums = []
    for value in values:
        try:
            if value is not None:
                nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


def _rate(num: int, den: int) -> float | None:
    return float(num) / float(den) if den > 0 else None


__all__ = ["build_ft_failure_diagnostics", "build_ft_failure_diagnostics_matrix", "render_ft_failure_diagnostics_markdown"]
