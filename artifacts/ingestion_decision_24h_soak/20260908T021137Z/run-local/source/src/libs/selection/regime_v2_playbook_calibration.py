"""Playbook threshold calibration for RegimeV2 shadow outcomes.

This module is intentionally offline-only. It does not change live selection.
It decomposes whether playbook activation is limited by score floors or by
policy allow flags, then attaches realized shadow-vs-baseline outcome lift to
those buckets.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_PLAYBOOKS = ("trend", "breakout", "mean_reversion")
_PLAYBOOK_FIELDS = {
    "trend": ("allow_trend_following", "trend_score"),
    "breakout": ("allow_breakout", "breakout_score"),
    "mean_reversion": ("allow_mean_reversion", "mean_reversion_score"),
}
_DEFAULT_FLOORS = (0.10, 0.14, 0.18, 0.20, 0.22, 0.24)


def build_regime_v2_playbook_calibration(
    records: Iterable[Mapping[str, Any]],
    *,
    floors: Sequence[float] = _DEFAULT_FLOORS,
) -> dict[str, Any]:
    """Build threshold/policy decomposition from labeled shadow outcomes."""
    rows = [dict(record) for record in records]
    labeled = [record for record in rows if record.get("outcome_label") != "unlabeled"]
    return {
        "phase": "phase_6d_playbook_calibration",
        "summary": {
            "total_records": len(rows),
            "labeled_count": len(labeled),
            "unlabeled_count": len(rows) - len(labeled),
            "floors": [float(floor) for floor in floors],
            "best_policy_gated_cell": _best_cell(_all_cells(labeled, floors), segment="policy_gated"),
            "best_score_only_cell": _best_cell(_all_cells(labeled, floors), segment="score_only"),
            "best_allow_blocked_cell": _best_cell(_all_cells(labeled, floors), segment="allow_blocked_score_pass"),
        },
        "playbooks": {
            playbook: _playbook_report(labeled, playbook=playbook, floors=floors)
            for playbook in _PLAYBOOKS
        },
        "price_action": _price_action_report(labeled),
        "model_pairs": _model_pair_report(labeled),
    }


def render_regime_v2_playbook_calibration_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown calibration report."""
    summary = dict(report.get("summary", {}))
    playbooks = dict(report.get("playbooks", {}))
    price_action = dict(report.get("price_action", {}))
    lines = [
        "# RegimeV2 Phase 6D Playbook Calibration",
        "",
        "## Summary",
        "",
        f"- Records: {summary.get('total_records', 0)}",
        f"- Labeled: {summary.get('labeled_count', 0)}",
        f"- Unlabeled: {summary.get('unlabeled_count', 0)}",
        f"- Floors: {summary.get('floors', [])}",
        f"- Best policy-gated cell: {summary.get('best_policy_gated_cell')}",
        f"- Best score-only cell: {summary.get('best_score_only_cell')}",
        f"- Best allow-blocked score-pass cell: {summary.get('best_allow_blocked_cell')}",
        "",
        "## Playbook Floor Sweep",
        "",
        "| Playbook | Floor | Policy count | Policy lift | Score-only count | Score-only lift | Allow-blocked count | Allow-blocked lift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for playbook in _PLAYBOOKS:
        rows = list(dict(playbooks.get(playbook, {})).get("floor_sweep", []))
        for row in rows:
            lines.append(
                "| {playbook} | {floor} | {policy_count} | {policy_lift} | {score_count} | {score_lift} | {blocked_count} | {blocked_lift} |".format(
                    playbook=playbook,
                    floor=row.get("floor"),
                    policy_count=row.get("policy_gated", {}).get("count"),
                    policy_lift=row.get("policy_gated", {}).get("avg_shadow_minus_baseline"),
                    score_count=row.get("score_only", {}).get("count"),
                    score_lift=row.get("score_only", {}).get("avg_shadow_minus_baseline"),
                    blocked_count=row.get("allow_blocked_score_pass", {}).get("count"),
                    blocked_lift=row.get("allow_blocked_score_pass", {}).get("avg_shadow_minus_baseline"),
                )
            )
    lines.extend(
        [
            "",
            "## PriceAction Subset Removal",
            "",
            f"- Count: {price_action.get('count')}",
            f"- Avg shadow-minus-baseline: {price_action.get('avg_shadow_minus_baseline')}",
            f"- Positive lift rate: {price_action.get('positive_shadow_lift_rate')}",
            f"- Labels: {price_action.get('outcome_labels')}",
            "",
        ]
    )
    return "\n".join(lines)


def _playbook_report(records: list[dict[str, Any]], *, playbook: str, floors: Sequence[float]) -> dict[str, Any]:
    return {
        "score_summary": _score_summary(records, playbook),
        "floor_sweep": [_floor_cell(records, playbook=playbook, floor=float(floor)) for floor in floors],
    }


def _floor_cell(records: list[dict[str, Any]], *, playbook: str, floor: float) -> dict[str, Any]:
    policy_gated = [record for record in records if _passes(record, playbook=playbook, floor=floor, require_allow=True)]
    score_only = [record for record in records if _passes(record, playbook=playbook, floor=floor, require_allow=False)]
    allow_blocked = [
        record
        for record in score_only
        if not _allow(record, playbook)
    ]
    active_actual = [record for record in records if playbook in _active_playbooks(record)]
    return {
        "floor": float(floor),
        "policy_gated": _segment_metrics(policy_gated),
        "score_only": _segment_metrics(score_only),
        "allow_blocked_score_pass": _segment_metrics(allow_blocked),
        "actual_active": _segment_metrics(active_actual),
    }


def _all_cells(records: list[dict[str, Any]], floors: Sequence[float]) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for playbook in _PLAYBOOKS:
        for floor in floors:
            cell = _floor_cell(records, playbook=playbook, floor=float(floor))
            cell["playbook"] = playbook
            cells.append(cell)
    return cells


def _best_cell(cells: list[dict[str, Any]], *, segment: str) -> dict[str, Any] | None:
    rows = []
    for cell in cells:
        metrics = dict(cell.get(segment, {}))
        lift = metrics.get("avg_shadow_minus_baseline")
        count = int(metrics.get("count") or 0)
        if lift is None or count <= 0:
            continue
        rows.append(
            {
                "playbook": cell.get("playbook"),
                "floor": cell.get("floor"),
                "count": count,
                "avg_shadow_minus_baseline": lift,
                "positive_shadow_lift_rate": metrics.get("positive_shadow_lift_rate"),
            }
        )
    if not rows:
        return None
    return sorted(rows, key=lambda row: (float(row["avg_shadow_minus_baseline"]), int(row["count"])), reverse=True)[0]


def _price_action_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        record
        for record in records
        if str(record.get("baseline_selected_model") or "") == "PriceAction"
        and bool(record.get("subset_only_changed", False))
    ]
    return _segment_metrics(rows)


