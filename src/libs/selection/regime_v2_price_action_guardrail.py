"""Offline PriceAction guardrail candidate discovery for RegimeV2.

This module turns the Phase 6E finding into candidate guardrail rules. It is
analysis-only: no live SelectionLayer behaviour is changed here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

_DEFAULT_MIN_SUPPORT = 10
_DEFAULT_MIN_BAD_RATE = 0.55
_DEFAULT_MIN_AVG_LIFT = 0.0


def build_price_action_guardrail_report(
    records: Iterable[Mapping[str, Any]],
    *,
    min_support: int = _DEFAULT_MIN_SUPPORT,
    min_bad_rate: float = _DEFAULT_MIN_BAD_RATE,
    min_avg_lift: float = _DEFAULT_MIN_AVG_LIFT,
) -> dict[str, Any]:
    """Build candidate PriceAction guardrail rules from labeled outcomes."""
    rows = [dict(record) for record in records]
    price_action = [record for record in rows if _is_price_action_subset_removal(record)]
    candidates = _candidate_rows(
        price_action,
        min_support=int(min_support),
        min_bad_rate=float(min_bad_rate),
        min_avg_lift=float(min_avg_lift),
    )
    return {
        "phase": "phase_6f_price_action_guardrail_candidate",
        "summary": {
            "total_records": len(rows),
            "price_action_subset_removal_count": len(price_action),
            "price_action_subset_removal_rate": _rate(len(price_action), len(rows)),
            "min_support": int(min_support),
            "min_bad_rate": float(min_bad_rate),
            "min_avg_lift": float(min_avg_lift),
            "candidate_rule_count": len(candidates),
            "overall_price_action": _metrics(price_action),
        },
        "candidate_rules": candidates,
        "diagnostics": {
            "asset_timeframe": _group_metrics(price_action, _asset_timeframe_key),
            "direction": _group_metrics(price_action, _direction_key),
            "regime_side": _group_metrics(price_action, _regime_side_key),
            "confidence_bucket": _group_metrics(price_action, lambda record: _bucket(_float(record.get("confidence"), None), [0.3, 0.5, 0.7], "confidence")),
            "uncertainty_bucket": _group_metrics(price_action, lambda record: _bucket(_float(record.get("uncertainty"), None), [0.25, 0.5, 0.75], "uncertainty")),
            "trend_score_bucket": _group_metrics(price_action, lambda record: _bucket(_float(record.get("trend_score"), None), [0.0, 0.05, 0.10, 0.18, 0.24], "trend")),
            "breakout_score_bucket": _group_metrics(price_action, lambda record: _bucket(_float(record.get("breakout_score"), None), [0.0, 0.02, 0.05, 0.10, 0.18], "breakout")),
            "mean_reversion_score_bucket": _group_metrics(price_action, lambda record: _bucket(_float(record.get("mean_reversion_score"), None), [0.0, 0.02, 0.05, 0.10, 0.18], "mean_reversion")),
            "active_playbooks": _group_metrics(price_action, _active_playbooks_key),
        },
    }


def render_price_action_guardrail_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for PriceAction guardrail candidates."""
    summary = dict(report.get("summary", {}))
    overall = dict(summary.get("overall_price_action", {}))
    candidates = list(report.get("candidate_rules", []))
    lines = [
        "# RegimeV2 Phase 6F PriceAction Guardrail Candidate",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- PriceAction subset removals: {summary.get('price_action_subset_removal_count', 0)} ({summary.get('price_action_subset_removal_rate')})",
        f"- Candidate rules: {summary.get('candidate_rule_count', 0)}",
        f"- Min support: {summary.get('min_support')}",
        f"- Min bad rate: {summary.get('min_bad_rate')}",
        f"- Overall avg lift: {overall.get('avg_shadow_minus_baseline')}",
        f"- Overall bad rate: {overall.get('bad_rate')}",
        f"- Overall positive lift rate: {overall.get('positive_shadow_lift_rate')}",
        "",
        "## Candidate Rules",
        "",
        "| Rank | Condition | Count | Bad rate | Avg lift | Positive rate | Labels |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    if candidates:
        for index, row in enumerate(candidates, start=1):
            lines.append(
                "| {rank} | {condition} | {count} | {bad_rate} | {lift} | {positive} | {labels} |".format(
                    rank=index,
                    condition=f"{row.get('condition')}={row.get('value')}",
                    count=row.get("count"),
                    bad_rate=row.get("bad_rate"),
                    lift=row.get("avg_shadow_minus_baseline"),
                    positive=row.get("positive_shadow_lift_rate"),
                    labels=row.get("outcome_labels"),
                )
            )
    else:
        lines.append("| 0 | none | 0 | n/a | n/a | n/a | n/a |")
    lines.append("")
    return "\n".join(lines)


def _candidate_rows(
    records: list[dict[str, Any]],
    *,
    min_support: int,
    min_bad_rate: float,
    min_avg_lift: float,
) -> list[dict[str, Any]]:
    candidate_groups: list[tuple[str, dict[str, dict[str, Any]]]] = [
        ("asset_timeframe", _group_metrics(records, _asset_timeframe_key)),
        ("direction", _group_metrics(records, _direction_key)),
        ("regime_side", _group_metrics(records, _regime_side_key)),
        ("confidence_bucket", _group_metrics(records, lambda record: _bucket(_float(record.get("confidence"), None), [0.3, 0.5, 0.7], "confidence"))),
        ("uncertainty_bucket", _group_metrics(records, lambda record: _bucket(_float(record.get("uncertainty"), None), [0.25, 0.5, 0.75], "uncertainty"))),
        ("trend_score_bucket", _group_metrics(records, lambda record: _bucket(_float(record.get("trend_score"), None), [0.0, 0.05, 0.10, 0.18, 0.24], "trend"))),
        ("breakout_score_bucket", _group_metrics(records, lambda record: _bucket(_float(record.get("breakout_score"), None), [0.0, 0.02, 0.05, 0.10, 0.18], "breakout"))),
        ("mean_reversion_score_bucket", _group_metrics(records, lambda record: _bucket(_float(record.get("mean_reversion_score"), None), [0.0, 0.02, 0.05, 0.10, 0.18], "mean_reversion"))),
        ("active_playbooks", _group_metrics(records, _active_playbooks_key)),
    ]
    rows: list[dict[str, Any]] = []
    for condition, groups in candidate_groups:
        for value, metrics in groups.items():
            if int(metrics.get("count") or 0) < min_support:
                continue
            if _float(metrics.get("bad_rate"), 0.0) < min_bad_rate:
                continue
            if _float(metrics.get("avg_shadow_minus_baseline"), 0.0) <= min_avg_lift:
                continue
            row = dict(metrics)
            row["condition"] = condition
            row["value"] = value
            rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            float(row.get("bad_rate") or 0.0),
            float(row.get("avg_shadow_minus_baseline") or 0.0),
            int(row.get("count") or 0),
        ),
        reverse=True,
    )


