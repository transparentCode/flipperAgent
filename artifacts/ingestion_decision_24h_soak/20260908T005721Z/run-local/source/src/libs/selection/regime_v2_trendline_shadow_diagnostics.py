"""Trendline diagnostics for RegimeV2 shadow-decision logs.

This report is read-only: it never changes selection behavior.  It explains
where shadow-selection changes occurred relative to trendline market structure,
quality, compression, and temporal persistence fields that may be present in
RegimeV2 shadow JSONL rows.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping

_CONTEXT_FLAGS = (
    "trendline_near_support",
    "trendline_near_resistance",
    "trendline_mid_channel_noise",
    "trendline_above_channel",
    "trendline_below_channel",
    "trendline_inside_channel",
)
_QUALITY_BUCKETS = (
    ("missing", None, None),
    ("low", 0.0, 0.4),
    ("medium", 0.4, 0.7),
    ("high", 0.7, 1.0000001),
)


def build_trendline_shadow_diagnostics(
    records: Iterable[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Build a report over RegimeV2 shadow rows that contain trendline context."""

    raw = [dict(record) for record in records]
    filtered = _filter_records(raw, asset=asset, timeframe=timeframe)
    context_rows = [record for record in filtered if _has_trendline_context(record)]
    changed = [record for record in filtered if _bool(record.get("selection_changed"))]
    context_changed = [record for record in context_rows if _bool(record.get("selection_changed"))]
    gate_active_context = [record for record in context_rows if _bool(record.get("gate_active"))]
    labeled_context = [record for record in context_rows if _has_outcome(record)]
    changed_labeled_context = [record for record in labeled_context if _bool(record.get("selection_changed"))]

    return {
        "phase": "phase_tl_h8_trendline_shadow_diagnostics",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(raw),
            "records_after_filter": len(filtered),
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "trendline_context_count": len(context_rows),
            "trendline_context_rate": _rate(len(context_rows), len(filtered)),
            "selection_changed_count": len(changed),
            "trendline_context_changed_count": len(context_changed),
            "trendline_context_changed_rate": _rate(len(context_changed), len(context_rows)),
            "gate_active_trendline_context_count": len(gate_active_context),
            "gate_active_trendline_context_rate": _rate(len(gate_active_context), len(context_rows)),
            "avg_trendline_mean_quality": _mean(record.get("trendline_mean_normalized_quality") for record in context_rows),
            "avg_trendline_support_quality": _mean(record.get("trendline_support_quality_score") for record in context_rows),
            "avg_trendline_resistance_quality": _mean(record.get("trendline_resistance_quality_score") for record in context_rows),
            "avg_trendline_hull_width_atr": _mean(record.get("trendline_hull_width_atr") for record in context_rows),
            "avg_trendline_hull_convergence_rate": _mean(record.get("trendline_hull_convergence_rate") for record in context_rows),
            "avg_trendline_hull_expansion_rate": _mean(record.get("trendline_hull_expansion_rate") for record in context_rows),
            "avg_trendline_ray_persistence_bias": _mean(record.get("trendline_ray_persistence_bias") for record in context_rows),
            "changed_avg_trendline_mean_quality": _mean(record.get("trendline_mean_normalized_quality") for record in context_changed),
            "changed_avg_trendline_hull_width_atr": _mean(record.get("trendline_hull_width_atr") for record in context_changed),
            "changed_avg_edge_delta": _mean(record.get("edge_delta") for record in context_changed),
            "outcome_labeled_context_count": len(labeled_context),
            "outcome_labeled_context_rate": _rate(len(labeled_context), len(context_rows)),
            "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in labeled_context),
            "changed_avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in changed_labeled_context),
            "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in labeled_context),
            "changed_positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in changed_labeled_context),
        },
        "distributions": {
            "asset_timeframe": _group_count(context_rows, ("asset", "timeframe")),
            "trendline_interaction": _count_key(context_rows, "trendline_interaction"),
            "trendline_market_position_state": _count_key(context_rows, "trendline_market_position_state"),
            "trendline_structure_state": _count_key(context_rows, "trendline_structure_state"),
            "trendline_risk_context": _count_key(context_rows, "trendline_risk_context"),
            "trendline_confidence_annotation": _count_key(context_rows, "trendline_confidence_annotation"),
            "trendline_annotation_reason": _count_key(context_rows, "trendline_annotation_reason"),
            "quality_bucket": _quality_bucket_counts(context_rows),
            "changed_quality_bucket": _quality_bucket_counts(context_changed),
            "selection_changed_by_market_position": _changed_by_key(context_rows, "trendline_market_position_state"),
            "selection_changed_by_interaction": _changed_by_key(context_rows, "trendline_interaction"),
            "selection_changed_by_quality_bucket": _changed_by_quality_bucket(context_rows),
            "outcome_label": _count_key(labeled_context, "outcome_label"),
            "outcome_label_by_market_position": _outcome_by_key(labeled_context, "trendline_market_position_state"),
            "outcome_label_by_quality_bucket": _outcome_by_quality_bucket(labeled_context),
        },
        "market_position_groups": _context_group_summary(context_rows, "trendline_market_position_state"),
        "interaction_groups": _context_group_summary(context_rows, "trendline_interaction"),
        "risk_context_groups": _context_group_summary(context_rows, "trendline_risk_context"),
        "confidence_annotation_groups": _context_group_summary(context_rows, "trendline_confidence_annotation"),
        "quality_buckets": _quality_bucket_summary(context_rows),
        "context_flags": {flag: _flag_summary(context_rows, flag) for flag in _CONTEXT_FLAGS},
        "model_context": _model_context_summary(context_rows),
        "candidate_questions": _candidate_question_summary(context_rows),
    }


