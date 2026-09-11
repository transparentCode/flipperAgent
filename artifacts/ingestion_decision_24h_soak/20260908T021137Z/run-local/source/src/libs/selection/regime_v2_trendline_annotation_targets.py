"""Targeted evidence report for RegimeV2 trendline annotations.

This module is intentionally read-only.  It evaluates whether annotation buckets
have enough labeled shadow evidence to justify future experiments, without
changing selection, playbooks, or policy gates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_TARGETS = (
    ("trendline_risk_context", "upper_channel_pressure_watch"),
    ("trendline_confidence_annotation", "breakout_watch"),
    ("trendline_pressure_watch", 1.0),
    ("trendline_breakout_watch_high_quality", 1.0),
    ("trendline_breakout_watch_positive_persistence", 1.0),
    ("trendline_breakout_watch_hull_expansion", 1.0),
    ("trendline_breakout_watch_clean_context", 1.0),
    ("trendline_breakout_watch_confirmed_interaction", 1.0),
    ("trendline_breakout_watch_strict_context", "breakout_watch_candidate"),
    ("trendline_breakout_watch_strict_context", "breakout_watch_strict"),
)


@dataclass(frozen=True)
class AnnotationTargetThresholds:
    """Minimum evidence requirements before a target can be considered mature."""

    min_samples: int = 100
    min_positive_lift_rate: float = 0.50
    min_avg_shadow_lift: float = 0.0


def build_trendline_annotation_target_report(
    records: Iterable[Mapping[str, Any]],
    *,
    targets: Sequence[tuple[str, Any]] | None = None,
    thresholds: AnnotationTargetThresholds | None = None,
    source_path: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Return target-level evidence quality for trendline annotations."""

    rows = [_enrich_strict_breakout_fields(dict(record)) for record in records]
    filtered = _filter_records(rows, asset=asset, timeframe=timeframe)
    labeled = [record for record in filtered if _has_lift(record)]
    target_specs = tuple(targets or _DEFAULT_TARGETS)
    cfg = thresholds or AnnotationTargetThresholds()
    target_rows = [_target_summary(labeled, field, value, cfg) for field, value in target_specs]

    mature = [row for row in target_rows if row["evidence_status"] == "candidate_ready"]
    immature = [row for row in target_rows if row["evidence_status"] != "candidate_ready"]
    return {
        "phase": "phase_tl_h14_annotation_target_report",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(rows),
            "records_after_filter": len(filtered),
            "labeled_count": len(labeled),
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "target_count": len(target_rows),
            "candidate_ready_count": len(mature),
            "needs_more_evidence_count": len(immature),
            "min_samples": cfg.min_samples,
            "min_positive_lift_rate": cfg.min_positive_lift_rate,
            "min_avg_shadow_lift": cfg.min_avg_shadow_lift,
        },
        "targets": target_rows,
        "candidate_ready_targets": mature,
        "needs_more_evidence_targets": immature,
    }


