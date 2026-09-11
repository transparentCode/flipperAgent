"""Activation diagnostics for RegimeV2 shadow-decision logs."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_RELAXED_FLOORS = (0.18, 0.20, 0.22, 0.24)
_PLAYBOOKS = ("trend", "breakout", "mean_reversion")
_PLAYBOOK_FIELDS = {
    "trend": ("allow_trend_following", "trend_score", "min_trend_score"),
    "breakout": ("allow_breakout", "breakout_score", "min_breakout_score"),
    "mean_reversion": ("allow_mean_reversion", "mean_reversion_score", "min_mean_reversion_score"),
}


def build_regime_v2_activation_diagnostics(
    records: Iterable[Mapping[str, Any]],
    *,
    relaxed_floors: Sequence[float] = _DEFAULT_RELAXED_FLOORS,
) -> dict[str, Any]:
    """Explain why RegimeV2 shadow playbooks are rarely active."""
    rows = [dict(record) for record in records]
    total = len(rows)
    active = [record for record in rows if bool(record.get("gate_active", False))]
    inactive = [record for record in rows if not bool(record.get("gate_active", False))]
    changed = [record for record in rows if bool(record.get("selection_changed", False))]
    active_changed = [record for record in active if bool(record.get("selection_changed", False))]
    return {
        "phase": "phase_6c_activation_diagnostics",
        "summary": {
            "total_records": total,
            "gate_active_count": len(active),
            "gate_active_rate": _rate(len(active), total),
            "gate_inactive_count": len(inactive),
            "selection_changed_count": len(changed),
            "gate_active_changed_count": len(active_changed),
            "target_candidate_absent_count": sum(1 for record in rows if _int(record.get("target_candidate_count"), 0) <= 0),
            "target_candidate_absent_rate": _rate(
                sum(1 for record in rows if _int(record.get("target_candidate_count"), 0) <= 0),
                total,
            ),
            "missing_policy_context_count": sum(1 for record in rows if _missing_policy_context(record)),
        },
        "distributions": {
            "asset_timeframe": _group_count(rows, ("asset", "timeframe")),
            "gate_reason": _count_key(rows, "gate_reason"),
            "baseline_model": _count_key(rows, "baseline_selected_model"),
            "shadow_model": _count_key(rows, "shadow_selected_model"),
            "active_playbooks": _active_playbook_counts(rows),
            "changed_by_gate_reason": _changed_by_key(rows, "gate_reason"),
        },
        "asset_timeframe": _asset_timeframe(rows),
        "playbooks": {playbook: _playbook_diagnostics(rows, playbook) for playbook in _PLAYBOOKS},
        "relaxed_floor_scenarios": _relaxed_floor_scenarios(rows, relaxed_floors),
        "top_blockers": _top_blockers(rows),
    }


def render_regime_v2_activation_diagnostics_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown activation diagnostic report."""
    summary = dict(report.get("summary", {}))
    playbooks = dict(report.get("playbooks", {}))
    scenarios = list(report.get("relaxed_floor_scenarios", []))
    top_blockers = list(report.get("top_blockers", []))
    lines = [
        "# RegimeV2 Phase 6C Activation Diagnostics",
        "",
        "## Summary",
        "",
        f"- Records: {summary.get('total_records', 0)}",
        f"- Gate active: {summary.get('gate_active_count', 0)} ({summary.get('gate_active_rate')})",
        f"- Gate inactive: {summary.get('gate_inactive_count', 0)}",
        f"- Selection changed: {summary.get('selection_changed_count', 0)}",
        f"- Gate-active changed: {summary.get('gate_active_changed_count', 0)}",
        f"- Target candidate absent: {summary.get('target_candidate_absent_count', 0)} ({summary.get('target_candidate_absent_rate')})",
        f"- Missing policy context: {summary.get('missing_policy_context_count', 0)}",
        "",
        "## Playbook Diagnostics",
        "",
        "| Playbook | Active | Allowed | Score pass | Allow+score pass | Avg score | Floor |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in _PLAYBOOKS:
        row = dict(playbooks.get(name, {}))
        lines.append(
            "| {name} | {active} | {allowed} | {score_pass} | {both} | {avg_score} | {floor} |".format(
                name=name,
                active=row.get("active_count"),
                allowed=row.get("allow_true_count"),
                score_pass=row.get("score_pass_count"),
                both=row.get("allow_and_score_pass_count"),
                avg_score=row.get("avg_score"),
                floor=row.get("default_floor"),
            )
        )

    lines.extend([
        "",
        "## Relaxed Floor Scenarios",
        "",
        "| Floor | Potential active | Potential rate | Score-only active | Score-only rate | Trend | Breakout | MR |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in scenarios:
        lines.append(
            "| {floor} | {active} | {rate} | {score_only} | {score_only_rate} | {trend} | {breakout} | {mr} |".format(
                floor=row.get("floor"),
                active=row.get("potential_active_count"),
                rate=row.get("potential_active_rate"),
                score_only=row.get("score_only_potential_active_count"),
                score_only_rate=row.get("score_only_potential_active_rate"),
                trend=row.get("trend_count"),
                breakout=row.get("breakout_count"),
                mr=row.get("mean_reversion_count"),
            )
        )

    lines.extend([
        "",
        "## Top Blockers",
        "",
    ])
    if top_blockers:
        for row in top_blockers:
            lines.append(f"- {row.get('blocker')}: {row.get('count')}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _playbook_diagnostics(records: list[dict[str, Any]], playbook: str) -> dict[str, Any]:
    allow_key, score_key, floor_key = _PLAYBOOK_FIELDS[playbook]
    floor_values = [_float(record.get(floor_key), None) for record in records]
    valid_floors = [value for value in floor_values if value is not None]
    default_floor = valid_floors[0] if valid_floors else _default_floor(playbook)
    active_count = sum(1 for record in records if playbook in _active_playbooks(record))
    allow_true = [record for record in records if _bool(record.get(allow_key))]
    score_pass = [record for record in records if _float(record.get(score_key), 0.0) >= _float(record.get(floor_key), default_floor)]
    both = [
        record
        for record in records
        if _bool(record.get(allow_key))
        and _float(record.get(score_key), 0.0) >= _float(record.get(floor_key), default_floor)
        and _float(record.get("confidence"), 0.0) >= _float(record.get("min_confidence"), 0.0)
    ]
    return {
        "active_count": active_count,
        "active_rate": _rate(active_count, len(records)),
        "allow_true_count": len(allow_true),
        "allow_true_rate": _rate(len(allow_true), len(records)),
        "score_pass_count": len(score_pass),
        "score_pass_rate": _rate(len(score_pass), len(records)),
        "allow_and_score_pass_count": len(both),
        "allow_and_score_pass_rate": _rate(len(both), len(records)),
        "allow_false_count": len(records) - len(allow_true),
        "score_below_floor_count": len(records) - len(score_pass),
        "avg_score": _mean(record.get(score_key) for record in records),
        "score_quantiles": _quantiles(record.get(score_key) for record in records),
        "default_floor": default_floor,
    }


def _asset_timeframe(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
        grouped.setdefault(key, []).append(record)
    return {key: _pair_diagnostics(items) for key, items in sorted(grouped.items())}


def _pair_diagnostics(records: list[dict[str, Any]]) -> dict[str, Any]:
    active = [record for record in records if bool(record.get("gate_active", False))]
    return {
        "count": len(records),
        "gate_active_count": len(active),
        "gate_active_rate": _rate(len(active), len(records)),
        "selection_changed_count": sum(1 for record in records if bool(record.get("selection_changed", False))),
        "target_candidate_absent_count": sum(1 for record in records if _int(record.get("target_candidate_count"), 0) <= 0),
        "avg_trend_score": _mean(record.get("trend_score") for record in records),
        "avg_breakout_score": _mean(record.get("breakout_score") for record in records),
        "avg_mean_reversion_score": _mean(record.get("mean_reversion_score") for record in records),
        "avg_confidence": _mean(record.get("confidence") for record in records),
        "gate_reason": _count_key(records, "gate_reason"),
        "active_playbooks": _active_playbook_counts(records),
    }


def _relaxed_floor_scenarios(records: list[dict[str, Any]], relaxed_floors: Sequence[float]) -> list[dict[str, Any]]:
    rows = []
    for floor in relaxed_floors:
        playbook_counts = {
            playbook: sum(1 for record in records if _playbook_passes(record, playbook, float(floor)))
            for playbook in _PLAYBOOKS
        }
        score_only_counts = {
            playbook: sum(1 for record in records if _playbook_score_passes(record, playbook, float(floor)))
            for playbook in _PLAYBOOKS
        }
        potential_active = sum(1 for record in records if any(_playbook_passes(record, playbook, float(floor)) for playbook in _PLAYBOOKS))
        score_only_potential = sum(
            1 for record in records if any(_playbook_score_passes(record, playbook, float(floor)) for playbook in _PLAYBOOKS)
        )
        rows.append(
            {
                "floor": float(floor),
                "potential_active_count": potential_active,
                "potential_active_rate": _rate(potential_active, len(records)),
                "score_only_potential_active_count": score_only_potential,
                "score_only_potential_active_rate": _rate(score_only_potential, len(records)),
                "trend_count": playbook_counts["trend"],
                "breakout_count": playbook_counts["breakout"],
                "mean_reversion_count": playbook_counts["mean_reversion"],
                "score_only_trend_count": score_only_counts["trend"],
                "score_only_breakout_count": score_only_counts["breakout"],
                "score_only_mean_reversion_count": score_only_counts["mean_reversion"],
            }
        )
    return rows


def _playbook_passes(record: Mapping[str, Any], playbook: str, floor: float) -> bool:
    allow_key, score_key, _floor_key = _PLAYBOOK_FIELDS[playbook]
    return (
        _bool(record.get(allow_key))
        and _float(record.get(score_key), 0.0) >= float(floor)
        and _float(record.get("confidence"), 0.0) >= _float(record.get("min_confidence"), 0.0)
    )


def _playbook_score_passes(record: Mapping[str, Any], playbook: str, floor: float) -> bool:
    _allow_key, score_key, _floor_key = _PLAYBOOK_FIELDS[playbook]
    return (
        _float(record.get(score_key), 0.0) >= float(floor)
        and _float(record.get("confidence"), 0.0) >= _float(record.get("min_confidence"), 0.0)
    )


def _top_blockers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for record in records:
        if bool(record.get("gate_active", False)):
            continue
        if _int(record.get("target_candidate_count"), 0) <= 0:
            counts["no_target_candidate"] += 1
        for playbook in _PLAYBOOKS:
            allow_key, score_key, floor_key = _PLAYBOOK_FIELDS[playbook]
            if not _bool(record.get(allow_key)):
                counts[f"{playbook}_allow_false"] += 1
            if _float(record.get(score_key), 0.0) < _float(record.get(floor_key), _default_floor(playbook)):
                counts[f"{playbook}_score_below_floor"] += 1
        if _float(record.get("confidence"), 0.0) < _float(record.get("min_confidence"), 0.0):
            counts["confidence_below_floor"] += 1
    return [
        {"blocker": blocker, "count": count}
        for blocker, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _missing_policy_context(record: Mapping[str, Any]) -> bool:
    required = [
        "allow_trend_following",
        "allow_breakout",
        "allow_mean_reversion",
        "min_trend_score",
        "min_breakout_score",
        "min_mean_reversion_score",
    ]
    return any(key not in record or record.get(key) is None for key in required)


def _active_playbooks(record: Mapping[str, Any]) -> list[str]:
    playbooks = record.get("active_playbooks") or []
    return [str(playbook) for playbook in playbooks] if isinstance(playbooks, list) else [str(playbooks)]


def _active_playbook_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        playbooks = _active_playbooks(record)
        if not playbooks:
            counts["none"] += 1
        for playbook in playbooks:
            counts[playbook] += 1
    return dict(sorted(counts.items()))


def _changed_by_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records if bool(record.get("selection_changed", False)))
    return dict(sorted(counts.items()))


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _mean(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    if not nums:
        return None
    return sum(nums) / len(nums)


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
    if not nums:
        return 0.0
    idx = min(len(nums) - 1, max(0, int(round((len(nums) - 1) * q))))
    return float(nums[idx])


def _numbers(values: Iterable[Any]) -> list[float]:
    nums: list[float] = []
    for value in values:
        parsed = _float(value, None)
        if parsed is not None:
            nums.append(parsed)
    return nums


def _float(value: Any, default: float | None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
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


def _default_floor(playbook: str) -> float:
    if playbook == "trend":
        return 0.24
    if playbook == "breakout":
        return 0.24
    return 0.24


__all__ = [
    "build_regime_v2_activation_diagnostics",
    "render_regime_v2_activation_diagnostics_markdown",
]