def render_trendline_shadow_diagnostics_markdown(report: Mapping[str, Any]) -> str:
    """Render trendline shadow diagnostics as compact Markdown."""

    summary = dict(report.get("summary", {}))
    market_groups = list(report.get("market_position_groups", []))
    risk_context_groups = list(report.get("risk_context_groups", []))
    quality_buckets = list(report.get("quality_buckets", []))
    context_flags = dict(report.get("context_flags", {}))
    model_context = list(report.get("model_context", []))
    questions = dict(report.get("candidate_questions", {}))

    lines = [
        "# RegimeV2 Trendline Shadow Diagnostics",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records after filter: {summary.get('records_after_filter', 0)}",
        f"- Trendline context rows: {summary.get('trendline_context_count', 0)} ({summary.get('trendline_context_rate')})",
        f"- Context changed rows: {summary.get('trendline_context_changed_count', 0)} ({summary.get('trendline_context_changed_rate')})",
        f"- Avg trendline quality: {summary.get('avg_trendline_mean_quality')}",
        f"- Changed avg trendline quality: {summary.get('changed_avg_trendline_mean_quality')}",
        f"- Avg hull width ATR: {summary.get('avg_trendline_hull_width_atr')}",
        f"- Avg persistence bias: {summary.get('avg_trendline_ray_persistence_bias')}",
        f"- Outcome-labeled context rows: {summary.get('outcome_labeled_context_count', 0)} ({summary.get('outcome_labeled_context_rate')})",
        f"- Avg shadow lift: {summary.get('avg_shadow_minus_baseline')}",
        f"- Changed avg shadow lift: {summary.get('changed_avg_shadow_minus_baseline')}",
        f"- Changed positive lift rate: {summary.get('changed_positive_shadow_lift_rate')}",
        "",
        "## Market Position Groups",
        "",
        "| State | Count | Changed | Changed rate | Avg edge delta | Avg quality | Avg hull width ATR | Avg shadow lift | Positive lift rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    if market_groups:
        for row in market_groups:
            lines.append(
                "| {name} | {count} | {changed} | {rate} | {edge} | {quality} | {width} | {lift} | {positive_rate} |".format(
                    name=row.get("value"),
                    count=row.get("count"),
                    changed=row.get("selection_changed_count"),
                    rate=row.get("selection_changed_rate"),
                    edge=row.get("avg_edge_delta"),
                    quality=row.get("avg_trendline_mean_quality"),
                    width=row.get("avg_trendline_hull_width_atr"),
                    lift=row.get("avg_shadow_minus_baseline"),
                    positive_rate=row.get("positive_shadow_lift_rate"),
                )
            )
    else:
        lines.append("| none | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a |")

    lines.extend([
        "",
        "## Risk Context Annotations",
        "",
        "| Risk context | Count | Changed | Changed rate | Avg shadow lift | Positive lift rate |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    if risk_context_groups:
        for row in risk_context_groups:
            lines.append(
                "| {name} | {count} | {changed} | {rate} | {lift} | {positive_rate} |".format(
                    name=row.get("value"),
                    count=row.get("count"),
                    changed=row.get("selection_changed_count"),
                    rate=row.get("selection_changed_rate"),
                    lift=row.get("avg_shadow_minus_baseline"),
                    positive_rate=row.get("positive_shadow_lift_rate"),
                )
            )
    else:
        lines.append("| none | 0 | 0 | n/a | n/a | n/a |")

    lines.extend([
        "",
        "## Quality Buckets",
        "",
        "| Bucket | Count | Changed | Changed rate | Avg edge delta | Avg hull width ATR | Avg shadow lift | Positive lift rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    if quality_buckets:
        for row in quality_buckets:
            lines.append(
                "| {bucket} | {count} | {changed} | {rate} | {edge} | {width} | {lift} | {positive_rate} |".format(
                    bucket=row.get("bucket"),
                    count=row.get("count"),
                    changed=row.get("selection_changed_count"),
                    rate=row.get("selection_changed_rate"),
                    edge=row.get("avg_edge_delta"),
                    width=row.get("avg_trendline_hull_width_atr"),
                    lift=row.get("avg_shadow_minus_baseline"),
                    positive_rate=row.get("positive_shadow_lift_rate"),
                )
            )
    else:
        lines.append("| none | 0 | 0 | n/a | n/a | n/a | n/a | n/a |")

    lines.extend([
        "",
        "## Context Flags",
        "",
        "| Flag | Count | Changed | Changed rate | Avg edge delta |",
        "|---|---:|---:|---:|---:|",
    ])
    for flag in _CONTEXT_FLAGS:
        row = dict(context_flags.get(flag, {}))
        lines.append(
            "| {flag} | {count} | {changed} | {rate} | {edge} |".format(
                flag=flag,
                count=row.get("count", 0),
                changed=row.get("selection_changed_count", 0),
                rate=row.get("selection_changed_rate"),
                edge=row.get("avg_edge_delta"),
            )
        )

    lines.extend([
        "",
        "## Model Context",
        "",
        "| Shadow model | Count | Changed | Avg quality | Avg edge delta |",
        "|---|---:|---:|---:|---:|",
    ])
    if model_context:
        for row in model_context:
            lines.append(
                "| {model} | {count} | {changed} | {quality} | {edge} |".format(
                    model=row.get("shadow_selected_model"),
                    count=row.get("count"),
                    changed=row.get("selection_changed_count"),
                    quality=row.get("avg_trendline_mean_quality"),
                    edge=row.get("avg_edge_delta"),
                )
            )
    else:
        lines.append("| none | 0 | 0 | n/a | n/a |")

    lines.extend([
        "",
        "## Diagnostic Questions",
        "",
        f"- Changed near support/resistance: {questions.get('changed_near_support_or_resistance_count')} ({questions.get('changed_near_support_or_resistance_rate')})",
        f"- Changed during mid-channel noise: {questions.get('changed_mid_channel_noise_count')} ({questions.get('changed_mid_channel_noise_rate')})",
        f"- Breakout shadow picks above channel: {questions.get('breakout_shadow_above_channel_count')} ({questions.get('breakout_shadow_above_channel_rate')})",
        f"- Breakout shadow picks under pressure only: {questions.get('breakout_shadow_pressure_only_count')} ({questions.get('breakout_shadow_pressure_only_rate')})",
        f"- High-quality changed rows: {questions.get('high_quality_changed_count')} ({questions.get('high_quality_changed_rate')})",
        f"- Mid-channel noise avg shadow lift: {questions.get('mid_channel_noise_avg_shadow_lift')}",
        f"- Upper-pressure avg shadow lift: {questions.get('upper_channel_pressure_avg_shadow_lift')}",
        f"- Near S/R avg shadow lift: {questions.get('near_support_or_resistance_avg_shadow_lift')}",
        "",
    ])
    return "\n".join(lines)


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


def _has_trendline_context(record: Mapping[str, Any]) -> bool:
    context = record.get("trendline_context")
    if isinstance(context, Mapping) and context:
        return True
    return any(str(key).startswith("trendline_") and record.get(key) is not None for key in record.keys())


def _context_group_summary(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "none")].append(record)
    rows = [_summarize_group(value, items, label_key="value") for value, items in grouped.items()]
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["value"])))


def _quality_bucket_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_quality_bucket(record)].append(record)
    rows = [_summarize_group(bucket, items, label_key="bucket") for bucket, items in grouped.items()]
    order = {name: idx for idx, (name, _, _) in enumerate(_QUALITY_BUCKETS)}
    return sorted(rows, key=lambda row: order.get(str(row["bucket"]), 999))


