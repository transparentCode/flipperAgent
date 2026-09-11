"""Phase 7S support-aware validation for transition candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence


def build_transition_support_validation_report(
    matrix_payload: Mapping[str, Any],
    *,
    min_total_active: int = 30,
    min_split_active: int = 3,
    min_passed_splits: int = 4,
    min_support_score: float = 0.75,
    max_worst_loss: float = 0.0010,
) -> dict[str, Any]:
    """Score a 7R matrix with explicit support diagnostics."""
    matrix = dict(matrix_payload.get("matrix_report", matrix_payload))
    rows = [dict(row) for row in matrix.get("variants", [])]
    scored = [
        _score_variant(
            row,
            min_total_active=min_total_active,
            min_split_active=min_split_active,
            min_passed_splits=min_passed_splits,
            min_support_score=min_support_score,
            max_worst_loss=max_worst_loss,
        )
        for row in rows
    ]
    scored.sort(
        key=lambda row: (
            bool(row.get("support_ready")),
            float(row.get("support_adjusted_score") or -999.0),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
        ),
        reverse=True,
    )
    ready = [row for row in scored if row.get("support_ready")]
    watch = [row for row in scored if row.get("support_grade") in {"promising_thin", "watchlist"}]
    return {
        "phase": "phase_7s_transition_support_validation",
        "summary": {
            "variant_count": len(scored),
            "support_ready_count": len(ready),
            "watch_count": len(watch),
            "assets": sorted({str(row.get("asset")) for row in scored}),
            "best_variant": _compact(scored[0]) if scored else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "asset_summary": _asset_summary(scored),
            "grade_distribution": _counts(row.get("support_grade") for row in scored),
            "blocker_distribution": _blocker_counts(scored),
            "recommendation": _recommendation(ready, watch),
            "criteria": {
                "min_total_active": min_total_active,
                "min_split_active": min_split_active,
                "min_passed_splits": min_passed_splits,
                "min_support_score": min_support_score,
                "max_worst_loss": max_worst_loss,
            },
        },
        "variants": scored,
        "top_variants": [_compact(row) for row in scored[:20]],
    }


def render_transition_support_validation_markdown(report: Mapping[str, Any]) -> str:
    """Render a Phase 7S Markdown report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7S Transition Support Validation",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Support-ready variants: {summary.get('support_ready_count', 0)}",
        f"- Watch variants: {summary.get('watch_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        "",
        "## Asset summary",
        "",
        "| Asset | Variants | Best grade | Best score | Max active | Best passed | Best avg | Best worst |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for asset, row in dict(summary.get("asset_summary", {})).items():
        lines.append(
            "| {asset} | {variant_count} | {best_grade} | {best_support_adjusted_score} | {max_post_active_count} | {best_passed_split_count} | {best_avg_split_directional_return} | {best_worst_split_directional_return} |".format(
                asset=asset,
                **row,
            )
        )
    lines.extend([
        "",
        f"- Grades: {summary.get('grade_distribution')}",
        f"- Blockers: {summary.get('blocker_distribution')}",
        "",
        "## Top variants",
        "",
        "| Asset | Grade | Score | Active | Min split active | Supported | Passed | Avg | Worst | Blockers |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in report.get("top_variants", []):
        blockers = ",".join(row.get("support_blockers", []))
        lines.append(
            "| {asset} | {support_grade} | {support_adjusted_score} | {post_active_count} | {min_split_active_count} | {supported_split_count}/{split_count} | {passed_split_count}/{split_count} | {avg_split_directional_return} | {worst_split_directional_return} | {blockers} |".format(
                blockers=blockers,
                **row,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _score_variant(
    row: Mapping[str, Any],
    *,
    min_total_active: int,
    min_split_active: int,
    min_passed_splits: int,
    min_support_score: float,
    max_worst_loss: float,
) -> dict[str, Any]:
    splits = [dict(item) for item in row.get("splits", [])]
    split_count = int(row.get("split_count") or len(splits) or 0)
    active_total = int(row.get("post_active_count") or row.get("active_count") or 0)
    passed = int(row.get("passed_split_count") or 0)
    split_counts = [int(split.get("active_count") or 0) for split in splits]
    min_active = min(split_counts) if split_counts else 0
    supported = sum(1 for count in split_counts if count >= int(min_split_active))
    avg_return = _float(row.get("avg_split_directional_return"))
    worst_return = _float(row.get("worst_split_directional_return"))
    pass_rate = _rate(passed, split_count)
    split_support_rate = _rate(supported, split_count)
    total_support_rate = min(1.0, active_total / float(min_total_active)) if min_total_active > 0 else 1.0
    support_score = round((0.45 * split_support_rate) + (0.35 * total_support_rate) + (0.20 * pass_rate), 6)
    downside_score = max(0.0, min(1.0, 1.0 + worst_return / abs(max_worst_loss))) if max_worst_loss > 0 else 0.0
    adjusted = round(max(0.0, avg_return) * 100.0 * support_score * downside_score, 6)
    blockers = []
    if active_total < int(min_total_active):
        blockers.append("total_support_low")
    if supported < split_count:
        blockers.append("split_support_low")
    if passed < int(min_passed_splits):
        blockers.append("passed_splits_low")
    if support_score < float(min_support_score):
        blockers.append("support_score_low")
    if avg_return <= 0.0:
        blockers.append("avg_return_low")
    if worst_return < -abs(max_worst_loss):
        blockers.append("worst_loss_too_negative")
    grade = _grade(blockers, passed, split_count, support_score, avg_return)
    return {
        **dict(row),
        "min_split_active_count": min_active,
        "supported_split_count": supported,
        "split_support_rate": split_support_rate,
        "total_support_rate": total_support_rate,
        "support_score": support_score,
        "support_adjusted_score": adjusted,
        "support_blockers": blockers,
        "support_grade": grade,
        "support_ready": grade == "support_ready",
    }


def _grade(blockers: Sequence[str], passed: int, split_count: int, support_score: float, avg_return: float) -> str:
    if not blockers:
        return "support_ready"
    if passed >= max(1, split_count - 1) and avg_return > 0.0:
        return "promising_thin" if support_score >= 0.60 else "watchlist"
    if passed >= max(1, split_count // 2) and avg_return > 0.0:
        return "watchlist"
    return "blocked"


def _asset_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for asset in sorted({str(row.get("asset")) for row in rows}):
        subset = [row for row in rows if str(row.get("asset")) == asset]
        best = subset[0] if subset else {}
        out[asset] = {
            "variant_count": len(subset),
            "best_grade": best.get("support_grade"),
            "best_support_adjusted_score": best.get("support_adjusted_score"),
            "max_post_active_count": max((int(row.get("post_active_count") or 0) for row in subset), default=0),
            "best_passed_split_count": max((int(row.get("passed_split_count") or 0) for row in subset), default=0),
            "best_avg_split_directional_return": max((_float(row.get("avg_split_directional_return"), -999.0) for row in subset), default=None),
            "best_worst_split_directional_return": max((_float(row.get("worst_split_directional_return"), -999.0) for row in subset), default=None),
        }
    return out


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "support_grade": row.get("support_grade"),
        "support_adjusted_score": row.get("support_adjusted_score"),
        "support_score": row.get("support_score"),
        "post_active_count": row.get("post_active_count"),
        "min_split_active_count": row.get("min_split_active_count"),
        "supported_split_count": row.get("supported_split_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
        "support_blockers": row.get("support_blockers", []),
        "config": row.get("config", {}),
    }


def _recommendation(ready: Sequence[Mapping[str, Any]], watch: Sequence[Mapping[str, Any]]) -> str:
    if ready:
        return "candidate_ready_for_multi_window_robustness"
    if watch:
        return "keep_diagnostic_collect_more_support"
    return "hold_off_transition_support_unstable"


def _blocker_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update(str(value) for value in row.get("support_blockers", []))
    return dict(counter.most_common())


def _counts(values) -> dict[str, int]:
    return dict(Counter(str(value) for value in values).most_common())


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator > 0 else 0.0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_transition_support_validation_report", "render_transition_support_validation_markdown"]
