"""Outcome labeling for RegimeV2 shadow-selection decisions."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import json
import math

import pandas as pd


def load_labeled_shadow_outcomes(path: str | Path) -> tuple[list[dict[str, Any]], int]:
    """Load labeled shadow-outcome JSONL rows.

    Returns ``(records, invalid_count)``. Missing files are treated as empty so
    scheduled/report jobs can run before the first outcome row exists.
    """
    output_path = Path(path)
    if not output_path.exists():
        return [], 0

    records: list[dict[str, Any]] = []
    invalid_count = 0
    for raw_line in output_path.read_text(encoding="utf-8").splitlines():
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


def label_shadow_decision_outcomes(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizon_bars: int = 12,
    fee_bps: float = 0.0,
) -> list[dict[str, Any]]:
    """Attach future-return outcomes to shadow-decision records.

    Baseline and shadow returns are directional log returns over ``horizon_bars``
    minus a one-position fee. A missing shadow selection is treated as flat.
    Records missing baseline direction or future candles are emitted as
    ``outcome_label='unlabeled'`` with a reason.
    """
    labeled: list[dict[str, Any]] = []
    prepared = {
        (asset.upper(), timeframe): _prepare_ohlcv(frame)
        for (asset, timeframe), frame in ohlcv_by_pair.items()
    }
    for raw in records:
        record = dict(raw)
        asset = str(record.get("asset") or "").upper()
        timeframe = str(record.get("timeframe") or "")
        frame = prepared.get((asset, timeframe))
        labeled.append(
            _label_one_record(
                record,
                frame,
                horizon_bars=horizon_bars,
                fee_bps=fee_bps,
            )
        )
    return labeled


def write_labeled_shadow_outcomes(records: Iterable[Mapping[str, Any]], path: str | Path) -> Path:
    """Write labeled outcome records to JSONL."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
    return output_path


def build_shadow_outcome_report(
    records: Iterable[Mapping[str, Any]],
    *,
    source_path: str | None = None,
    invalid_record_count: int = 0,
) -> dict[str, Any]:
    """Build aggregate metrics over labeled shadow-outcome rows."""
    rows = [dict(record) for record in records]
    labeled = [row for row in rows if row.get("outcome_label") != "unlabeled"]
    changed = [row for row in labeled if bool(row.get("selection_changed", False))]
    gate_active = [row for row in labeled if bool(row.get("gate_active", False))]
    gate_active_changed = [row for row in gate_active if bool(row.get("selection_changed", False))]
    subset_only = [row for row in labeled if bool(row.get("subset_only_changed", False))]

    summary = {
        "source_path": source_path,
        "total_records_read": len(rows),
        "invalid_record_count": int(invalid_record_count),
        "labeled_count": len(labeled),
        "unlabeled_count": len(rows) - len(labeled),
        "selection_changed_count": len(changed),
        "gate_active_count": len(gate_active),
        "gate_active_changed_count": len(gate_active_changed),
        "subset_only_changed_count": len(subset_only),
        "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in labeled),
        "avg_shadow_net_return": _mean(row.get("shadow_net_return") for row in labeled),
        "avg_shadow_minus_baseline": _mean(row.get("shadow_minus_baseline") for row in labeled),
        "avg_changed_shadow_minus_baseline": _mean(row.get("shadow_minus_baseline") for row in changed),
        "avg_gate_active_shadow_minus_baseline": _mean(row.get("shadow_minus_baseline") for row in gate_active),
        "avg_gate_active_changed_shadow_minus_baseline": _mean(row.get("shadow_minus_baseline") for row in gate_active_changed),
        "positive_shadow_lift_rate": _positive_rate(row.get("shadow_minus_baseline") for row in labeled),
        "changed_positive_shadow_lift_rate": _positive_rate(row.get("shadow_minus_baseline") for row in changed),
        "gate_active_changed_positive_shadow_lift_rate": _positive_rate(
            row.get("shadow_minus_baseline") for row in gate_active_changed
        ),
    }
    return {
        "phase": "phase_6_shadow_outcome_labeling",
        "summary": summary,
        "distributions": {
            "outcome_label": _count_key(labeled, "outcome_label"),
            "unlabeled_reason": _count_key([row for row in rows if row.get("outcome_label") == "unlabeled"], "outcome_reason"),
            "asset_timeframe": _group_count(labeled, ("asset", "timeframe")),
            "baseline_model": _count_key(labeled, "baseline_selected_model"),
            "shadow_model": _count_key(labeled, "shadow_selected_model"),
        },
        "model_pair_outcomes": _model_pair_outcomes(labeled),
        "gate_active_changed_outcomes": _model_pair_outcomes(gate_active_changed),
        "subset_only_outcomes": _model_pair_outcomes(subset_only),
    }


