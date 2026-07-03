"""Reporting and outcome labeling for PA asset paper guardrail logs."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping
import json

import pandas as pd

from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes

_DEFAULT_LOG_PATH = "logs/regime_v2_pa_asset_paper_decisions.jsonl"


def load_pa_paper_decisions(path: str | Path = _DEFAULT_LOG_PATH) -> tuple[list[dict[str, Any]], int]:
    """Load PA paper-decision JSONL records.

    Missing files are treated as empty logs so scheduled/report jobs can run
    before a paper rollout has produced records.
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


def build_pa_paper_report(
    records: Iterable[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    invalid_record_count: int = 0,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    """Build aggregate metrics over PA paper-decision records."""
    raw = [dict(record) for record in records]
    filtered = _filter_records(raw, asset=asset, timeframe=timeframe)
    active = [record for record in filtered if bool(record.get("paper_active", False))]
    changed = [record for record in filtered if bool(record.get("selection_changed", False))]
    suppressed_total = sum(_int_value(record.get("suppressed_count"), 0) for record in filtered)
    total = len(filtered)
    return {
        "phase": "phase_6k_pa_paper_report",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(raw),
            "invalid_record_count": int(invalid_record_count),
            "records_after_filter": total,
            "asset_filter": asset.upper() if asset else None,
            "timeframe_filter": timeframe,
            "paper_active_count": len(active),
            "paper_active_rate": _rate(len(active), total),
            "selection_changed_count": len(changed),
            "selection_changed_rate": _rate(len(changed), total),
            "suppressed_total": suppressed_total,
            "avg_suppressed_count": _mean(record.get("suppressed_count") for record in filtered),
            "avg_edge_delta": _mean(record.get("edge_delta") for record in filtered),
        },
        "distributions": {
            "asset_timeframe": _group_count(filtered, ("asset", "timeframe")),
            "target": _group_count(filtered, ("target_asset", "target_timeframe", "target_direction")),
            "paper_reason": _count_key(filtered, "paper_reason"),
            "baseline_model": _count_key(filtered, "baseline_selected_model"),
            "paper_model": _count_key(filtered, "paper_selected_model"),
        },
        "changed_pick_groups": _changed_groups(changed),
        "model_pair_summary": _model_pair_summary(filtered),
    }


def run_pa_paper_report(
    path: str | Path = _DEFAULT_LOG_PATH,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
) -> dict[str, Any]:
    records, invalid = load_pa_paper_decisions(path)
    return build_pa_paper_report(
        records,
        source_path=str(path),
        invalid_record_count=invalid,
        asset=asset,
        timeframe=timeframe,
    )


def render_pa_paper_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown report for PA paper decisions."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6K PA Paper Decision Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records read: {summary.get('total_records_read', 0)}",
        f"- Invalid records: {summary.get('invalid_record_count', 0)}",
        f"- Records after filter: {summary.get('records_after_filter', 0)}",
        f"- Paper active: {summary.get('paper_active_count', 0)} ({summary.get('paper_active_rate')})",
        f"- Selection changed: {summary.get('selection_changed_count', 0)} ({summary.get('selection_changed_rate')})",
        f"- Suppressed total: {summary.get('suppressed_total', 0)}",
        f"- Avg edge delta: {summary.get('avg_edge_delta')}",
        "",
        "## Changed Pick Groups",
        "",
        "| Baseline | Paper | Count | Avg edge delta |",
        "|---|---|---:|---:|",
    ]
    groups = list(report.get("changed_pick_groups", []))
    if groups:
        for row in groups:
            lines.append(
                "| {baseline} | {paper} | {count} | {avg_edge_delta} |".format(
                    baseline=row.get("baseline_selected_model"),
                    paper=row.get("paper_selected_model"),
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
        "| Baseline | Paper | Count | Changed rate | Avg edge delta |",
        "|---|---|---:|---:|---:|",
    ])
    pairs = list(report.get("model_pair_summary", []))
    if pairs:
        for row in pairs:
            lines.append(
                "| {baseline} | {paper} | {count} | {changed_rate} | {avg_edge_delta} |".format(
                    baseline=row.get("baseline_selected_model"),
                    paper=row.get("paper_selected_model"),
                    count=row.get("count"),
                    changed_rate=row.get("changed_rate"),
                    avg_edge_delta=row.get("avg_edge_delta"),
                )
            )
    else:
        lines.append("| n/a | n/a | 0 | n/a | n/a |")
    lines.append("")
    return "\n".join(lines)


