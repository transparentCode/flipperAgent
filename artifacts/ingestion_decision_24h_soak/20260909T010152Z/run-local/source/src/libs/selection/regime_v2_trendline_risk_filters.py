"""Evidence report for trendline contexts as risk filters.

This module is read-only.  It evaluates whether a trendline context would have
been useful as a warning against bad shadow-selection changes.  It does not
change selection, scoring, playbooks, or policy gates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_FILTERS = (
    ("trendline_mid_channel_noise", 1.0),
    ("trendline_no_trade_warning", 1.0),
    ("trendline_risk_context", "near_support_reversal_context"),
    ("trendline_risk_context", "near_resistance_reversal_context"),
    ("trendline_confidence_annotation", "reversal_watch"),
    ("trendline_pressure_watch", 1.0),
    ("trendline_confidence_annotation", "breakout_watch"),
)


@dataclass(frozen=True)
class RiskFilterThresholds:
    min_changed_samples: int = 25
    min_bad_change_rate: float = 0.55
    max_avg_changed_lift: float = 0.0


def build_trendline_risk_filter_report(
    records: Iterable[Mapping[str, Any]],
    *,
    filters: Sequence[tuple[str, Any]] | None = None,
    thresholds: RiskFilterThresholds | None = None,
    source_path: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    rows = [dict(record) for record in records]
    filtered = _filter_records(rows, asset=asset, timeframe=timeframe)
    labeled = [record for record in filtered if _has_lift(record)]
    changed = [record for record in labeled if _bool(record.get("selection_changed"))]
    specs = tuple(filters or _DEFAULT_FILTERS)
    cfg = thresholds or RiskFilterThresholds()
    filter_rows = [_filter_summary(changed, field, value, cfg) for field, value in specs]
    ready = [row for row in filter_rows if row["risk_filter_status"] == "candidate_ready"]
    weak = [row for row in filter_rows if row["risk_filter_status"] != "candidate_ready"]
    return {
        "phase": "phase_tl_h18_trendline_risk_filter_report",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(rows),
            "records_after_filter": len(filtered),
            "labeled_count": len(labeled),
            "changed_labeled_count": len(changed),
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "filter_count": len(filter_rows),
            "candidate_ready_count": len(ready),
            "needs_more_evidence_count": len(weak),
            "min_changed_samples": cfg.min_changed_samples,
            "min_bad_change_rate": cfg.min_bad_change_rate,
            "max_avg_changed_lift": cfg.max_avg_changed_lift,
        },
        "filters": filter_rows,
        "candidate_ready_filters": ready,
        "needs_more_evidence_filters": weak,
    }


def render_trendline_risk_filter_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    filters = list(report.get("filters", []))
    lines = [
        "# RegimeV2 Trendline Risk Filter Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Labeled rows: {summary.get('labeled_count', 0)}",
        f"- Changed labeled rows: {summary.get('changed_labeled_count', 0)}",
        f"- Candidate-ready filters: {summary.get('candidate_ready_count', 0)}",
        f"- Needs more evidence: {summary.get('needs_more_evidence_count', 0)}",
        f"- Thresholds: changed_samples>={summary.get('min_changed_samples')}, bad_rate>={summary.get('min_bad_change_rate')}, avg_changed_lift<={summary.get('max_avg_changed_lift')}",
        "",
        "## Filters",
        "",
        "| Field | Value | Changed count | Avg changed lift | Bad change rate | Avg loss avoided | Status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    if not filters:
        lines.append("| none | none | 0 | n/a | n/a | n/a | none |")
    for row in filters:
        lines.append(
            "| {field} | {value} | {count} | {avg} | {bad} | {avoided} | {status} |".format(
                field=row.get("field"),
                value=row.get("value"),
                count=row.get("changed_count"),
                avg=row.get("avg_changed_shadow_lift"),
                bad=row.get("bad_change_rate"),
                avoided=row.get("avg_loss_avoided_when_bad"),
                status=row.get("risk_filter_status"),
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in filters:
        lines.append(f"- {row.get('field')}={row.get('value')}: {row.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def _filter_summary(records: list[dict[str, Any]], field: str, value: Any, thresholds: RiskFilterThresholds) -> dict[str, Any]:
    matched = [record for record in records if _matches(record.get(field), value)]
    lifts = [_float(record.get("shadow_minus_baseline"), None) for record in matched]
    parsed = [value for value in lifts if value is not None]
    bad = [value for value in parsed if value < 0.0]
    good = [value for value in parsed if value > 0.0]
    count = len(parsed)
    avg_lift = _mean(parsed)
    bad_rate = len(bad) / count if count else None
    avg_loss_avoided = _mean([-value for value in bad])
    avg_good_missed = _mean(good)
    pass_samples = count >= thresholds.min_changed_samples
    pass_bad_rate = bad_rate is not None and bad_rate >= thresholds.min_bad_change_rate
    pass_avg_lift = avg_lift is not None and avg_lift <= thresholds.max_avg_changed_lift
    status = "candidate_ready" if pass_samples and pass_bad_rate and pass_avg_lift else "needs_more_evidence"
    return {
        "field": field,
        "value": value,
        "changed_count": count,
        "additional_changed_samples_needed": max(0, thresholds.min_changed_samples - count),
        "avg_changed_shadow_lift": avg_lift,
        "bad_change_rate": bad_rate,
        "bad_change_count": len(bad),
        "good_change_count": len(good),
        "avg_loss_avoided_when_bad": avg_loss_avoided,
        "avg_good_lift_missed": avg_good_missed,
        "pass_min_changed_samples": pass_samples,
        "pass_bad_change_rate": pass_bad_rate,
        "pass_avg_changed_lift": pass_avg_lift,
        "risk_filter_status": status,
        "recommendation": _recommendation(status, count, thresholds, avg_lift, bad_rate),
        "asset_timeframe": _group_count(matched, ("asset", "timeframe")),
        "outcome_label": _count_key(matched, "outcome_label"),
        "shadow_model": _count_key(matched, "shadow_selected_model"),
    }


def _recommendation(status: str, count: int, thresholds: RiskFilterThresholds, avg_lift: float | None, bad_rate: float | None) -> str:
    if status == "candidate_ready":
        return "Candidate risk filter for offline suppression experiment design only; do not enable live gating automatically."
    reasons: list[str] = []
    if count < thresholds.min_changed_samples:
        reasons.append(f"collect {thresholds.min_changed_samples - count} more changed rows")
    if bad_rate is None or bad_rate < thresholds.min_bad_change_rate:
        reasons.append("bad-change rate below threshold")
    if avg_lift is None or avg_lift > thresholds.max_avg_changed_lift:
        reasons.append("average changed shadow lift not negative enough")
    return "; ".join(reasons) if reasons else "collect more evidence"


def _filter_records(records: list[dict[str, Any]], *, asset: str | None, timeframe: str | None) -> list[dict[str, Any]]:
    asset_filter = asset.upper() if asset else None
    out: list[dict[str, Any]] = []
    for record in records:
        if asset_filter and str(record.get("asset", "")).upper() != asset_filter:
            continue
        if timeframe and str(record.get("timeframe", "")) != timeframe:
            continue
        out.append(record)
    return out


def _matches(observed: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        parsed = _float(observed, None)
        return parsed == expected
    return str(observed) == str(expected)


def _has_lift(record: Mapping[str, Any]) -> bool:
    return _float(record.get("shadow_minus_baseline"), None) is not None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[Any]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


__all__ = [
    "RiskFilterThresholds",
    "build_trendline_risk_filter_report",
    "render_trendline_risk_filter_markdown",
]