def render_shadow_outcome_report_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown outcome report."""
    summary = dict(report.get("summary", {}))
    distributions = dict(report.get("distributions", {}))
    lines = [
        "# RegimeV2 Phase 6 Shadow Outcome Report",
        "",
        "## Summary",
        "",
        f"- Source: {summary.get('source_path') or 'n/a'}",
        f"- Records read: {summary.get('total_records_read', 0)}",
        f"- Labeled: {summary.get('labeled_count', 0)}",
        f"- Unlabeled: {summary.get('unlabeled_count', 0)}",
        f"- Selection changed: {summary.get('selection_changed_count', 0)}",
        f"- Gate-active changed: {summary.get('gate_active_changed_count', 0)}",
        f"- Subset-only changed: {summary.get('subset_only_changed_count', 0)}",
        f"- Avg baseline net return: {summary.get('avg_baseline_net_return')}",
        f"- Avg shadow net return: {summary.get('avg_shadow_net_return')}",
        f"- Avg shadow minus baseline: {summary.get('avg_shadow_minus_baseline')}",
        f"- Avg changed shadow minus baseline: {summary.get('avg_changed_shadow_minus_baseline')}",
        f"- Avg gate-active changed shadow minus baseline: {summary.get('avg_gate_active_changed_shadow_minus_baseline')}",
        f"- Changed positive lift rate: {summary.get('changed_positive_shadow_lift_rate')}",
        "",
        "## Outcome Labels",
        "",
    ]
    outcome_labels = dict(distributions.get("outcome_label", {}))
    if outcome_labels:
        for label, count in sorted(outcome_labels.items()):
            lines.append(f"- {label}: {count}")
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Model Pair Outcomes",
        "",
        "| Baseline | Shadow | Count | Avg lift | Positive rate | Labels |",
        "|---|---|---:|---:|---:|---|",
    ])
    for row in list(report.get("model_pair_outcomes", [])):
        lines.append(
            "| {baseline} | {shadow} | {count} | {avg_lift} | {positive_rate} | {labels} |".format(
                baseline=row.get("baseline_selected_model"),
                shadow=row.get("shadow_selected_model"),
                count=row.get("count"),
                avg_lift=row.get("avg_shadow_minus_baseline"),
                positive_rate=row.get("positive_shadow_lift_rate"),
                labels=row.get("outcome_labels"),
            )
        )
    if not report.get("model_pair_outcomes"):
        lines.append("| n/a | n/a | 0 | n/a | n/a | n/a |")
    lines.append("")
    return "\n".join(lines)


def _label_one_record(
    record: dict[str, Any],
    frame: pd.DataFrame | None,
    *,
    horizon_bars: int,
    fee_bps: float,
) -> dict[str, Any]:
    out = dict(record)
    out["outcome_horizon_bars"] = int(horizon_bars)
    out["outcome_fee_bps"] = float(fee_bps)
    if frame is None or frame.empty:
        return _unlabeled(out, "missing_ohlcv_pair")
    baseline_direction = _optional_int(record.get("baseline_selected_direction"))
    shadow_direction = _optional_int(record.get("shadow_selected_direction"))
    if baseline_direction is None:
        return _unlabeled(out, "missing_baseline_direction")

    timestamp = _optional_float(record.get("timestamp"))
    if timestamp is None:
        return _unlabeled(out, "missing_timestamp")
    pos = _position_for_timestamp(frame, timestamp)
    if pos is None:
        return _unlabeled(out, "timestamp_not_found")
    future_pos = pos + int(horizon_bars)
    if future_pos >= len(frame):
        return _unlabeled(out, "insufficient_future_bars")

    close_now = float(frame["close"].iloc[pos])
    close_future = float(frame["close"].iloc[future_pos])
    if close_now <= 0.0 or close_future <= 0.0:
        return _unlabeled(out, "invalid_close")

    forward_return = math.log(close_future / close_now)
    fee = float(fee_bps) / 10_000.0
    baseline_net = _directional_net_return(baseline_direction, forward_return, fee)
    shadow_net = _directional_net_return(shadow_direction, forward_return, fee)
    lift = shadow_net - baseline_net

    out.update(
        {
            "outcome_label": _outcome_label(baseline_net, shadow_net, lift, record),
            "outcome_reason": "labeled",
            "decision_close": close_now,
            "future_close": close_future,
            "forward_log_return": forward_return,
            "baseline_net_return": baseline_net,
            "shadow_net_return": shadow_net,
            "shadow_minus_baseline": lift,
            "baseline_won": baseline_net > 0.0,
            "shadow_won": shadow_net > 0.0,
            "subset_only_changed": _subset_only_removed(record),
        }
    )
    return out


def _prepare_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "timestamp" in out.columns:
            out.index = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
        else:
            out.index = pd.to_datetime(out.index, utc=True)
    else:
        out.index = pd.to_datetime(out.index, utc=True)
    out = out.sort_index().loc[~out.index.duplicated(keep="last")]
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["close"])
    out["_epoch_seconds"] = [float(ts.timestamp()) for ts in out.index]
    return out


def _position_for_timestamp(frame: pd.DataFrame, timestamp: float) -> int | None:
    matches = frame.index[abs(frame["_epoch_seconds"] - float(timestamp)) < 1e-6]
    if len(matches) == 0:
        return None
    loc = frame.index.get_loc(matches[0])
    return int(loc) if not isinstance(loc, slice) else int(loc.start)


def _directional_net_return(direction: int | None, forward_return: float, fee: float) -> float:
    if direction is None or int(direction) == 0:
        return 0.0
    return float(int(direction)) * float(forward_return) - fee


def _outcome_label(baseline_net: float, shadow_net: float, lift: float, record: Mapping[str, Any]) -> str:
    changed = bool(record.get("selection_changed", False))
    if not changed:
        return "unchanged"
    if lift > 0.0 and baseline_net < 0.0:
        return "avoided_loss"
    if lift > 0.0:
        return "improved_pick"
    if lift < 0.0 and baseline_net > 0.0:
        return "missed_win"
    if lift < 0.0:
        return "worsened_pick"
    return "neutral_changed"


def _unlabeled(record: dict[str, Any], reason: str) -> dict[str, Any]:
    out = dict(record)
    out["outcome_label"] = "unlabeled"
    out["outcome_reason"] = reason
    return out


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    numeric = _optional_float(value)
    if numeric is None:
        return None
    return int(numeric)


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


def _positive_rate(values: Iterable[Any]) -> float | None:
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
    return sum(1 for value in nums if value > 0.0) / len(nums)


def _count_key(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(record.get(key) or "none") for record in records)
    return dict(sorted(counts.items()))


def _group_count(records: list[dict[str, Any]], keys: tuple[str, ...]) -> dict[str, int]:
    counts = Counter("|".join(str(record.get(key) or "none") for key in keys) for record in records)
    return dict(sorted(counts.items()))


def _model_pair_outcomes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (
            str(record.get("baseline_selected_model") or "none"),
            str(record.get("shadow_selected_model") or "none"),
        )
        grouped[key].append(record)
    rows = []
    for key, items in grouped.items():
        rows.append(
            {
                "baseline_selected_model": key[0],
                "shadow_selected_model": key[1],
                "count": len(items),
                "avg_baseline_net_return": _mean(item.get("baseline_net_return") for item in items),
                "avg_shadow_net_return": _mean(item.get("shadow_net_return") for item in items),
                "avg_shadow_minus_baseline": _mean(item.get("shadow_minus_baseline") for item in items),
                "positive_shadow_lift_rate": _positive_rate(item.get("shadow_minus_baseline") for item in items),
                "outcome_labels": dict(sorted(Counter(str(item.get("outcome_label")) for item in items).items())),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["baseline_selected_model"]), str(row["shadow_selected_model"])))


__all__ = [
    "build_shadow_outcome_report",
    "label_shadow_decision_outcomes",
    "load_labeled_shadow_outcomes",
    "render_shadow_outcome_report_markdown",
    "write_labeled_shadow_outcomes",
]