def render_trendline_annotation_target_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for target annotation evidence."""

    summary = dict(report.get("summary", {}))
    targets = list(report.get("targets", []))
    lines = [
        "# RegimeV2 Trendline Annotation Target Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records after filter: {summary.get('records_after_filter', 0)}",
        f"- Labeled rows: {summary.get('labeled_count', 0)}",
        f"- Candidate-ready targets: {summary.get('candidate_ready_count', 0)}",
        f"- Needs more evidence: {summary.get('needs_more_evidence_count', 0)}",
        f"- Thresholds: samples>={summary.get('min_samples')}, positive_rate>={summary.get('min_positive_lift_rate')}, avg_lift>={summary.get('min_avg_shadow_lift')}",
        "",
        "## Targets",
        "",
        "| Field | Value | Count | Avg lift | Positive lift rate | Status | More needed |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    if not targets:
        lines.append("| none | none | 0 | n/a | n/a | none | 0 |")
    for row in targets:
        lines.append(
            "| {field} | {value} | {count} | {lift} | {rate} | {status} | {needed} |".format(
                field=row.get("field"),
                value=row.get("value"),
                count=row.get("count"),
                lift=row.get("avg_shadow_lift"),
                rate=row.get("positive_shadow_lift_rate"),
                status=row.get("evidence_status"),
                needed=row.get("additional_samples_needed"),
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in targets:
        lines.append(f"- {row.get('field')}={row.get('value')}: {row.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def _target_summary(
    records: list[dict[str, Any]],
    field: str,
    value: Any,
    thresholds: AnnotationTargetThresholds,
) -> dict[str, Any]:
    matched = [record for record in records if _matches(record.get(field), value)]
    count = len(matched)
    avg_lift = _mean(record.get("shadow_minus_baseline") for record in matched)
    positive_rate = _positive_rate(record.get("shadow_minus_baseline") for record in matched)
    pass_samples = count >= thresholds.min_samples
    pass_positive = positive_rate is not None and positive_rate >= thresholds.min_positive_lift_rate
    pass_lift = avg_lift is not None and avg_lift >= thresholds.min_avg_shadow_lift
    status = "candidate_ready" if pass_samples and pass_positive and pass_lift else "needs_more_evidence"
    return {
        "field": field,
        "value": value,
        "count": count,
        "additional_samples_needed": max(0, thresholds.min_samples - count),
        "avg_shadow_lift": avg_lift,
        "positive_shadow_lift_rate": positive_rate,
        "pass_min_samples": pass_samples,
        "pass_positive_lift_rate": pass_positive,
        "pass_avg_shadow_lift": pass_lift,
        "evidence_status": status,
        "recommendation": _recommendation(status, count, thresholds, avg_lift, positive_rate),
        "asset_timeframe": _group_count(matched, ("asset", "timeframe")),
        "outcome_label": _count_key(matched, "outcome_label"),
        "shadow_model": _count_key(matched, "shadow_selected_model"),
    }


def _recommendation(
    status: str,
    count: int,
    thresholds: AnnotationTargetThresholds,
    avg_lift: float | None,
    positive_rate: float | None,
) -> str:
    if status == "candidate_ready":
        return "Evidence threshold met for offline soft-policy experiment design; still do not enable live gating automatically."
    reasons: list[str] = []
    if count < thresholds.min_samples:
        reasons.append(f"collect {thresholds.min_samples - count} more labeled rows")
    if positive_rate is None or positive_rate < thresholds.min_positive_lift_rate:
        reasons.append("positive lift rate below threshold")
    if avg_lift is None or avg_lift < thresholds.min_avg_shadow_lift:
        reasons.append("average shadow lift below threshold")
    return "; ".join(reasons) if reasons else "collect more evidence"


def _enrich_strict_breakout_fields(record: dict[str, Any]) -> dict[str, Any]:
    breakout_watch = str(record.get("trendline_confidence_annotation") or "") == "breakout_watch"
    if not breakout_watch:
        record.setdefault("trendline_breakout_watch_high_quality", 0.0)
        record.setdefault("trendline_breakout_watch_positive_persistence", 0.0)
        record.setdefault("trendline_breakout_watch_hull_expansion", 0.0)
        record.setdefault("trendline_breakout_watch_clean_context", 0.0)
        record.setdefault("trendline_breakout_watch_confirmed_interaction", 0.0)
        record.setdefault("trendline_breakout_watch_strict_score", 0.0)
        record.setdefault("trendline_breakout_watch_strict_context", "none")
        return record
    quality = _float(record.get("trendline_mean_normalized_quality"), 0.0) or 0.0
    resistance_quality = _float(record.get("trendline_resistance_quality_score"), 0.0) or 0.0
    persistence_bias = _float(record.get("trendline_ray_persistence_bias"), 0.0) or 0.0
    expansion_rate = _float(record.get("trendline_hull_expansion_rate"), 0.0) or 0.0
    high_quality = quality >= 0.85 and resistance_quality >= 0.85
    positive_persistence = persistence_bias > 0.0
    hull_expansion = expansion_rate > 0.0
    clean_context = not _bool(record.get("trendline_mid_channel_noise")) and not _bool(record.get("trendline_no_trade_warning")) and not _bool(record.get("trendline_low_quality_warning"))
    confirmed_interaction = str(record.get("trendline_interaction") or "") == "STRUCTURAL_BREAKOUT"
    strict_score = float(sum([high_quality, positive_persistence, hull_expansion, clean_context, confirmed_interaction]))
    strict_context = "breakout_watch_broad"
    if strict_score >= 4.0:
        strict_context = "breakout_watch_strict"
    elif strict_score >= 3.0:
        strict_context = "breakout_watch_candidate"
    record.setdefault("trendline_breakout_watch_high_quality", 1.0 if high_quality else 0.0)
    record.setdefault("trendline_breakout_watch_positive_persistence", 1.0 if positive_persistence else 0.0)
    record.setdefault("trendline_breakout_watch_hull_expansion", 1.0 if hull_expansion else 0.0)
    record.setdefault("trendline_breakout_watch_clean_context", 1.0 if clean_context else 0.0)
    record.setdefault("trendline_breakout_watch_confirmed_interaction", 1.0 if confirmed_interaction else 0.0)
    record.setdefault("trendline_breakout_watch_strict_score", strict_score)
    record.setdefault("trendline_breakout_watch_strict_context", strict_context)
    return record


def _filter_records(
    records: list[dict[str, Any]],
    *,
    asset: str | None,
    timeframe: str | None,
) -> list[dict[str, Any]]:
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


def _mean(values: Iterable[Any]) -> float | None:
    nums: list[float] = []
    for value in values:
        parsed = _float(value, None)
        if parsed is not None:
            nums.append(parsed)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = [_float(value, None) for value in values]
    parsed = [value for value in nums if value is not None]
    if not parsed:
        return None
    return sum(1 for value in parsed if value > 0.0) / len(parsed)


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


__all__ = [
    "AnnotationTargetThresholds",
    "build_trendline_annotation_target_report",
    "render_trendline_annotation_target_markdown",
]
