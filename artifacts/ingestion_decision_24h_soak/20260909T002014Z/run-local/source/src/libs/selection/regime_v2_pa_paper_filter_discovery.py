"""Context-filter discovery for PA paper failure pockets.

Phase 6T searches for simple rules that keep suppress-to-flat where it helped
while avoiding the localized missed-win pocket found in Phase 6S. It is an
offline diagnostic only.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_FIELDS = (
    "baseline_selection_score",
    "baseline_edge_score",
    "baseline_conviction",
)


def build_pa_paper_filter_discovery_report(
    labeled_records: Iterable[Mapping[str, Any]],
    *,
    failure_window: Mapping[str, Any],
    min_support: int = 5,
    min_rejected_bad_rate: float = 0.60,
    max_kept_bad_rate: float = 0.35,
    fields: Sequence[str] = _DEFAULT_FIELDS,
) -> dict[str, Any]:
    """Discover simple filters that reject the PA suppression failure pocket."""
    rows = _active_changed_rows(labeled_records)
    rows = _with_derived_features(rows, failure_window=failure_window)
    baseline = _segment_metrics(rows, name="all_active_changed")
    failure_rows = [row for row in rows if bool(row.get("in_failure_window", False))]
    failure_metrics = _segment_metrics(failure_rows, name="failure_window")
    candidates = _candidate_filters(
        rows,
        fields=tuple(fields),
        min_support=int(min_support),
        min_rejected_bad_rate=float(min_rejected_bad_rate),
        max_kept_bad_rate=float(max_kept_bad_rate),
    )
    return {
        "phase": "phase_6t_pa_paper_context_filter_discovery",
        "summary": {
            "active_changed_count": len(rows),
            "failure_window_count": len(failure_rows),
            "candidate_filter_count": len(candidates),
            "min_support": int(min_support),
            "min_rejected_bad_rate": float(min_rejected_bad_rate),
            "max_kept_bad_rate": float(max_kept_bad_rate),
            "best_filter": candidates[0] if candidates else None,
            "recommendation": "candidate_filter_found" if candidates else "no_simple_filter_found",
        },
        "baseline": baseline,
        "failure_window": failure_metrics,
        "candidate_filters": candidates,
    }


def render_pa_paper_filter_discovery_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for context-filter discovery."""
    summary = dict(report.get("summary", {}))
    baseline = dict(report.get("baseline", {}))
    failure = dict(report.get("failure_window", {}))
    lines = [
        "# RegimeV2 Phase 6T PA Paper Context Filter Discovery",
        "",
        "## Summary",
        "",
        f"- Active changed rows: {summary.get('active_changed_count', 0)}",
        f"- Failure window rows: {summary.get('failure_window_count', 0)}",
        f"- Candidate filters: {summary.get('candidate_filter_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best filter: {summary.get('best_filter')}",
        "",
        "## Baseline vs Failure Window",
        "",
        f"- All rows avg lift: {baseline.get('avg_paper_minus_baseline')}",
        f"- All rows bad rate: {baseline.get('bad_rate')}",
        f"- Failure avg lift: {failure.get('avg_paper_minus_baseline')}",
        f"- Failure bad rate: {failure.get('bad_rate')}",
        "",
        "## Candidate Filters",
        "",
        "| Rule | Kept | Rejected | Rejected bad rate | Kept bad rate | Lift improvement | Failure coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("candidate_filters", []):
        lines.append(
            "| {rule} | {kept} | {rejected} | {rej_bad} | {kept_bad} | {improvement} | {coverage} |".format(
                rule=row.get("rule"),
                kept=row.get("kept_count"),
                rejected=row.get("rejected_count"),
                rej_bad=row.get("rejected_bad_rate"),
                kept_bad=row.get("kept_bad_rate"),
                improvement=row.get("kept_avg_lift_minus_all_avg_lift"),
                coverage=row.get("failure_window_coverage_rate"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _candidate_filters(
    rows: list[dict[str, Any]],
    *,
    fields: Sequence[str],
    min_support: int,
    min_rejected_bad_rate: float,
    max_kept_bad_rate: float,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for field in fields:
        values = sorted(_number(row.get(field)) for row in rows if _number(row.get(field)) is not None)
        if not values:
            continue
        thresholds = _thresholds(values)
        for threshold in thresholds:
            candidates.append(
                _evaluate_filter(
                    rows,
                    rule=f"{field} <= {threshold}",
                    reject_fn=lambda row, f=field, t=threshold: (_number(row.get(f)) is not None and _number(row.get(f)) <= t),
                )
            )
            candidates.append(
                _evaluate_filter(
                    rows,
                    rule=f"{field} > {threshold}",
                    reject_fn=lambda row, f=field, t=threshold: (_number(row.get(f)) is not None and _number(row.get(f)) > t),
                )
            )
    candidates.append(
        _evaluate_filter(
            rows,
            rule="recent_window_position >= 0.75",
            reject_fn=lambda row: _number(row.get("recent_window_position")) is not None and _number(row.get("recent_window_position")) >= 0.75,
        )
    )
    candidates.append(
        _evaluate_filter(
            rows,
            rule="timestamp >= failure_window_start",
            reject_fn=lambda row: bool(row.get("in_failure_window", False)),
        )
    )
    out = [
        row
        for row in candidates
        if row.get("rejected_count", 0) >= min_support
        and row.get("kept_count", 0) >= min_support
        and _float(row.get("rejected_bad_rate"), 0.0) >= min_rejected_bad_rate
        and _float(row.get("kept_bad_rate"), 1.0) <= max_kept_bad_rate
        and _float(row.get("kept_avg_lift_minus_all_avg_lift"), 0.0) > 0.0
    ]
    out.sort(
        key=lambda row: (
            _float(row.get("kept_avg_lift_minus_all_avg_lift"), 0.0),
            _float(row.get("failure_window_coverage_rate"), 0.0),
            _float(row.get("rejected_bad_rate"), 0.0),
        ),
        reverse=True,
    )
    return out


def _evaluate_filter(rows: list[dict[str, Any]], *, rule: str, reject_fn) -> dict[str, Any]:
    rejected = [row for row in rows if reject_fn(row)]
    kept = [row for row in rows if row not in rejected]
    all_metrics = _segment_metrics(rows, name="all")
    kept_metrics = _segment_metrics(kept, name="kept")
    rejected_metrics = _segment_metrics(rejected, name="rejected")
    failure_rows = [row for row in rows if bool(row.get("in_failure_window", False))]
    rejected_failure = [row for row in rejected if bool(row.get("in_failure_window", False))]
    return {
        "rule": rule,
        "kept_count": len(kept),
        "rejected_count": len(rejected),
        "kept_avg_lift": kept_metrics.get("avg_paper_minus_baseline"),
        "rejected_avg_lift": rejected_metrics.get("avg_paper_minus_baseline"),
        "all_avg_lift": all_metrics.get("avg_paper_minus_baseline"),
        "kept_avg_lift_minus_all_avg_lift": _delta(kept_metrics.get("avg_paper_minus_baseline"), all_metrics.get("avg_paper_minus_baseline")),
        "kept_bad_rate": kept_metrics.get("bad_rate"),
        "rejected_bad_rate": rejected_metrics.get("bad_rate"),
        "kept_outcome_labels": kept_metrics.get("outcome_labels"),
        "rejected_outcome_labels": rejected_metrics.get("outcome_labels"),
        "failure_window_coverage_rate": _rate(len(rejected_failure), len(failure_rows)),
        "rejected_failure_count": len(rejected_failure),
    }


def _active_changed_rows(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(record)
        for record in records
        if record.get("outcome_label") != "unlabeled"
        and bool(record.get("paper_active", False))
        and bool(record.get("selection_changed", False))
    ]


def _with_derived_features(rows: list[dict[str, Any]], *, failure_window: Mapping[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: _float(row.get("timestamp"), 0.0))
    start_ts = _float(failure_window.get("start_timestamp"), None)
    end_ts = _float(failure_window.get("end_timestamp"), None)
    max_index = max(len(ordered) - 1, 1)
    out = []
    for idx, row in enumerate(ordered):
        item = dict(row)
        ts = _float(item.get("timestamp"), None)
        item["recent_window_position"] = float(idx) / float(max_index)
        item["in_failure_window"] = (
            ts is not None
            and (start_ts is None or ts >= start_ts)
            and (end_ts is None or ts <= end_ts)
        )
        out.append(item)
    return out


def _segment_metrics(rows: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    labels = Counter(str(row.get("outcome_label")) for row in rows)
    bad = int(labels.get("missed_win", 0))
    return {
        "name": name,
        "count": len(rows),
        "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in rows),
        "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in rows),
        "bad_count": bad,
        "bad_rate": _rate(bad, len(rows)),
        "outcome_labels": dict(sorted(labels.items())),
        "avg_baseline_selection_score": _mean(row.get("baseline_selection_score") for row in rows),
        "avg_baseline_edge_score": _mean(row.get("baseline_edge_score") for row in rows),
        "avg_baseline_conviction": _mean(row.get("baseline_conviction") for row in rows),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in rows),
    }


def _thresholds(values: list[float]) -> list[float]:
    if not values:
        return []
    percentiles = (0.10, 0.20, 0.25, 0.33, 0.50, 0.67, 0.75, 0.80, 0.90)
    out = []
    for pct in percentiles:
        idx = min(max(int(round((len(values) - 1) * pct)), 0), len(values) - 1)
        value = float(values[idx])
        if value not in out:
            out.append(value)
    return out


def _mean(values: Iterable[Any]) -> float | None:
    nums = [_number(value) for value in values]
    nums = [value for value in nums if value is not None]
    return sum(nums) / len(nums) if nums else None


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = [_number(value) for value in values]
    nums = [value for value in nums if value is not None]
    return sum(1 for value in nums if value > 0.0) / len(nums) if nums else None


def _delta(a: Any, b: Any) -> float | None:
    av = _number(a)
    bv = _number(b)
    return None if av is None or bv is None else av - bv


def _number(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any, default: float | None) -> float | None:
    parsed = _number(value)
    return default if parsed is None else parsed


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = ["build_pa_paper_filter_discovery_report", "render_pa_paper_filter_discovery_markdown"]
