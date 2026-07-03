"""Offline replay/reporting for RegimeV2 shadow-selection JSONL logs."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import json


def load_regime_v2_shadow_decisions(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Load RegimeV2 shadow-decision JSONL records.

    Returns ``(records, invalid_count)``. Missing files are treated as an empty
    log so scheduled report jobs can run before the first shadow record exists.
    """
    log_path = Path(path)
    if not log_path.exists():
        return [], 0

    records: list[dict[str, Any]] = []
    invalid_count = 0
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            invalid_count += 1
            continue
        if not isinstance(parsed, dict):
            invalid_count += 1
            continue
        records.append(parsed)
    return records, invalid_count


def build_regime_v2_shadow_report(
    records: Iterable[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    invalid_record_count: int = 0,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Build an aggregate Phase 5C shadow replay report."""
    raw_records = [dict(record) for record in records]
    filtered = _filter_records(raw_records, asset=asset, timeframe=timeframe)
    total = len(filtered)
    changed = [record for record in filtered if bool(record.get("selection_changed", False))]
    gate_active = [record for record in filtered if bool(record.get("gate_active", False))]
    gate_active_changed = [record for record in gate_active if bool(record.get("selection_changed", False))]
    gate_inactive = [record for record in filtered if not bool(record.get("gate_active", False))]
    gate_inactive_changed = [record for record in gate_inactive if bool(record.get("selection_changed", False))]
    missing_payload = [record for record in filtered if record.get("gate_reason") == "missing_regime_v2_payload"]
    inactive_policy = [
        record
        for record in filtered
        if record.get("gate_reason") in {"inactive_playbook_policy", "inactive_trend_policy"}
    ]
    inactive_policy_changed = [record for record in inactive_policy if bool(record.get("selection_changed", False))]
    no_active_playbook = [record for record in filtered if not record.get("active_playbooks")]
    shadow_empty = [record for record in filtered if not record.get("shadow_selected_model")]
    shadow_empty_changed = [record for record in shadow_empty if bool(record.get("selection_changed", False))]
    subset_only_changed = [record for record in changed if _subset_only_removed(record)]
    price_action_subset_exclusions = [
        record
        for record in subset_only_changed
        if str(record.get("baseline_selected_model") or "") == "PriceAction"
    ]

    summary = {
        "source_path": source_path,
        "total_records_read": len(raw_records),
        "invalid_record_count": int(invalid_record_count),
        "records_after_filter": total,
        "asset_filter": asset.upper() if asset else None,
        "timeframe_filter": timeframe,
        "selection_changed_count": len(changed),
        "selection_changed_rate": _rate(len(changed), total),
        "gate_active_count": len(gate_active),
        "gate_active_rate": _rate(len(gate_active), total),
        "gate_active_changed_count": len(gate_active_changed),
        "gate_active_changed_rate": _rate(len(gate_active_changed), len(gate_active)),
        "gate_inactive_count": len(gate_inactive),
        "gate_inactive_changed_count": len(gate_inactive_changed),
        "gate_inactive_changed_rate": _rate(len(gate_inactive_changed), len(gate_inactive)),
        "missing_regime_payload_count": len(missing_payload),
        "inactive_policy_count": len(inactive_policy),
        "inactive_policy_changed_count": len(inactive_policy_changed),
        "inactive_policy_changed_rate": _rate(len(inactive_policy_changed), len(inactive_policy)),
        "no_active_playbook_count": len(no_active_playbook),
        "shadow_empty_count": len(shadow_empty),
        "shadow_empty_changed_count": len(shadow_empty_changed),
        "subset_only_changed_count": len(subset_only_changed),
        "price_action_subset_exclusion_count": len(price_action_subset_exclusions),
        "avg_edge_delta": _mean(record.get("edge_delta") for record in filtered),
        "avg_trend_score": _mean(record.get("trend_score") for record in filtered),
        "avg_breakout_score": _mean(record.get("breakout_score") for record in filtered),
        "avg_mean_reversion_score": _mean(record.get("mean_reversion_score") for record in filtered),
        "avg_confidence": _mean(record.get("confidence") for record in filtered),
        "avg_uncertainty": _mean(record.get("uncertainty") for record in filtered),
    }

    return {
        "phase": "phase_5_shadow_replay",
        "summary": summary,
        "distributions": {
            "asset_timeframe": _group_count(filtered, ("asset", "timeframe")),
            "baseline_model": _count_key(filtered, "baseline_selected_model"),
            "shadow_model": _count_key(filtered, "shadow_selected_model"),
            "gate_reason": _count_key(filtered, "gate_reason"),
            "reason": _count_key(filtered, "reason"),
            "shadow_subset": _count_key(filtered, "shadow_subset_name"),
            "active_playbooks": _active_playbook_counts(filtered),
        },
        "changed_pick_groups": _changed_pick_groups(changed),
        "gate_active_changed_pick_groups": _changed_pick_groups(gate_active_changed),
        "inactive_policy_changed_pick_groups": _changed_pick_groups(inactive_policy_changed),
        "subset_only_changed_pick_groups": _changed_pick_groups(subset_only_changed),
        "model_pair_summary": _model_pair_summary(filtered),
    }


def run_regime_v2_shadow_report(
    path: str | Path,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Load a JSONL log and build the Phase 5C report payload."""
    records, invalid_count = load_regime_v2_shadow_decisions(path)
    return build_regime_v2_shadow_report(
        records,
        source_path=str(path),
        invalid_record_count=invalid_count,
        asset=asset,
        timeframe=timeframe,
    )


def render_regime_v2_shadow_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown summary for a shadow replay report."""
    summary = dict(report.get("summary", {}))
    distributions = dict(report.get("distributions", {}))
    changed_groups = list(report.get("changed_pick_groups", []))
    model_pairs = list(report.get("model_pair_summary", []))

    lines = [
        "# RegimeV2 Phase 5 Shadow Replay Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records read: {summary.get('total_records_read', 0)}",
        f"- Invalid records: {summary.get('invalid_record_count', 0)}",
        f"- Records after filter: {summary.get('records_after_filter', 0)}",
        f"- Selection changed: {summary.get('selection_changed_count', 0)} ({summary.get('selection_changed_rate')})",
        f"- Gate active: {summary.get('gate_active_count', 0)} ({summary.get('gate_active_rate')})",
        f"- Gate-active changed: {summary.get('gate_active_changed_count', 0)} ({summary.get('gate_active_changed_rate')})",
        f"- Gate-inactive changed: {summary.get('gate_inactive_changed_count', 0)} ({summary.get('gate_inactive_changed_rate')})",
        f"- Inactive-policy changed: {summary.get('inactive_policy_changed_count', 0)} ({summary.get('inactive_policy_changed_rate')})",
        f"- Subset-only changed: {summary.get('subset_only_changed_count', 0)}",
        f"- PriceAction subset exclusions: {summary.get('price_action_subset_exclusion_count', 0)}",
        f"- Missing RegimeV2 payload: {summary.get('missing_regime_payload_count', 0)}",
        f"- Inactive policy: {summary.get('inactive_policy_count', 0)}",
        f"- No active playbook: {summary.get('no_active_playbook_count', 0)}",
        f"- Avg edge delta: {summary.get('avg_edge_delta')}",
        f"- Avg confidence: {summary.get('avg_confidence')}",
        f"- Avg uncertainty: {summary.get('avg_uncertainty')}",
        "",
        "## Active Playbooks",
        "",
    ]
    playbooks = dict(distributions.get("active_playbooks", {}))
    if playbooks:
        for name, count in sorted(playbooks.items()):
            lines.append(f"- {name}: {count}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Changed Pick Groups",
        "",
        "| Baseline | Shadow | Count | Avg edge delta |",
        "|---|---|---:|---:|",
    ])
    if changed_groups:
        for row in changed_groups:
            lines.append(
                "| {baseline} | {shadow} | {count} | {avg_edge_delta} |".format(
                    baseline=row.get("baseline_selected_model"),
                    shadow=row.get("shadow_selected_model"),
                    count=row.get("count"),
                    avg_edge_delta=row.get("avg_edge_delta"),
                )
            )
    else:
        lines.append("| n/a | n/a | 0 | n/a |")

    lines.extend([
        "",
        "## Model Pair Summary",
        "",
        "| Baseline | Shadow | Count | Changed rate | Avg edge delta |",
        "|---|---|---:|---:|---:|",
    ])
    if model_pairs:
        for row in model_pairs:
            lines.append(
                "| {baseline} | {shadow} | {count} | {changed_rate} | {avg_edge_delta} |".format(
                    baseline=row.get("baseline_selected_model"),
                    shadow=row.get("shadow_selected_model"),
                    count=row.get("count"),
                    changed_rate=row.get("changed_rate"),
                    avg_edge_delta=row.get("avg_edge_delta"),
                )
            )
    else:
        lines.append("| n/a | n/a | 0 | n/a | n/a |")

    lines.append("")
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


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _subset_only_removed(record: Mapping[str, Any]) -> bool:
    if not bool(record.get("selection_changed", False)):
        return False
    if not bool(record.get("shadow_subset_only", False)):
        return False
    if bool(record.get("include_non_target_models", True)):
        return False
    baseline = record.get("baseline_selected_model")
    shadow = record.get("shadow_selected_model")
    if baseline is None or shadow is not None:
        return False
    target_models = record.get("target_models") or []
    return str(baseline) not in {str(model) for model in target_models}


def _mean(values: Iterable[Any]) -> float | None:
    nums: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    if not nums:
        return None
    return sum(nums) / len(nums)


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


def _active_playbook_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for record in records:
        playbooks = record.get("active_playbooks") or []
        if not isinstance(playbooks, list):
            counts[str(playbooks)] += 1
            continue
        if not playbooks:
            counts["none"] += 1
            continue
        for playbook in playbooks:
            counts[str(playbook)] += 1
    return dict(sorted(counts.items()))


def _changed_pick_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record.get("baseline_selected_model") or "none"),
            str(record.get("shadow_selected_model") or "none"),
        )
        grouped[key].append(record)
    rows = [
        {
            "baseline_selected_model": key[0],
            "shadow_selected_model": key[1],
            "count": len(items),
            "avg_edge_delta": _mean(item.get("edge_delta") for item in items),
        }
        for key, items in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["baseline_selected_model"]), str(row["shadow_selected_model"])))


def _model_pair_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record.get("baseline_selected_model") or "none"),
            str(record.get("shadow_selected_model") or "none"),
        )
        grouped[key].append(record)
    rows = []
    for key, items in grouped.items():
        changed_count = sum(1 for item in items if bool(item.get("selection_changed", False)))
        rows.append(
            {
                "baseline_selected_model": key[0],
                "shadow_selected_model": key[1],
                "count": len(items),
                "changed_count": changed_count,
                "changed_rate": _rate(changed_count, len(items)),
                "avg_edge_delta": _mean(item.get("edge_delta") for item in items),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["baseline_selected_model"]), str(row["shadow_selected_model"])))


__all__ = [
    "build_regime_v2_shadow_report",
    "load_regime_v2_shadow_decisions",
    "render_regime_v2_shadow_report_markdown",
    "run_regime_v2_shadow_report",
]
