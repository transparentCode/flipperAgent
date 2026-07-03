"""Phase 7G matrix summary for direction-aware breakout follow-through variants."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def build_ft_matrix_report(
    variant_results: Sequence[Mapping[str, Any]],
    *,
    min_support: int = 10,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_cell_loss: float = 0.0010,
) -> dict[str, Any]:
    variants = [
        _variant(
            item,
            min_support=int(min_support),
            min_passing_rate=float(min_passing_rate),
            min_avg_return=float(min_avg_return),
            max_cell_loss=float(max_cell_loss),
        )
        for item in variant_results
    ]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passing_cells") or 0),
            float(row.get("avg_dir_return") or -999.0),
            int(row.get("active_count") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7g_ft_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "pair_count": len({row.get("pair") for row in variants}),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "min_support": int(min_support),
            "min_passing_rate": float(min_passing_rate),
            "min_avg_return": float(min_avg_return),
            "max_cell_loss": float(max_cell_loss),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_found" if ready else "hold_off_collect_more_or_refine",
            "pairs": _counts(row.get("pair") for row in variants),
            "ready_pairs": _counts(row.get("pair") for row in ready),
        },
        "variants": variants,
    }


def render_ft_matrix_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7G Follow-Through Matrix",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Pair count: {summary.get('pair_count', 0)}",
        f"- Thresholds: {summary.get('thresholds', [])}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        f"- Best ready variant: {summary.get('best_ready_variant')}",
        "",
        "## Variants",
        "",
        "| Pair | Threshold | Active | Passing | Avg dir | Worst dir | Directions | Ready | Reasons |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {pair} | {thr} | {active} | {passing}/{cells} | {avg} | {worst} | {dirs} | {ready} | {reasons} |".format(
                pair=row.get("pair"),
                thr=row.get("threshold"),
                active=row.get("active_count"),
                passing=row.get("passing_cells"),
                cells=row.get("cell_count"),
                avg=row.get("avg_dir_return"),
                worst=row.get("worst_dir_return"),
                dirs=row.get("directions"),
                ready=row.get("ready"),
                reasons=",".join(row.get("reasons", [])) or "none",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _variant(item: Mapping[str, Any], *, min_support: int, min_passing_rate: float, min_avg_return: float, max_cell_loss: float) -> dict[str, Any]:
    report_summary = dict(dict(item.get("followthrough_report", {})).get("summary", {}))
    matrix = dict(item.get("outcome_matrix", {}))
    cells = [dict(cell) for cell in matrix.get("cells", [])]
    active = int(report_summary.get("active_count") or 0)
    passing = [cell for cell in cells if _cell_pass(cell, min_avg_return)]
    values = [float(cell.get("avg_directional_net_return")) for cell in cells if cell.get("avg_directional_net_return") is not None]
    avg = sum(values) / len(values) if values else None
    worst = min(values) if values else None
    pass_rate = float(len(passing)) / float(len(cells)) if cells else 0.0
    dirs = dict(report_summary.get("direction_distribution", {}))
    reasons = []
    if active < min_support:
        reasons.append("low_support")
    if pass_rate < min_passing_rate:
        reasons.append("low_passing_rate")
    if avg is None or avg < min_avg_return:
        reasons.append("avg_return_too_low")
    if worst is None or worst < -abs(max_cell_loss):
        reasons.append("worst_cell_too_negative")
    if len([value for value in dirs.values() if int(value) > 0]) < 2:
        reasons.append("single_direction")
    asset = item.get("asset") or report_summary.get("asset")
    timeframe = item.get("timeframe") or report_summary.get("timeframe")
    return {
        "asset": asset,
        "timeframe": timeframe,
        "pair": f"{asset}|{timeframe}",
        "threshold": float(item.get("threshold") or item.get("min_followthrough_score") or 0.0),
        "active_count": active,
        "eligible_count": int(report_summary.get("eligible_count") or 0),
        "cell_count": len(cells),
        "passing_cells": len(passing),
        "passing_rate": pass_rate,
        "avg_dir_return": avg,
        "worst_dir_return": worst,
        "best_cell": matrix.get("summary", {}).get("best_cell"),
        "worst_cell": matrix.get("summary", {}).get("worst_cell"),
        "directions": dirs,
        "ready": not reasons,
        "reasons": reasons,
    }


def _cell_pass(cell: Mapping[str, Any], min_avg_return: float) -> bool:
    avg = cell.get("avg_directional_net_return")
    pos = cell.get("directional_positive_rate")
    count = int(cell.get("labeled_count") or 0)
    if avg is None or pos is None or count <= 0:
        return False
    return float(avg) > float(min_avg_return) and float(pos) >= 0.50


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "pair": row.get("pair"),
        "threshold": row.get("threshold"),
        "active_count": row.get("active_count"),
        "passing_cells": row.get("passing_cells"),
        "cell_count": row.get("cell_count"),
        "avg_dir_return": row.get("avg_dir_return"),
        "worst_dir_return": row.get("worst_dir_return"),
        "ready": row.get("ready"),
        "reasons": list(row.get("reasons", [])),
    }


def _counts(values) -> dict[str, int]:
    return dict(Counter(str(value) for value in values if value is not None).most_common())


__all__ = ["build_ft_matrix_report", "render_ft_matrix_markdown"]