def _summarize_group(name: str, records: list[dict[str, Any]], *, label_key: str) -> dict[str, Any]:
    changed = [record for record in records if _bool(record.get("selection_changed"))]
    return {
        label_key: name,
        "count": len(records),
        "selection_changed_count": len(changed),
        "selection_changed_rate": _rate(len(changed), len(records)),
        "avg_edge_delta": _mean(record.get("edge_delta") for record in records),
        "changed_avg_edge_delta": _mean(record.get("edge_delta") for record in changed),
        "avg_trendline_mean_quality": _mean(record.get("trendline_mean_normalized_quality") for record in records),
        "avg_trendline_hull_width_atr": _mean(record.get("trendline_hull_width_atr") for record in records),
        "avg_trendline_ray_persistence_bias": _mean(record.get("trendline_ray_persistence_bias") for record in records),
        **_outcome_summary(records),
    }


def _flag_summary(records: list[dict[str, Any]], flag: str) -> dict[str, Any]:
    matched = [record for record in records if _bool(record.get(flag))]
    changed = [record for record in matched if _bool(record.get("selection_changed"))]
    return {
        "count": len(matched),
        "selection_changed_count": len(changed),
        "selection_changed_rate": _rate(len(changed), len(matched)),
        "avg_edge_delta": _mean(record.get("edge_delta") for record in matched),
        "avg_trendline_mean_quality": _mean(record.get("trendline_mean_normalized_quality") for record in matched),
        **_outcome_summary(matched),
    }