def label_pa_paper_outcomes(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizon_bars: int = 12,
    fee_bps: float = 5.0,
) -> list[dict[str, Any]]:
    """Attach future-return outcomes to PA paper records."""
    shadow_like = [_paper_to_shadow_like(record) for record in records]
    labeled = label_shadow_decision_outcomes(
        shadow_like,
        ohlcv_by_pair,
        horizon_bars=horizon_bars,
        fee_bps=fee_bps,
    )
    return [_shadow_like_to_paper_labeled(record) for record in labeled]


def write_labeled_pa_paper_outcomes(records: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    """Write labeled PA paper outcomes to JSONL."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
    return output_path


def load_labeled_pa_paper_outcomes(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Load labeled PA paper outcome JSONL rows."""
    return load_pa_paper_decisions(path)


def build_pa_paper_outcome_report(
    records: Iterable[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    invalid_record_count: int = 0,
) -> dict[str, Any]:
    """Build aggregate metrics over labeled PA paper outcome rows."""
    rows = [dict(record) for record in records]
    labeled = [row for row in rows if row.get("outcome_label") != "unlabeled"]
    changed = [row for row in labeled if bool(row.get("selection_changed", False))]
    active = [row for row in labeled if bool(row.get("paper_active", False))]
    active_changed = [row for row in active if bool(row.get("selection_changed", False))]
    return {
        "phase": "phase_6k_pa_paper_outcome_labeling",
        "summary": {
            "source_path": source_path,
            "total_records_read": len(rows),
            "invalid_record_count": int(invalid_record_count),
            "labeled_count": len(labeled),
            "unlabeled_count": len(rows) - len(labeled),
            "paper_active_count": len(active),
            "selection_changed_count": len(changed),
            "paper_active_changed_count": len(active_changed),
            "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in labeled),
            "avg_paper_net_return": _mean(row.get("paper_net_return") for row in labeled),
            "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in labeled),
            "avg_changed_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in changed),
            "avg_active_changed_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in active_changed),
            "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in labeled),
            "changed_positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in changed),
            "active_changed_positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in active_changed),
        },
        "distributions": {
            "outcome_label": _count_key(labeled, "outcome_label"),
            "unlabeled_reason": _count_key([row for row in rows if row.get("outcome_label") == "unlabeled"], "outcome_reason"),
            "asset_timeframe": _group_count(labeled, ("asset", "timeframe")),
            "baseline_model": _count_key(labeled, "baseline_selected_model"),
            "paper_model": _count_key(labeled, "paper_selected_model"),
        },
        "model_pair_outcomes": _paper_pair_outcomes(labeled),
        "active_changed_outcomes": _paper_pair_outcomes(active_changed),
    }


def render_pa_paper_outcome_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown outcome report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6K PA Paper Outcome Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records read: {summary.get('total_records_read', 0)}",
        f"- Labeled: {summary.get('labeled_count', 0)}",
        f"- Unlabeled: {summary.get('unlabeled_count', 0)}",
        f"- Paper active: {summary.get('paper_active_count', 0)}",
        f"- Selection changed: {summary.get('selection_changed_count', 0)}",
        f"- Avg baseline net return: {summary.get('avg_baseline_net_return')}",
        f"- Avg paper net return: {summary.get('avg_paper_net_return')}",
        f"- Avg paper minus baseline: {summary.get('avg_paper_minus_baseline')}",
        f"- Avg changed paper minus baseline: {summary.get('avg_changed_paper_minus_baseline')}",
        f"- Changed positive lift rate: {summary.get('changed_positive_paper_lift_rate')}",
        "",
        "## Model Pair Outcomes",
        "",
        "| Baseline | Paper | Count | Avg lift | Positive rate | Labels |",
        "|---|---|---:|---:|---:|---|",
    ]
    pairs = list(report.get("model_pair_outcomes", []))
    if pairs:
        for row in pairs:
            lines.append(
                "| {baseline} | {paper} | {count} | {avg_lift} | {positive_rate} | {labels} |".format(
                    baseline=row.get("baseline_selected_model"),
                    paper=row.get("paper_selected_model"),
                    count=row.get("count"),
                    avg_lift=row.get("avg_paper_minus_baseline"),
                    positive_rate=row.get("positive_paper_lift_rate"),
                    labels=row.get("outcome_labels"),
                )
            )
    else:
        lines.append("| n/a | n/a | 0 | n/a | n/a | n/a |")
    lines.append("")
    return "\n".join(lines)


def _paper_to_shadow_like(record: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["shadow_selected_model"] = record.get("paper_selected_model")
    out["shadow_selected_direction"] = record.get("paper_selected_direction")
    out["shadow_edge_score"] = record.get("paper_edge_score")
    out["shadow_conviction"] = record.get("paper_conviction")
    out["shadow_selection_score"] = record.get("paper_selection_score")
    return out


def _shadow_like_to_paper_labeled(record: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(record)
    out["paper_selected_model"] = record.get("shadow_selected_model")
    out["paper_selected_direction"] = record.get("shadow_selected_direction")
    out["paper_net_return"] = record.get("shadow_net_return")
    out["paper_minus_baseline"] = record.get("shadow_minus_baseline")
    out.pop("shadow_selected_model", None)
    out.pop("shadow_selected_direction", None)
    out.pop("shadow_edge_score", None)
    out.pop("shadow_conviction", None)
    out.pop("shadow_selection_score", None)
    out.pop("shadow_net_return", None)
    out.pop("shadow_minus_baseline", None)
    return out


def _filter_records(records: list[dict[str, Any]], *, asset: str | None, timeframe: str | None) -> list[dict[str, Any]]:
    rows = records
    if asset:
        wanted = asset.upper()
        rows = [row for row in rows if str(row.get("asset") or "").upper() == wanted]
    if timeframe:
        rows = [row for row in rows if str(row.get("timeframe") or "") == str(timeframe)]
    return rows


def _changed_groups(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for record in records:
        key = (record.get("baseline_selected_model"), record.get("paper_selected_model"))
        grouped.setdefault(key, []).append(record)
    rows = []
    for (baseline, paper), items in grouped.items():
        rows.append(
            {
                "baseline_selected_model": baseline,
                "paper_selected_model": paper,
                "count": len(items),
                "avg_edge_delta": _mean(item.get("edge_delta") for item in items),
            }
        )
    return sorted(rows, key=lambda row: int(row["count"]), reverse=True)


def _model_pair_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for record in records:
        key = (record.get("baseline_selected_model"), record.get("paper_selected_model"))
        grouped.setdefault(key, []).append(record)
    rows = []
    for (baseline, paper), items in grouped.items():
        rows.append(
            {
                "baseline_selected_model": baseline,
                "paper_selected_model": paper,
                "count": len(items),
                "changed_count": sum(1 for item in items if bool(item.get("selection_changed", False))),
                "changed_rate": _rate(sum(1 for item in items if bool(item.get("selection_changed", False))), len(items)),
                "avg_edge_delta": _mean(item.get("edge_delta") for item in items),
            }
        )
    return sorted(rows, key=lambda row: int(row["count"]), reverse=True)


def _paper_pair_outcomes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for record in records:
        key = (record.get("baseline_selected_model"), record.get("paper_selected_model"))
        grouped.setdefault(key, []).append(record)
    rows = []
    for (baseline, paper), items in grouped.items():
        rows.append(
            {
                "baseline_selected_model": baseline,
                "paper_selected_model": paper,
                "count": len(items),
                "avg_baseline_net_return": _mean(item.get("baseline_net_return") for item in items),
                "avg_paper_net_return": _mean(item.get("paper_net_return") for item in items),
                "avg_paper_minus_baseline": _mean(item.get("paper_minus_baseline") for item in items),
                "positive_paper_lift_rate": _positive_rate(item.get("paper_minus_baseline") for item in items),
                "outcome_labels": dict(sorted(Counter(str(item.get("outcome_label")) for item in items).items())),
            }
        )
    return sorted(rows, key=lambda row: int(row["count"]), reverse=True)


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key, "none")) for record in records).items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key, "none")) for key in keys) for record in records)
    return dict(sorted(counts.items()))


def _mean(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    return sum(nums) / len(nums) if nums else None


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    return sum(1 for value in nums if value > 0.0) / len(nums) if nums else None


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


def _int_value(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = [
    "build_pa_paper_outcome_report",
    "build_pa_paper_report",
    "label_pa_paper_outcomes",
    "load_labeled_pa_paper_outcomes",
    "load_pa_paper_decisions",
    "render_pa_paper_outcome_report_markdown",
    "render_pa_paper_report_markdown",
    "run_pa_paper_report",
    "write_labeled_pa_paper_outcomes",
]
