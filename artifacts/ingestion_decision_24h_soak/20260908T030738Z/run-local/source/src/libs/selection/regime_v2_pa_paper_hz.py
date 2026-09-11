"""Horizon-slice validation for PA paper gate-search results.

Phase 6X separates short-horizon failures from longer-horizon behavior using
an existing Phase 6W gate-search report. It is offline/report-only.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

_DEFAULT_LONG_HORIZONS = (12, 24)
_DEFAULT_SHORT_HORIZONS = (3,)


def build_pa_paper_horizon_report(
    gate_search_report: Mapping[str, Any],
    *,
    long_horizons: Sequence[int] = _DEFAULT_LONG_HORIZONS,
    short_horizons: Sequence[int] = _DEFAULT_SHORT_HORIZONS,
    require_long_all_pass: bool = True,
    require_short_failures_only: bool = True,
) -> dict[str, Any]:
    """Build a horizon-slice report from a gate-search report."""
    variants = [dict(row) for row in gate_search_report.get("variants", [])]
    summaries = [
        _variant_summary(
            row,
            long_horizons=tuple(int(value) for value in long_horizons),
            short_horizons=tuple(int(value) for value in short_horizons),
        )
        for row in variants
    ]
    summaries.sort(
        key=lambda row: (
            bool(row.get("long_horizon_candidate", False)),
            int(row.get("long", {}).get("passing_cell_count") or 0),
            -int(row.get("mid", {}).get("failed_cell_count") or 0),
            -int(row.get("short", {}).get("lost_avoided_loss_count") or 0),
            float(row.get("long", {}).get("avg_improvement") or 0.0),
        ),
        reverse=True,
    )
    best = summaries[0] if summaries else None
    candidate = _candidate_from_best(best, require_long_all_pass=require_long_all_pass, require_short_failures_only=require_short_failures_only)
    return {
        "phase": "phase_6x_pa_paper_horizon_slice",
        "summary": {
            "source_phase": gate_search_report.get("phase"),
            "variant_count": len(summaries),
            "long_horizons": list(long_horizons),
            "short_horizons": list(short_horizons),
            "best_variant": _compact(best),
            "long_horizon_candidate": bool(candidate),
            "recommendation": "long_horizon_paper_candidate" if candidate else "hold_off_no_horizon_candidate",
        },
        "variants": summaries,
    }


def render_pa_paper_horizon_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for horizon-slice validation."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6X PA Paper Horizon Slice",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Long horizons: {summary.get('long_horizons')}",
        f"- Short horizons: {summary.get('short_horizons')}",
        f"- Long-horizon candidate: {summary.get('long_horizon_candidate')}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        "",
        "## Variants",
        "",
        "| Variant | Long pass | Long lost | Long improvement | Short pass | Short lost | Mid pass | Candidate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        long = dict(row.get("long", {}))
        short = dict(row.get("short", {}))
        mid = dict(row.get("mid", {}))
        lines.append(
            "| {name} | {lp}/{lc} | {ll} | {li} | {sp}/{sc} | {sl} | {mp}/{mc} | {cand} |".format(
                name=row.get("name"),
                lp=long.get("passing_cell_count"),
                lc=long.get("cell_count"),
                ll=long.get("lost_avoided_loss_count"),
                li=long.get("avg_improvement"),
                sp=short.get("passing_cell_count"),
                sc=short.get("cell_count"),
                sl=short.get("lost_avoided_loss_count"),
                mp=mid.get("passing_cell_count"),
                mc=mid.get("cell_count"),
                cand=row.get("long_horizon_candidate"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _variant_summary(row: Mapping[str, Any], *, long_horizons: tuple[int, ...], short_horizons: tuple[int, ...]) -> dict[str, Any]:
    cells = [dict(cell) for cell in row.get("cells", [])]
    long_cells = [cell for cell in cells if int(cell.get("horizon_bars") or -1) in long_horizons]
    short_cells = [cell for cell in cells if int(cell.get("horizon_bars") or -1) in short_horizons]
    mid_cells = [cell for cell in cells if cell not in long_cells and cell not in short_cells]
    long = _slice_metrics(long_cells)
    short = _slice_metrics(short_cells)
    mid = _slice_metrics(mid_cells)
    long_candidate = (
        long.get("cell_count", 0) > 0
        and long.get("passing_cell_count") == long.get("cell_count")
        and int(long.get("lost_avoided_loss_count") or 0) == 0
        and float(long.get("avg_improvement") or 0.0) > 0.0
    )
    return {
        "name": row.get("name"),
        "matrix_ready": bool(row.get("matrix_ready", False)),
        "long_horizon_candidate": bool(long_candidate),
        "long": long,
        "short": short,
        "mid": mid,
        "overall": {
            "passing_cell_count": row.get("passing_cell_count"),
            "cell_count": row.get("cell_count"),
            "avg_improvement": row.get("avg_improvement"),
            "total_recovered": row.get("total_recovered"),
            "total_lost_avoided": row.get("total_lost_avoided"),
        },
    }


def _slice_metrics(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(cells),
        "passing_cell_count": sum(1 for cell in cells if cell.get("status") == "pass"),
        "failed_cell_count": sum(1 for cell in cells if cell.get("status") != "pass"),
        "improved_cell_count": sum(1 for cell in cells if _gate_metric(cell, "improvement") > 0.0),
        "recovered_missed_win_count": sum(int(_gate_metric(cell, "recovered")) for cell in cells),
        "lost_avoided_loss_count": sum(int(_gate_metric(cell, "lost_avoided")) for cell in cells),
        "avg_improvement": _mean(_gate_metric(cell, "improvement") for cell in cells),
        "failed_cells": [_cell_summary(cell) for cell in cells if cell.get("status") != "pass"],
    }


def _cell_summary(cell: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "horizon_bars": cell.get("horizon_bars"),
        "fee_bps": cell.get("fee_bps"),
        "improvement": _gate_metric(cell, "improvement"),
        "recovered": _gate_metric(cell, "recovered"),
        "lost_avoided": _gate_metric(cell, "lost_avoided"),
        "failure_reasons": list(cell.get("failure_reasons", [])),
    }


def _candidate_from_best(best: Mapping[str, Any] | None, *, require_long_all_pass: bool, require_short_failures_only: bool) -> bool:
    if not best or not bool(best.get("long_horizon_candidate", False)):
        return False
    if require_long_all_pass and best.get("long", {}).get("passing_cell_count") != best.get("long", {}).get("cell_count"):
        return False
    if require_short_failures_only:
        mid = dict(best.get("mid", {}))
        if int(mid.get("failed_cell_count") or 0) > 0:
            return False
    return True


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    long = dict(row.get("long", {}))
    short = dict(row.get("short", {}))
    mid = dict(row.get("mid", {}))
    return {
        "name": row.get("name"),
        "long_passing_cell_count": long.get("passing_cell_count"),
        "long_cell_count": long.get("cell_count"),
        "long_avg_improvement": long.get("avg_improvement"),
        "long_lost_avoided_loss_count": long.get("lost_avoided_loss_count"),
        "short_failed_cell_count": short.get("failed_cell_count"),
        "mid_failed_cell_count": mid.get("failed_cell_count"),
        "long_horizon_candidate": row.get("long_horizon_candidate"),
    }


def _gate_metric(cell: Mapping[str, Any], key: str) -> float:
    gate = dict(cell.get("gate", {}))
    try:
        return float(gate.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _mean(values) -> float | None:
    nums = []
    for value in values:
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


__all__ = ["build_pa_paper_horizon_report", "render_pa_paper_horizon_markdown"]
