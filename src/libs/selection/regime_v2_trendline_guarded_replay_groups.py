"""Group review for RegimeV2 trendline guarded replay reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class GuardedGroupThresholds:
    min_guarded_samples: int = 5
    min_allow_loss_saved_rate: float = 0.55
    min_allow_net_lift_delta: float = 0.0
    max_veto_loss_saved_rate: float = 0.50
    max_veto_net_lift_delta: float = 0.0


def build_guarded_replay_group_analysis(
    replay_report: Mapping[str, Any],
    *,
    thresholds: GuardedGroupThresholds | None = None,
) -> dict[str, Any]:
    cfg = thresholds or GuardedGroupThresholds()
    grouped = dict(replay_report.get("grouped", {}))
    asset_rows = _classify_rows(grouped.get("asset_timeframe", []), cfg)
    model_rows = _classify_rows(grouped.get("shadow_model", []), cfg)
    risk_rows = _classify_rows(grouped.get("risk_context", []), cfg)
    confidence_rows = _classify_rows(grouped.get("confidence_annotation", []), cfg)
    all_rows = asset_rows + model_rows + risk_rows + confidence_rows
    return {
        "phase": "phase_tl_h21_guarded_replay_group_analysis",
        "summary": {
            "min_guarded_samples": cfg.min_guarded_samples,
            "min_allow_loss_saved_rate": cfg.min_allow_loss_saved_rate,
            "min_allow_net_lift_delta": cfg.min_allow_net_lift_delta,
            "max_veto_loss_saved_rate": cfg.max_veto_loss_saved_rate,
            "max_veto_net_lift_delta": cfg.max_veto_net_lift_delta,
            "allow_candidate_count": sum(1 for row in all_rows if row["group_decision"] == "allow_candidate"),
            "veto_candidate_count": sum(1 for row in all_rows if row["group_decision"] == "veto_candidate"),
            "needs_more_evidence_count": sum(1 for row in all_rows if row["group_decision"] == "needs_more_evidence"),
        },
        "asset_timeframe": asset_rows,
        "shadow_model": model_rows,
        "risk_context": risk_rows,
        "confidence_annotation": confidence_rows,
    }


def render_guarded_replay_group_analysis_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# RegimeV2 Trendline Guarded Replay Group Analysis",
        "",
        "## Asset / Timeframe",
        "",
        "| Group | Guarded | Loss saved rate | Net delta | Decision |",
        "|---|---:|---:|---:|---|",
    ]
    for row in report.get("asset_timeframe", []):
        lines.append(_row_md(row))
    lines.extend([
        "",
        "## Shadow Model",
        "",
        "| Group | Guarded | Loss saved rate | Net delta | Decision |",
        "|---|---:|---:|---:|---|",
    ])
    for row in report.get("shadow_model", []):
        lines.append(_row_md(row))
    lines.extend([
        "",
        "## Risk Context",
        "",
        "| Group | Guarded | Loss saved rate | Net delta | Decision |",
        "|---|---:|---:|---:|---|",
    ])
    for row in report.get("risk_context", []):
        lines.append(_row_md(row))
    lines.append("")
    return "\n".join(lines)


def _classify_rows(rows: Any, thresholds: GuardedGroupThresholds) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        item = dict(row)
        item["group_decision"] = _decision(item, thresholds)
        item["group_reason"] = _reason(item, thresholds, item["group_decision"])
        out.append(item)
    return sorted(out, key=lambda row: (_decision_rank(row["group_decision"]), -(row.get("net_lift_delta") or 0.0), str(row.get("group"))))


def _decision(row: Mapping[str, Any], thresholds: GuardedGroupThresholds) -> str:
    guarded = int(row.get("guarded_count") or 0)
    loss_rate = row.get("loss_saved_rate")
    net_delta = float(row.get("net_lift_delta") or 0.0)
    if guarded >= thresholds.min_guarded_samples and loss_rate is not None:
        if float(loss_rate) >= thresholds.min_allow_loss_saved_rate and net_delta >= thresholds.min_allow_net_lift_delta:
            return "allow_candidate"
        if float(loss_rate) <= thresholds.max_veto_loss_saved_rate or net_delta < thresholds.max_veto_net_lift_delta:
            return "veto_candidate"
    return "needs_more_evidence"


def _reason(row: Mapping[str, Any], thresholds: GuardedGroupThresholds, decision: str) -> str:
    guarded = int(row.get("guarded_count") or 0)
    loss_rate = row.get("loss_saved_rate")
    if decision == "allow_candidate":
        return "passes guarded sample, loss-saved-rate, and net-delta checks"
    if decision == "veto_candidate":
        return "fails loss-saved-rate or net-delta check with enough guarded samples"
    missing = max(0, thresholds.min_guarded_samples - guarded)
    if missing > 0:
        return f"collect {missing} more guarded rows"
    if loss_rate is None:
        return "missing loss-saved-rate"
    return "mixed evidence; keep in shadow analysis"


def _decision_rank(value: str) -> int:
    return {"allow_candidate": 0, "veto_candidate": 1, "needs_more_evidence": 2}.get(value, 3)


def _row_md(row: Mapping[str, Any]) -> str:
    return "| {group} | {guarded} | {loss_rate} | {delta} | {decision} |".format(
        group=row.get("group"),
        guarded=row.get("guarded_count"),
        loss_rate=row.get("loss_saved_rate"),
        delta=row.get("net_lift_delta"),
        decision=row.get("group_decision"),
    )


__all__ = [
    "GuardedGroupThresholds",
    "build_guarded_replay_group_analysis",
    "render_guarded_replay_group_analysis_markdown",
]
