"""Phase 7M robustness validation for the Phase 7L transition rule.

7L produced a clean BNBUSDT 1h walk-forward candidate by reinterpreting one
split-local high-reversal down confirmation as an up transition. 7M asks whether
that rule is robust or just a single-row diagnostic fit by sweeping windows,
target splits, actions, and assets/timeframes in an offline-only report.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_ft_transition_rule import build_ft_transition_rule_retest_report

_DEFAULT_THRESHOLDS = (0.25, 0.30)
_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_DEFAULT_TARGET_SPLITS = (1, 2, 3, 4)
_DEFAULT_ACTIONS = ("reverse_direction", "suppress")


def build_ft_transition_robust_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    thresholds: Sequence[float] = _DEFAULT_THRESHOLDS,
    split_count: int = 4,
    target_split_indices: Sequence[int] = _DEFAULT_TARGET_SPLITS,
    actions: Sequence[str] = _DEFAULT_ACTIONS,
    transition_directions: Sequence[str] = ("down",),
    window_size: int = 360,
    step_size: int = 180,
    include_full_window: bool = True,
    min_ready_rate: float = 0.60,
    min_non_full_ready_rate: float = 0.50,
    min_applied_support: int = 2,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
    gate_min_context_score: float = 0.70,
    gate_max_risk_score: float = 0.72,
    gate_max_conflict_count: int = 1,
    min_reversal_penalty: float = 0.60,
    min_transition_context_score: float = 0.70,
) -> dict[str, Any]:
    """Run 7L transition rule robustness checks over windows/splits/actions."""
    windows = build_ft_transition_window_specs(
        len(ohlcv),
        window_size=int(window_size),
        step_size=int(step_size),
        include_full_window=bool(include_full_window),
    )
    variants: list[dict[str, Any]] = []
    for window in windows:
        w_analysis = analysis_df.iloc[int(window["start_pos"]): int(window["end_pos"])].copy()
        w_context = context_df.iloc[int(window["start_pos"]): int(window["end_pos"])].copy()
        w_states = state_df.iloc[int(window["start_pos"]): int(window["end_pos"])].copy()
        w_ohlcv = ohlcv.iloc[int(window["start_pos"]): int(window["end_pos"])].copy()
        if len(w_ohlcv) < max(horizons) + int(split_count):
            continue
        for threshold in thresholds:
            for target_split in target_split_indices:
                for action in actions:
                    retest = build_ft_transition_rule_retest_report(
                        w_analysis,
                        w_context,
                        w_states,
                        w_ohlcv,
                        asset=asset,
                        timeframe=timeframe,
                        threshold=float(threshold),
                        split_count=int(split_count),
                        horizons=tuple(int(h) for h in horizons),
                        fees_bps=tuple(float(f) for f in fees_bps),
                        min_split_support=int(min_split_support),
                        min_passing_rate=float(min_passing_rate),
                        min_avg_return=float(min_avg_return),
                        max_worst_loss=float(max_worst_loss),
                        gate_min_context_score=float(gate_min_context_score),
                        gate_max_risk_score=float(gate_max_risk_score),
                        gate_max_conflict_count=int(gate_max_conflict_count),
                        target_split_indices=(int(target_split),),
                        transition_directions=tuple(str(value) for value in transition_directions),
                        min_reversal_penalty=float(min_reversal_penalty),
                        min_transition_context_score=float(min_transition_context_score),
                        action=str(action),
                    )
                    variants.append(_variant_row(retest, window=window, target_split=int(target_split), action=str(action)))
    summary = _summary(
        variants,
        asset=asset,
        timeframe=timeframe,
        thresholds=thresholds,
        target_split_indices=target_split_indices,
        actions=actions,
        windows=windows,
        min_ready_rate=float(min_ready_rate),
        min_non_full_ready_rate=float(min_non_full_ready_rate),
        min_applied_support=int(min_applied_support),
    )
    return {
        "phase": "phase_7m_ft_transition_robustness",
        "summary": summary,
        "variants": variants,
    }


def build_ft_transition_multi_asset_robust_report(asset_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine per-asset/timeframe 7M reports."""
    reports = [dict(report) for report in asset_reports]
    summaries = [dict(report.get("summary", {})) for report in reports]
    ready_reports = [summary for summary in summaries if summary.get("robust_ready")]
    reusable_reports = [summary for summary in summaries if summary.get("recommendation") == "candidate_reusable_signature"]
    variants = [row for report in reports for row in report.get("variants", [])]
    return {
        "phase": "phase_7m_ft_transition_multi_asset_robustness",
        "summary": {
            "report_count": len(reports),
            "robust_ready_report_count": len(ready_reports),
            "reusable_signature_report_count": len(reusable_reports),
            "total_variant_count": len(variants),
            "ready_variant_count": sum(1 for row in variants if row.get("ready")),
            "applied_variant_count": sum(1 for row in variants if int(row.get("applied_count") or 0) > 0),
            "assets": sorted({str(summary.get("asset")) for summary in summaries}),
            "recommendation": "candidate_reusable_signature" if reusable_reports and len(reusable_reports) == len(reports) else "hold_off_transition_rule_not_robust",
            "best_report": _best_summary(summaries),
        },
        "reports": reports,
    }


