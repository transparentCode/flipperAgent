"""Phase 7U policy-safe transition micro-regime separation.

7T showed that phase-level tags explain a useful part of transition behavior.
7U tests the policy-safe separation directly over a transition matrix: compare
breakout_setup-only, compressed_wait-only, and all/mixed variants without using
outcome-derived failure labels as live rules.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence


def build_transition_micro_separation_report(
    matrix_payload: Mapping[str, Any],
    *,
    min_total_active: int = 30,
    min_split_active: int = 3,
    min_passed_splits: int = 4,
    max_worst_loss: float = 0.0010,
) -> dict[str, Any]:
    """Summarize policy-safe phase separation over transition variants."""
    matrix = dict(matrix_payload.get("matrix_report", matrix_payload))
    variants = [dict(row) for row in matrix.get("variants", [])]
    rows = [_score_variant(row, min_total_active, min_split_active, min_passed_splits, max_worst_loss) for row in variants]
    groups = _group_rows(rows)
    group_rows = [_group_summary(key, value) for key, value in groups.items()]
    group_rows.sort(key=lambda row: (_rank_group(row), row.get("avg_split_directional_return") or -999.0), reverse=True)
    return {
        "phase": "phase_7u_transition_micro_separation",
        "summary": {
            "variant_count": len(rows),
            "assets": sorted({str(row.get("asset")) for row in rows}),
            "group_count": len(group_rows),
            "best_group": group_rows[0] if group_rows else None,
            "separation_decision": _decision(group_rows),
            "criteria": {
                "min_total_active": int(min_total_active),
                "min_split_active": int(min_split_active),
                "min_passed_splits": int(min_passed_splits),
                "max_worst_loss": float(max_worst_loss),
            },
        },
        "groups": group_rows,
        "variants": rows,
    }


def render_transition_micro_separation_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7U."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7U Transition Micro-Regime Separation",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Groups: {summary.get('group_count', 0)}",
        f"- Decision: {summary.get('separation_decision')}",
        f"- Best group: {summary.get('best_group')}",
        "",
        "## Groups",
        "",
        "| Group | Variants | Assets | Ready | Promising | Max active | Best passed | Avg split return | Worst split return | Recommendation |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("groups", []):
        lines.append(
            "| {group} | {variant_count} | {assets} | {ready_count} | {promising_count} | {max_post_active_count} | {best_passed_split_count} | {avg_split_directional_return} | {worst_split_directional_return} | {recommendation} |".format(
                group=row.get("phase_group"),
                assets=",".join(row.get("assets", [])),
                variant_count=row.get("variant_count"),
                ready_count=row.get("ready_count"),
                promising_count=row.get("promising_count"),
                max_post_active_count=row.get("max_post_active_count"),
                best_passed_split_count=row.get("best_passed_split_count"),
                avg_split_directional_return=row.get("avg_split_directional_return"),
                worst_split_directional_return=row.get("worst_split_directional_return"),
                recommendation=row.get("recommendation"),
            )
        )
    lines.extend([
        "",
        "## Asset by group",
        "",
        "| Group | Asset | Variants | Best grade | Max active | Best passed | Best avg | Best worst |",
        "|---|---|---:|---|---:|---:|---:|---:|",
    ])
    for group in report.get("groups", []):
        for asset, row in dict(group.get("asset_summary", {})).items():
            lines.append(
                "| {group} | {asset} | {variant_count} | {best_grade} | {max_post_active_count} | {best_passed_split_count} | {best_avg_split_directional_return} | {best_worst_split_directional_return} |".format(
                    group=group.get("phase_group"),
                    asset=asset,
                    **row,
                )
            )
    lines.append("")
    return "\n".join(lines)


def _score_variant(
    row: Mapping[str, Any],
    min_total_active: int,
    min_split_active: int,
    min_passed_splits: int,
    max_worst_loss: float,
) -> dict[str, Any]:
    split_count = int(row.get("split_count") or 0)
    post_active = int(row.get("post_active_count") or row.get("active_count") or 0)
    passed = int(row.get("passed_split_count") or 0)
    splits = [dict(split) for split in row.get("splits", [])]
    split_active_counts = [int(split.get("active_count") or 0) for split in splits]
    supported = sum(1 for count in split_active_counts if count >= int(min_split_active))
    avg_return = _float(row.get("avg_split_directional_return"))
    worst_return = _float(row.get("worst_split_directional_return"))
    blockers = []
    if post_active < int(min_total_active):
        blockers.append("total_support_low")
    if supported < split_count:
        blockers.append("split_support_low")
    if passed < int(min_passed_splits):
        blockers.append("passed_splits_low")
    if avg_return <= 0.0:
        blockers.append("avg_return_low")
    if worst_return < -abs(float(max_worst_loss)):
        blockers.append("worst_loss_too_negative")
    grade = _grade(blockers, passed, split_count, avg_return)
    return {
        **dict(row),
        "phase_group": _phase_group(dict(row.get("config", {})).get("allowed_market_phases")),
        "supported_split_count": supported,
        "min_split_active_count": min(split_active_counts) if split_active_counts else 0,
        "separation_blockers": blockers,
        "separation_grade": grade,
    }


def _group_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("phase_group"))].append(row)
    return groups


def _group_summary(group: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    best = sorted(rows, key=lambda row: (int(row.get("passed_split_count") or 0), _float(row.get("avg_split_directional_return")), _float(row.get("worst_split_directional_return"))), reverse=True)[0] if rows else {}
    avg_values = [_float(row.get("avg_split_directional_return")) for row in rows if row.get("avg_split_directional_return") is not None]
    worst_values = [_float(row.get("worst_split_directional_return")) for row in rows if row.get("worst_split_directional_return") is not None]
    grades = Counter(str(row.get("separation_grade")) for row in rows)
    return {
        "phase_group": group,
        "variant_count": len(rows),
        "assets": sorted({str(row.get("asset")) for row in rows}),
        "ready_count": int(grades.get("ready", 0)),
        "promising_count": int(grades.get("promising", 0)),
        "watch_count": int(grades.get("watch", 0)),
        "grade_distribution": dict(grades.most_common()),
        "max_post_active_count": max((int(row.get("post_active_count") or 0) for row in rows), default=0),
        "best_passed_split_count": max((int(row.get("passed_split_count") or 0) for row in rows), default=0),
        "avg_split_directional_return": sum(avg_values) / len(avg_values) if avg_values else None,
        "best_avg_split_directional_return": max(avg_values) if avg_values else None,
        "worst_split_directional_return": min(worst_values) if worst_values else None,
        "best_worst_split_directional_return": max(worst_values) if worst_values else None,
        "best_variant": _compact(best),
        "asset_summary": _asset_summary(rows),
        "recommendation": _group_recommendation(group, rows, grades),
    }


def _asset_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for asset in sorted({str(row.get("asset")) for row in rows}):
        subset = [row for row in rows if str(row.get("asset")) == asset]
        best = sorted(subset, key=lambda row: (int(row.get("passed_split_count") or 0), _float(row.get("avg_split_directional_return"))), reverse=True)[0] if subset else {}
        out[asset] = {
            "variant_count": len(subset),
            "best_grade": best.get("separation_grade"),
            "max_post_active_count": max((int(row.get("post_active_count") or 0) for row in subset), default=0),
            "best_passed_split_count": max((int(row.get("passed_split_count") or 0) for row in subset), default=0),
            "best_avg_split_directional_return": max((_float(row.get("avg_split_directional_return"), -999.0) for row in subset), default=None),
            "best_worst_split_directional_return": max((_float(row.get("worst_split_directional_return"), -999.0) for row in subset), default=None),
        }
    return out


def _phase_group(value: Any) -> str:
    if not value:
        return "all"
    values = sorted(str(item) for item in value)
    if values == ["breakout_setup"]:
        return "breakout_setup"
    if values == ["compressed_wait"]:
        return "compressed_wait"
    return "mixed"


def _grade(blockers: Sequence[str], passed: int, split_count: int, avg_return: float) -> str:
    if not blockers:
        return "ready"
    if passed >= max(1, split_count - 1) and avg_return > 0.0:
        return "promising"
    if passed >= max(1, split_count // 2) and avg_return > 0.0:
        return "watch"
    return "blocked"


def _group_recommendation(group: str, rows: Sequence[Mapping[str, Any]], grades: Counter[str]) -> str:
    if grades.get("ready", 0):
        return "candidate_ready_for_robustness"
    if group == "breakout_setup" and (grades.get("promising", 0) or grades.get("watch", 0)):
        return "keep_as_research_candidate"
    if group == "compressed_wait":
        return "separate_as_observation_only"
    return "diagnostic_only"


def _decision(groups: Sequence[Mapping[str, Any]]) -> str:
    by_group = {str(row.get("phase_group")): row for row in groups}
    breakout = by_group.get("breakout_setup", {})
    compressed = by_group.get("compressed_wait", {})
    if _float(breakout.get("avg_split_directional_return")) > _float(compressed.get("avg_split_directional_return")):
        return "separate_breakout_setup_from_compressed_wait"
    return "no_phase_separation_edge"


def _rank_group(row: Mapping[str, Any]) -> int:
    group = str(row.get("phase_group"))
    if group == "breakout_setup":
        return 3
    if group == "all":
        return 2
    if group == "compressed_wait":
        return 1
    return 0


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "phase_group": row.get("phase_group"),
        "grade": row.get("separation_grade"),
        "post_active_count": row.get("post_active_count"),
        "supported_split_count": row.get("supported_split_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
        "blockers": row.get("separation_blockers", []),
        "config": row.get("config", {}),
    }


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_transition_micro_separation_report", "render_transition_micro_separation_markdown"]