def _model_context_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("shadow_selected_model") or "none")].append(record)
    rows = []
    for model, items in grouped.items():
        changed = [record for record in items if _bool(record.get("selection_changed"))]
        rows.append(
            {
                "shadow_selected_model": model,
                "count": len(items),
                "selection_changed_count": len(changed),
                "selection_changed_rate": _rate(len(changed), len(items)),
                "avg_trendline_mean_quality": _mean(record.get("trendline_mean_normalized_quality") for record in items),
                "avg_edge_delta": _mean(record.get("edge_delta") for record in items),
                "market_position_state": _count_key(items, "trendline_market_position_state"),
                **_outcome_summary(items),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["shadow_selected_model"])))


def _candidate_question_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    changed = [record for record in records if _bool(record.get("selection_changed"))]
    changed_near = [record for record in changed if _bool(record.get("trendline_near_support")) or _bool(record.get("trendline_near_resistance"))]
    changed_mid = [record for record in changed if _bool(record.get("trendline_mid_channel_noise"))]
    high_quality_changed = [record for record in changed if _float(record.get("trendline_mean_normalized_quality"), 0.0) >= 0.7]
    breakout_shadow = [record for record in records if str(record.get("shadow_selected_model") or "") == "SqueezeBreakout"]
    breakout_above = [record for record in breakout_shadow if _bool(record.get("trendline_above_channel"))]
    breakout_pressure = [
        record
        for record in breakout_shadow
        if not _bool(record.get("trendline_above_channel"))
        and str(record.get("trendline_market_position_state") or "") == "upper_channel_pressure"
    ]
    mid_noise = [record for record in records if _bool(record.get("trendline_mid_channel_noise"))]
    upper_pressure = [record for record in records if str(record.get("trendline_market_position_state") or "") == "upper_channel_pressure"]
    near_sr = [record for record in records if _bool(record.get("trendline_near_support")) or _bool(record.get("trendline_near_resistance"))]
    return {
        "changed_near_support_or_resistance_count": len(changed_near),
        "changed_near_support_or_resistance_rate": _rate(len(changed_near), len(changed)),
        "changed_mid_channel_noise_count": len(changed_mid),
        "changed_mid_channel_noise_rate": _rate(len(changed_mid), len(changed)),
        "high_quality_changed_count": len(high_quality_changed),
        "high_quality_changed_rate": _rate(len(high_quality_changed), len(changed)),
        "breakout_shadow_count": len(breakout_shadow),
        "breakout_shadow_above_channel_count": len(breakout_above),
        "breakout_shadow_above_channel_rate": _rate(len(breakout_above), len(breakout_shadow)),
        "breakout_shadow_pressure_only_count": len(breakout_pressure),
        "breakout_shadow_pressure_only_rate": _rate(len(breakout_pressure), len(breakout_shadow)),
        "mid_channel_noise_avg_shadow_lift": _mean(record.get("shadow_minus_baseline") for record in mid_noise),
        "mid_channel_noise_positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in mid_noise),
        "upper_channel_pressure_avg_shadow_lift": _mean(record.get("shadow_minus_baseline") for record in upper_pressure),
        "upper_channel_pressure_positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in upper_pressure),
        "near_support_or_resistance_avg_shadow_lift": _mean(record.get("shadow_minus_baseline") for record in near_sr),
        "near_support_or_resistance_positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in near_sr),
    }