def build_ft_transition_window_specs(
    row_count: int,
    *,
    window_size: int = 360,
    step_size: int = 180,
    include_full_window: bool = True,
) -> list[dict[str, Any]]:
    """Return deterministic full/rolling window specs for robustness checks."""
    total = int(row_count)
    if total <= 0:
        return []
    specs: list[dict[str, Any]] = []
    if include_full_window:
        specs.append({"window_id": "full", "start_pos": 0, "end_pos": total, "row_count": total, "is_full": True})
    size = max(1, min(int(window_size), total))
    step = max(1, int(step_size))
    start = 0
    while start + size <= total:
        specs.append(
            {
                "window_id": f"w{len([s for s in specs if not s.get('is_full')]) + 1}_{start}_{start + size}",
                "start_pos": start,
                "end_pos": start + size,
                "row_count": size,
                "is_full": False,
            }
        )
        start += step
    if specs and specs[-1].get("end_pos") != total and size < total:
        start = total - size
        candidate = {"window_id": f"w_tail_{start}_{total}", "start_pos": start, "end_pos": total, "row_count": size, "is_full": False}
        if not any(spec["start_pos"] == candidate["start_pos"] and spec["end_pos"] == candidate["end_pos"] for spec in specs):
            specs.append(candidate)
    return specs


