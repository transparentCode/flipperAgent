"""Coverage report for PA paper candidate-ranking snapshots."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def build_pa_paper_snapshot_report(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize snapshot coverage and next-best availability."""
    rows = [dict(record) for record in records]
    with_baseline = [row for row in rows if _non_empty_list(row.get("baseline_ranked_candidates"))]
    with_paper = [row for row in rows if _non_empty_list(row.get("paper_ranked_candidates"))]
    with_both = [row for row in rows if _non_empty_list(row.get("baseline_ranked_candidates")) and _non_empty_list(row.get("paper_ranked_candidates"))]
    active = [row for row in rows if bool(row.get("paper_active", False))]
    changed = [row for row in active if bool(row.get("selection_changed", False))]
    changed_with_alt = [row for row in changed if _non_empty_list(row.get("paper_ranked_candidates"))]
    return {
        "phase": "phase_6r_pa_paper_snapshot_coverage",
        "summary": {
            "total_records": len(rows),
            "baseline_snapshot_count": len(with_baseline),
            "paper_snapshot_count": len(with_paper),
            "both_snapshot_count": len(with_both),
            "snapshot_coverage_rate": _rate(len(with_both), len(rows)),
            "paper_active_count": len(active),
            "selection_changed_count": len(changed),
            "changed_with_alternate_count": len(changed_with_alt),
            "changed_alternate_coverage_rate": _rate(len(changed_with_alt), len(changed)),
            "avg_baseline_snapshot_size": _mean(len(row.get("baseline_ranked_candidates", [])) for row in with_baseline),
            "avg_paper_snapshot_size": _mean(len(row.get("paper_ranked_candidates", [])) for row in with_paper),
            "alternate_action_ready": len(changed) > 0 and len(changed_with_alt) == len(changed),
        },
        "distributions": {
            "baseline_top_model": _top_model_distribution(rows, "baseline_ranked_candidates"),
            "paper_top_model": _top_model_distribution(rows, "paper_ranked_candidates"),
            "changed_paper_top_model": _top_model_distribution(changed, "paper_ranked_candidates"),
            "snapshot_schema_version": dict(sorted(Counter(str(row.get("candidate_snapshot_schema_version")) for row in rows).items())),
        },
        "changed_alternates": _changed_alternate_rows(changed),
    }


def render_pa_paper_snapshot_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for snapshot coverage."""
    summary = dict(report.get("summary", {}))
    distributions = dict(report.get("distributions", {}))
    lines = [
        "# RegimeV2 Phase 6R PA Paper Snapshot Coverage",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- Both snapshot count: {summary.get('both_snapshot_count', 0)}",
        f"- Snapshot coverage rate: {summary.get('snapshot_coverage_rate')}",
        f"- Paper active: {summary.get('paper_active_count', 0)}",
        f"- Selection changed: {summary.get('selection_changed_count', 0)}",
        f"- Changed with alternate: {summary.get('changed_with_alternate_count', 0)}",
        f"- Changed alternate coverage rate: {summary.get('changed_alternate_coverage_rate')}",
        f"- Alternate action ready: {summary.get('alternate_action_ready')}",
        f"- Avg baseline snapshot size: {summary.get('avg_baseline_snapshot_size')}",
        f"- Avg paper snapshot size: {summary.get('avg_paper_snapshot_size')}",
        "",
        "## Distributions",
        "",
        f"- Baseline top model: {distributions.get('baseline_top_model', {})}",
        f"- Paper top model: {distributions.get('paper_top_model', {})}",
        f"- Changed paper top model: {distributions.get('changed_paper_top_model', {})}",
        f"- Snapshot schema version: {distributions.get('snapshot_schema_version', {})}",
        "",
        "## Changed Alternates",
        "",
        "| Baseline | Paper top | Count | Avg baseline score | Avg paper score |",
        "|---|---|---:|---:|---:|",
    ]
    for row in report.get("changed_alternates", []):
        lines.append(
            "| {baseline} | {paper} | {count} | {baseline_score} | {paper_score} |".format(
                baseline=row.get("baseline_selected_model"),
                paper=row.get("paper_top_model"),
                count=row.get("count"),
                baseline_score=row.get("avg_baseline_selection_score"),
                paper_score=row.get("avg_paper_selection_score"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _changed_alternate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        baseline_model = str(row.get("baseline_selected_model"))
        paper_top = _top_snapshot(row.get("paper_ranked_candidates"))
        paper_model = str(paper_top.get("model_name")) if paper_top else "None"
        groups.setdefault((baseline_model, paper_model), []).append(row)
    out = []
    for (baseline_model, paper_model), items in sorted(groups.items()):
        out.append(
            {
                "baseline_selected_model": baseline_model,
                "paper_top_model": paper_model,
                "count": len(items),
                "avg_baseline_selection_score": _mean(row.get("baseline_selection_score") for row in items),
                "avg_paper_selection_score": _mean((_top_snapshot(row.get("paper_ranked_candidates")) or {}).get("selection_score") for row in items),
            }
        )
    return out


def _top_model_distribution(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counter = Counter()
    for row in rows:
        top = _top_snapshot(row.get(key))
        counter[str(top.get("model_name")) if top else "None"] += 1
    return dict(sorted(counter.items()))


def _top_snapshot(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    return first if isinstance(first, dict) else None


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _mean(values: Iterable[Any]) -> float | None:
    nums = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = ["build_pa_paper_snapshot_report", "render_pa_paper_snapshot_markdown"]
