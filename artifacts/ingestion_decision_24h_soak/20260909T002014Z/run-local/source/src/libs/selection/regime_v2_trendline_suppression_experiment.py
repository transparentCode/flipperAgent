"""Offline suppression experiment for trendline risk-warning contexts.

The experiment is read-only.  It replays labeled shadow rows and simulates a
fallback-to-baseline outcome when a candidate trendline warning is active on a
changed shadow pick.  It does not change selection, scoring, playbooks, policy,
or execution.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_FILTERS = (
    ("trendline_mid_channel_noise", 1.0),
    ("trendline_no_trade_warning", 1.0),
    ("trendline_confidence_annotation", "reversal_watch"),
)


@dataclass(frozen=True)
class SuppressionThresholds:
    min_suppressed_samples: int = 25
    min_loss_saved_rate: float = 0.55
    min_net_lift_delta: float = 0.0


def build_trendline_suppression_experiment(
    records: Iterable[Mapping[str, Any]],
    *,
    filters: Sequence[tuple[str, Any]] | None = None,
    thresholds: SuppressionThresholds | None = None,
    source_path: str | None = None,
    asset: str | None = None,
    timeframe: str | None = None,
    include_combined: bool = True,
) -> dict[str, Any]:
    """Return offline suppression results for trendline warning contexts."""

    rows = [dict(record) for record in records]
    filtered = _filter_records(rows, asset=asset, timeframe=timeframe)
    labeled = [record for record in filtered if _has_lift(record)]
    changed = [record for record in labeled if _bool(record.get("selection_changed"))]
    cfg = thresholds or SuppressionThresholds()
    specs = tuple(filters or _DEFAULT_FILTERS)
    baseline = _portfolio_summary(labeled, changed)
    experiments = [_experiment_summary(labeled, changed, spec, cfg) for spec in specs]
    if include_combined and specs:
        experiments.append(_combined_experiment_summary(labeled, changed, specs, cfg))
    ready = [row for row in experiments if row["experiment_status"] == "candidate_ready"]
    weak = [row for row in experiments if row["experiment_status"] != "candidate_ready"]
    return {
        "phase": "phase_tl_h19_trendline_suppression_experiment",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(rows),
            "records_after_filter": len(filtered),
            "labeled_count": len(labeled),
            "changed_labeled_count": len(changed),
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "experiment_count": len(experiments),
            "candidate_ready_count": len(ready),
            "needs_more_evidence_count": len(weak),
            "min_suppressed_samples": cfg.min_suppressed_samples,
            "min_loss_saved_rate": cfg.min_loss_saved_rate,
            "min_net_lift_delta": cfg.min_net_lift_delta,
            **baseline,
        },
        "experiments": experiments,
        "candidate_ready_experiments": ready,
        "needs_more_evidence_experiments": weak,
    }


def render_trendline_suppression_experiment_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    experiments = list(report.get("experiments", []))
    lines = [
        "# RegimeV2 Trendline Suppression Experiment",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Labeled rows: {summary.get('labeled_count', 0)}",
        f"- Changed rows: {summary.get('changed_labeled_count', 0)}",
        f"- Original avg lift: {summary.get('original_avg_shadow_lift')}",
        f"- Changed avg lift: {summary.get('changed_avg_shadow_lift')}",
        f"- Candidate-ready experiments: {summary.get('candidate_ready_count', 0)}",
        f"- Needs more evidence: {summary.get('needs_more_evidence_count', 0)}",
        "",
        "## Experiments",
        "",
        "| Filter | Suppressed | Loss saved rate | Avg suppressed lift | Net lift delta | Original avg | Suppressed avg | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    if not experiments:
        lines.append("| none | 0 | n/a | n/a | n/a | n/a | n/a | none |")
    for row in experiments:
        lines.append(
            "| {name} | {count} | {rate} | {avg} | {delta} | {orig} | {supp} | {status} |".format(
                name=row.get("name"),
                count=row.get("suppressed_count"),
                rate=row.get("loss_saved_rate"),
                avg=row.get("avg_suppressed_original_lift"),
                delta=row.get("net_lift_delta_all_rows"),
                orig=row.get("original_avg_shadow_lift_all_rows"),
                supp=row.get("suppressed_avg_shadow_lift_all_rows"),
                status=row.get("experiment_status"),
            )
        )
    lines.extend(["", "## Notes", ""])
    for row in experiments:
        lines.append(f"- {row.get('name')}: {row.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def _portfolio_summary(labeled: list[dict[str, Any]], changed: list[dict[str, Any]]) -> dict[str, Any]:
    all_lifts = [_float(record.get("shadow_minus_baseline"), None) for record in labeled]
    changed_lifts = [_float(record.get("shadow_minus_baseline"), None) for record in changed]
    all_parsed = [value for value in all_lifts if value is not None]
    changed_parsed = [value for value in changed_lifts if value is not None]
    return {
        "original_total_shadow_lift": sum(all_parsed),
        "original_avg_shadow_lift": _mean(all_parsed),
        "changed_total_shadow_lift": sum(changed_parsed),
        "changed_avg_shadow_lift": _mean(changed_parsed),
        "changed_bad_count": sum(1 for value in changed_parsed if value < 0.0),
        "changed_good_count": sum(1 for value in changed_parsed if value > 0.0),
    }


def _experiment_summary(
    labeled: list[dict[str, Any]],
    changed: list[dict[str, Any]],
    spec: tuple[str, Any],
    thresholds: SuppressionThresholds,
) -> dict[str, Any]:
    field, value = spec
    matched = [record for record in changed if _matches(record.get(field), value)]
    return _suppression_summary(
        labeled,
        changed,
        matched,
        name=f"{field}={value}",
        field=field,
        value=value,
        thresholds=thresholds,
    )


def _combined_experiment_summary(
    labeled: list[dict[str, Any]],
    changed: list[dict[str, Any]],
    specs: Sequence[tuple[str, Any]],
    thresholds: SuppressionThresholds,
) -> dict[str, Any]:
    matched = [record for record in changed if any(_matches(record.get(field), value) for field, value in specs)]
    row = _suppression_summary(
        labeled,
        changed,
        matched,
        name="combined_any_candidate_warning",
        field="combined_any",
        value="candidate_warning",
        thresholds=thresholds,
    )
    row["components"] = [f"{field}={value}" for field, value in specs]
    return row


def _suppression_summary(
    labeled: list[dict[str, Any]],
    changed: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    *,
    name: str,
    field: str,
    value: Any,
    thresholds: SuppressionThresholds,
) -> dict[str, Any]:
    all_lifts = [_float(record.get("shadow_minus_baseline"), 0.0) or 0.0 for record in labeled]
    matched_lifts = [_float(record.get("shadow_minus_baseline"), None) for record in matched]
    parsed = [value for value in matched_lifts if value is not None]
    original_total = sum(all_lifts)
    suppressed_total = original_total - sum(parsed)
    total_rows = max(len(all_lifts), 1)
    bad = [value for value in parsed if value < 0.0]
    good = [value for value in parsed if value > 0.0]
    suppressed_count = len(parsed)
    loss_saved_rate = len(bad) / suppressed_count if suppressed_count else None
    net_lift_delta = (suppressed_total - original_total) / total_rows
    pass_samples = suppressed_count >= thresholds.min_suppressed_samples
    pass_loss_saved = loss_saved_rate is not None and loss_saved_rate >= thresholds.min_loss_saved_rate
    pass_net_delta = net_lift_delta >= thresholds.min_net_lift_delta
    status = "candidate_ready" if pass_samples and pass_loss_saved and pass_net_delta else "needs_more_evidence"
    return {
        "name": name,
        "field": field,
        "value": value,
        "suppressed_count": suppressed_count,
        "suppressed_rate_over_changed": suppressed_count / max(len(changed), 1),
        "loss_saved_count": len(bad),
        "missed_good_count": len(good),
        "flat_count": suppressed_count - len(bad) - len(good),
        "loss_saved_rate": loss_saved_rate,
        "loss_saved_total": sum(-value for value in bad),
        "good_lift_missed_total": sum(good),
        "avg_loss_saved_when_bad": _mean([-value for value in bad]),
        "avg_good_lift_missed": _mean(good),
        "avg_suppressed_original_lift": _mean(parsed),
        "original_avg_shadow_lift_all_rows": original_total / total_rows,
        "suppressed_avg_shadow_lift_all_rows": suppressed_total / total_rows,
        "net_lift_delta_all_rows": net_lift_delta,
        "pass_min_suppressed_samples": pass_samples,
        "pass_loss_saved_rate": pass_loss_saved,
        "pass_net_lift_delta": pass_net_delta,
        "experiment_status": status,
        "recommendation": _recommendation(status, suppressed_count, thresholds, loss_saved_rate, net_lift_delta),
        "asset_timeframe": _group_count(matched, ("asset", "timeframe")),
        "outcome_label": _count_key(matched, "outcome_label"),
        "shadow_model": _count_key(matched, "shadow_selected_model"),
    }


def _recommendation(
    status: str,
    count: int,
    thresholds: SuppressionThresholds,
    loss_saved_rate: float | None,
    net_lift_delta: float,
) -> str:
    if status == "candidate_ready":
        return "Candidate offline suppression experiment passed; design a guarded shadow-only policy simulation next, not live gating."
    reasons: list[str] = []
    if count < thresholds.min_suppressed_samples:
        reasons.append(f"collect {thresholds.min_suppressed_samples - count} more suppressed rows")
    if loss_saved_rate is None or loss_saved_rate < thresholds.min_loss_saved_rate:
        reasons.append("loss-saved rate below threshold")
    if net_lift_delta < thresholds.min_net_lift_delta:
        reasons.append("net lift delta below threshold")
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
    "SuppressionThresholds",
    "build_trendline_suppression_experiment",
    "render_trendline_suppression_experiment_markdown",
]