def render_ft_transition_robust_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7M robustness reports."""
    if report.get("phase") == "phase_7m_ft_transition_multi_asset_robustness":
        return _render_multi(report)
    return _render_single(report)


def _variant_row(report: Mapping[str, Any], *, window: Mapping[str, Any], target_split: int, action: str) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    rule = dict(dict(report.get("transition_rule_report", {})).get("summary", {}))
    applied_rows = list(dict(report.get("transition_rule_report", {})).get("applied_rows", []))
    return {
        "asset": summary.get("asset"),
        "timeframe": summary.get("timeframe"),
        "threshold": summary.get("threshold"),
        "window_id": window.get("window_id"),
        "window_start_pos": window.get("start_pos"),
        "window_end_pos": window.get("end_pos"),
        "window_row_count": window.get("row_count"),
        "is_full_window": bool(window.get("is_full")),
        "target_split": int(target_split),
        "action": str(action),
        "active_total": summary.get("active_total"),
        "applied_count": summary.get("applied_count"),
        "passed_split_count": summary.get("passed_split_count"),
        "split_count": summary.get("split_count"),
        "ready": summary.get("ready"),
        "recommendation": summary.get("recommendation"),
        "avg_split_directional_return": summary.get("avg_split_directional_return"),
        "worst_split_directional_return": summary.get("worst_split_directional_return"),
        "applied_rows": applied_rows,
        "action_distribution": rule.get("action_distribution", {}),
        "active_direction_distribution": rule.get("active_direction_distribution", {}),
        "failure_reasons": _aggregate_failure_reasons(dict(report.get("walkforward_report", {})).get("splits", [])),
    }


def _summary(
    variants: Sequence[Mapping[str, Any]],
    *,
    asset: str | None,
    timeframe: str | None,
    thresholds: Sequence[float],
    target_split_indices: Sequence[int],
    actions: Sequence[str],
    windows: Sequence[Mapping[str, Any]],
    min_ready_rate: float,
    min_non_full_ready_rate: float,
    min_applied_support: int,
) -> dict[str, Any]:
    rows = [dict(row) for row in variants]
    ready = [row for row in rows if row.get("ready")]
    applied = [row for row in rows if int(row.get("applied_count") or 0) > 0]
    non_full = [row for row in rows if not row.get("is_full_window")]
    non_full_ready = [row for row in non_full if row.get("ready")]
    full_ready = [row for row in rows if row.get("is_full_window") and row.get("ready")]
    ready_rate = _rate(len(ready), len(rows)) or 0.0
    non_full_ready_rate = _rate(len(non_full_ready), len(non_full)) or 0.0
    applied_support = sum(int(row.get("applied_count") or 0) for row in applied)
    reusable = bool(
        rows
        and full_ready
        and ready_rate >= min_ready_rate
        and non_full_ready_rate >= min_non_full_ready_rate
        and applied_support >= min_applied_support
    )
    return {
        "asset": asset,
        "timeframe": timeframe,
        "variant_count": len(rows),
        "ready_variant_count": len(ready),
        "applied_variant_count": len(applied),
        "ready_rate": ready_rate,
        "non_full_ready_rate": non_full_ready_rate,
        "full_window_ready_count": len(full_ready),
        "applied_support": applied_support,
        "window_count": len(windows),
        "windows": list(windows),
        "thresholds": sorted({float(value) for value in thresholds}),
        "target_splits": sorted({int(value) for value in target_split_indices}),
        "actions": [str(value) for value in actions],
        "ready_by_target_split": _ready_by(rows, "target_split"),
        "ready_by_action": _ready_by(rows, "action"),
        "ready_by_window": _ready_by(rows, "window_id"),
        "best_variant": _compact(_best_variant(rows)),
        "best_ready_variant": _compact(_best_variant(ready)),
        "robust_ready": reusable,
        "recommendation": "candidate_reusable_signature" if reusable else "hold_off_transition_rule_not_robust",
    }


def _ready_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get(key))].append(row)
    return {
        name: {
            "variant_count": len(values),
            "ready_count": sum(1 for row in values if row.get("ready")),
            "applied_count": sum(int(row.get("applied_count") or 0) for row in values),
            "ready_rate": _rate(sum(1 for row in values if row.get("ready")), len(values)),
        }
        for name, values in sorted(groups.items())
    }


def _best_variant(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            float(row.get("worst_split_directional_return") or -999.0),
            int(row.get("applied_count") or 0),
        ),
        reverse=True,
    )[0]


def _best_summary(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not summaries:
        return None
    best = sorted(
        [dict(row) for row in summaries],
        key=lambda row: (
            bool(row.get("robust_ready")),
            float(row.get("ready_rate") or 0.0),
            float(row.get("non_full_ready_rate") or 0.0),
            int(row.get("applied_support") or 0),
        ),
        reverse=True,
    )[0]
    return {
        "asset": best.get("asset"),
        "timeframe": best.get("timeframe"),
        "ready_rate": best.get("ready_rate"),
        "non_full_ready_rate": best.get("non_full_ready_rate"),
        "applied_support": best.get("applied_support"),
        "recommendation": best.get("recommendation"),
    }


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "threshold": row.get("threshold"),
        "window_id": row.get("window_id"),
        "target_split": row.get("target_split"),
        "action": row.get("action"),
        "active_total": row.get("active_total"),
        "applied_count": row.get("applied_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _aggregate_failure_reasons(splits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for split in splits:
        counter.update(str(reason) for reason in split.get("failure_reasons", []))
    return dict(counter.most_common())


def _render_single(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7M Follow-Through Transition Robustness",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Applied variants: {summary.get('applied_variant_count', 0)}",
        f"- Ready rate: {summary.get('ready_rate')}",
        f"- Non-full ready rate: {summary.get('non_full_ready_rate')}",
        f"- Applied support: {summary.get('applied_support')}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        f"- Best ready variant: {summary.get('best_ready_variant')}",
        "",
        "## Ready by target split",
        "",
    ]
    for key, value in dict(summary.get("ready_by_target_split", {})).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top variants", "", "| Window | Target split | Action | Threshold | Applied | Passed | Avg split dir | Worst split dir | Ready |", "|---|---:|---|---:|---:|---:|---:|---:|---|"])
    for row in sorted(report.get("variants", []), key=lambda item: (bool(item.get("ready")), int(item.get("applied_count") or 0), float(item.get("avg_split_directional_return") or -999.0)), reverse=True)[:20]:
        lines.append(
            "| {window} | {target} | {action} | {thr} | {applied} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                window=row.get("window_id"),
                target=row.get("target_split"),
                action=row.get("action"),
                thr=row.get("threshold"),
                applied=row.get("applied_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_multi(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7M Multi-Asset Transition Robustness",
        "",
        "## Summary",
        "",
        f"- Reports: {summary.get('report_count', 0)}",
        f"- Robust-ready reports: {summary.get('robust_ready_report_count', 0)}",
        f"- Reusable-signature reports: {summary.get('reusable_signature_report_count', 0)}",
        f"- Total variants: {summary.get('total_variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Applied variants: {summary.get('applied_variant_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best report: {summary.get('best_report')}",
        "",
        "## Per report",
        "",
        "| Asset | Timeframe | Variants | Ready | Ready rate | Non-full ready rate | Applied support | Recommendation |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in report.get("reports", []):
        s = dict(item.get("summary", {}))
        lines.append(
            "| {asset} | {tf} | {variants} | {ready} | {rate} | {nfr} | {support} | {rec} |".format(
                asset=s.get("asset"),
                tf=s.get("timeframe"),
                variants=s.get("variant_count"),
                ready=s.get("ready_variant_count"),
                rate=s.get("ready_rate"),
                nfr=s.get("non_full_ready_rate"),
                support=s.get("applied_support"),
                rec=s.get("recommendation"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = [
    "build_ft_transition_multi_asset_robust_report",
    "build_ft_transition_robust_report",
    "build_ft_transition_window_specs",
    "render_ft_transition_robust_markdown",
]