def _group_metrics(records: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(key_fn(record)), []).append(record)
    return {key: _metrics(items) for key, items in sorted(grouped.items())}


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    bad = [record for record in records if _is_bad_price_action(record)]
    return {
        "count": len(records),
        "bad_count": len(bad),
        "bad_rate": _rate(len(bad), len(records)),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in records),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


def _is_bad_price_action(record: Mapping[str, Any]) -> bool:
    return _float(record.get("baseline_net_return"), 0.0) < 0.0


def _is_price_action_subset_removal(record: Mapping[str, Any]) -> bool:
    if str(record.get("baseline_selected_model") or "") != "PriceAction":
        return False
    if record.get("shadow_selected_model") is not None:
        return False
    if not bool(record.get("selection_changed", False)):
        return False
    if not bool(record.get("shadow_subset_only", False)):
        return False
    if bool(record.get("include_non_target_models", True)):
        return False
    target_models = {str(model) for model in (record.get("target_models") or [])}
    return "PriceAction" not in target_models


def _asset_timeframe_key(record: Mapping[str, Any]) -> str:
    return f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"


def _direction_key(record: Mapping[str, Any]) -> str:
    return f"direction_{record.get('baseline_selected_direction') or 'none'}"


def _regime_side_key(record: Mapping[str, Any]) -> str:
    return f"regime_side_{record.get('regime_side') if record.get('regime_side') is not None else 'none'}"


def _active_playbooks_key(record: Mapping[str, Any]) -> str:
    playbooks = record.get("active_playbooks") or []
    if isinstance(playbooks, list) and playbooks:
        return "+".join(sorted(str(playbook) for playbook in playbooks))
    return "none"


def _bucket(value: float | None, thresholds: list[float], name: str) -> str:
    if value is None:
        return f"{name}:missing"
    if value == 0.0:
        return f"{name}:zero"
    last = "-inf"
    for threshold in thresholds:
        if value <= threshold:
            return f"{name}:({last},{threshold}]"
        last = str(threshold)
    return f"{name}:>{thresholds[-1]}"


def _mean(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    if not nums:
        return None
    return sum(1 for value in nums if value > 0.0) / len(nums)


def _numbers(values: Iterable[Any]) -> list[float]:
    nums: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return nums


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


__all__ = [
    "build_price_action_guardrail_report",
    "render_price_action_guardrail_report_markdown",
]