def _outcome_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    labeled = [record for record in records if _has_outcome(record)]
    return {
        "outcome_labeled_count": len(labeled),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in labeled),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in labeled),
        "outcome_label": _count_key(labeled, "outcome_label"),
    }


def _quality_bucket_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(_quality_bucket(record) for record in records)
    return dict(sorted(counts.items()))


def _changed_by_quality_bucket(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_quality_bucket(record)].append(record)
    return {bucket: _changed_counter(items) for bucket, items in sorted(grouped.items())}


def _changed_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "none")].append(record)
    return {value: _changed_counter(items) for value, items in sorted(grouped.items())}


def _outcome_by_key(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get(key) or "none")].append(record)
    return {value: _count_key(items, "outcome_label") for value, items in sorted(grouped.items())}


def _outcome_by_quality_bucket(records: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_quality_bucket(record)].append(record)
    return {bucket: _count_key(items, "outcome_label") for bucket, items in sorted(grouped.items())}


def _changed_counter(records: list[dict[str, Any]]) -> dict[str, Any]:
    changed = sum(1 for record in records if _bool(record.get("selection_changed")))
    return {"count": len(records), "selection_changed_count": changed, "selection_changed_rate": _rate(changed, len(records))}


def _quality_bucket(record: Mapping[str, Any]) -> str:
    value = _float(record.get("trendline_mean_normalized_quality"), None)
    if value is None:
        return "missing"
    for name, low, high in _QUALITY_BUCKETS:
        if low is None or high is None:
            continue
        if low <= value < high:
            return name
    return "missing"


def _has_outcome(record: Mapping[str, Any]) -> bool:
    return _float(record.get("shadow_minus_baseline"), None) is not None


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = [_float(value, None) for value in values]
    parsed = [value for value in nums if value is not None]
    if not parsed:
        return None
    return sum(1 for value in parsed if value > 0.0) / len(parsed)


def _mean(values: Iterable[Any]) -> float | None:
    nums: list[float] = []
    for value in values:
        parsed = _float(value, None)
        if parsed is not None:
            nums.append(parsed)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


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


__all__ = [
    "build_trendline_shadow_diagnostics",
    "render_trendline_shadow_diagnostics_markdown",
]