def _model_pair_report(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("baseline_selected_model") or "none"),
            str(record.get("shadow_selected_model") or "none"),
        )
        grouped.setdefault(key, []).append(record)
    rows = []
    for key, items in grouped.items():
        row = _segment_metrics(items)
        row["baseline_selected_model"] = key[0]
        row["shadow_selected_model"] = key[1]
        rows.append(row)
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["baseline_selected_model"]), str(row["shadow_selected_model"])))


def _score_summary(records: list[dict[str, Any]], playbook: str) -> dict[str, Any]:
    _allow_key, score_key = _PLAYBOOK_FIELDS[playbook]
    values = _numbers(record.get(score_key) for record in records)
    return {
        "avg": _mean(values),
        "quantiles": _quantiles(values),
        "non_zero_count": sum(1 for value in values if value > 0.0),
        "non_zero_rate": _rate(sum(1 for value in values if value > 0.0), len(records)),
    }


def _segment_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in records),
        "avg_shadow_net_return": _mean(record.get("shadow_net_return") for record in records),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "selection_changed_count": sum(1 for record in records if bool(record.get("selection_changed", False))),
        "subset_only_changed_count": sum(1 for record in records if bool(record.get("subset_only_changed", False))),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


def _passes(record: Mapping[str, Any], *, playbook: str, floor: float, require_allow: bool) -> bool:
    _allow_key, score_key = _PLAYBOOK_FIELDS[playbook]
    if require_allow and not _allow(record, playbook):
        return False
    return _float(record.get(score_key), 0.0) >= float(floor)


def _allow(record: Mapping[str, Any], playbook: str) -> bool:
    allow_key, _score_key = _PLAYBOOK_FIELDS[playbook]
    return _bool(record.get(allow_key))


def _active_playbooks(record: Mapping[str, Any]) -> list[str]:
    playbooks = record.get("active_playbooks") or []
    if isinstance(playbooks, list):
        return [str(playbook) for playbook in playbooks]
    return [str(playbooks)]


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


def _quantiles(values: Iterable[Any]) -> dict[str, float] | None:
    nums = sorted(_numbers(values))
    if not nums:
        return None
    return {
        "p50": _quantile(nums, 0.50),
        "p75": _quantile(nums, 0.75),
        "p90": _quantile(nums, 0.90),
        "p95": _quantile(nums, 0.95),
    }


def _quantile(nums: list[float], q: float) -> float:
    idx = min(len(nums) - 1, max(0, int(round((len(nums) - 1) * q))))
    return float(nums[idx])


def _numbers(values: Iterable[Any]) -> list[float]:
    nums: list[float] = []
    for value in values:
        try:
            if value is None:
                continue
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return nums


def _float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


__all__ = [
    "build_regime_v2_playbook_calibration",
    "render_regime_v2_playbook_calibration_markdown",
]
