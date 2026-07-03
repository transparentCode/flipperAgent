"""Phase 8A playbook orchestration gate.

The transition branch ended at 7Z with a diagnostic freeze. 8A consolidates
that posture back into the broader playbook pipeline: base playbook states stay
as the only routeable state-machine output, while transition micro-states remain
metadata-only diagnostics.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import pandas as pd


def build_playbook_orchestration_frame(
    state_df: pd.DataFrame,
    stop_gate_payload: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Attach orchestration posture columns without changing playbook state."""
    frame = state_df.copy()
    gate = _gate_summary(stop_gate_payload)
    posture = _transition_posture(gate)
    runtime_enabled = int(gate.get("runtime_enabled_count") or 0)
    promotion_ready = bool(gate.get("promotion_ready", False))
    decision = str(gate.get("decision") or "not_provided")

    frame["playbook_orchestration_state"] = frame.get("playbook_state")
    frame["playbook_orchestration_routeable"] = frame.get("playbook_state_is_executable", False).astype(bool)
    frame["playbook_orchestration_source"] = "base_playbook_state_machine"
    frame["playbook_orchestration_transition_posture"] = posture
    frame["playbook_orchestration_transition_gate_decision"] = decision
    frame["playbook_orchestration_transition_runtime_enabled"] = runtime_enabled > 0
    frame["playbook_orchestration_transition_promotion_ready"] = promotion_ready
    frame["playbook_orchestration_runtime_action"] = _runtime_action(posture, runtime_enabled, promotion_ready)
    frame["playbook_orchestration_notes"] = _notes(gate)
    return frame


def build_playbook_orchestration_gate_report(
    orchestration_df: pd.DataFrame,
    stop_gate_payload: Mapping[str, Any] | None = None,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Summarize Phase 8A orchestration posture."""
    gate = _gate_summary(stop_gate_payload)
    rows = int(len(orchestration_df))
    routeable = _true_count(orchestration_df.get("playbook_orchestration_routeable"))
    transition_runtime = _true_count(orchestration_df.get("playbook_orchestration_transition_runtime_enabled"))
    return {
        "phase": "phase_8a_playbook_orchestration_gate",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "source": source,
            "row_count": rows,
            "routeable_count": routeable,
            "routeable_rate": _rate(routeable, rows),
            "transition_runtime_enabled_count": transition_runtime,
            "transition_promotion_ready": bool(gate.get("promotion_ready", False)),
            "transition_gate_decision": gate.get("decision"),
            "transition_gate_blockers": list(gate.get("blockers", [])),
            "transition_posture": _transition_posture(gate),
            "runtime_action_distribution": _counts(orchestration_df.get("playbook_orchestration_runtime_action")),
            "orchestration_state_distribution": _counts(orchestration_df.get("playbook_orchestration_state")),
            "base_state_group_distribution": _counts(orchestration_df.get("playbook_state_group")),
            "recommended_next_step": _recommended_next_step(gate),
        },
        "recent_rows": _recent_rows(orchestration_df),
    }


def render_playbook_orchestration_gate_markdown(report: Mapping[str, Any]) -> str:
    """Render the Phase 8A orchestration gate report."""
    if report.get("phase") == "phase_8a_playbook_orchestration_gate_matrix":
        return _render_matrix_markdown(report)
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 8A Playbook Orchestration Gate",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Rows: {summary.get('row_count')}",
        f"- Routeable base-state rows: {summary.get('routeable_count')} ({summary.get('routeable_rate')})",
        f"- Transition runtime-enabled rows: {summary.get('transition_runtime_enabled_count')}",
        f"- Transition promotion-ready: {summary.get('transition_promotion_ready')}",
        f"- Transition gate decision: {summary.get('transition_gate_decision')}",
        f"- Transition blockers: {summary.get('transition_gate_blockers')}",
        f"- Recommended next step: {summary.get('recommended_next_step')}",
        "",
        "## Runtime action distribution",
        "",
    ]
    for name, count in dict(summary.get("runtime_action_distribution", {})).items():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Orchestration state distribution", ""])
    for name, count in dict(summary.get("orchestration_state_distribution", {})).items():
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Recent rows", ""])
    for row in report.get("recent_rows", []):
        lines.append(
            "- {timestamp}: state={state}, routeable={routeable}, action={action}".format(
                timestamp=row.get("timestamp"),
                state=row.get("state"),
                routeable=row.get("routeable"),
                action=row.get("runtime_action"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_matrix_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 8A Playbook Orchestration Gate",
        "",
        f"- Assets: {summary.get('assets')}",
        f"- Variants: {summary.get('variant_count')}",
        f"- Rows: {summary.get('row_count')}",
        f"- Routeable base-state rows: {summary.get('routeable_count')}",
        f"- Transition runtime-enabled rows: {summary.get('transition_runtime_enabled_count')}",
        f"- Transition promotion-ready count: {summary.get('transition_promotion_ready_count')}",
        f"- Transition postures: {summary.get('transition_postures')}",
        f"- Recommended next step: {summary.get('recommended_next_step')}",
        "",
        "## Asset summaries",
        "",
        "| Asset | Rows | Routeable | Transition posture | Runtime enabled | Next step |",
        "|---|---:|---:|---|---:|---|",
    ]
    for row in report.get("asset_summaries", []):
        lines.append(
            "| {asset} | {rows} | {routeable} | {posture} | {runtime} | {next_step} |".format(
                asset=row.get("asset"),
                rows=row.get("row_count"),
                routeable=row.get("routeable_count"),
                posture=row.get("transition_posture"),
                runtime=row.get("transition_runtime_enabled_count"),
                next_step=row.get("recommended_next_step"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _gate_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    if "summary" in payload:
        return dict(payload.get("summary", {}))
    if "phase" in payload and payload.get("phase") == "phase_7z_transition_stop_gate":
        return dict(payload.get("summary", {}))
    return dict(payload.get("matrix_report", {}).get("summary", {}))


def _transition_posture(gate: Mapping[str, Any]) -> str:
    decision = str(gate.get("decision") or "")
    if decision == "freeze_transition_micro_states_diagnostic":
        return "frozen_diagnostic"
    if bool(gate.get("promotion_ready", False)):
        return "promotion_candidate_review_required"
    if gate:
        return "blocked_or_incomplete"
    return "not_attached"


def _runtime_action(posture: str, runtime_enabled: int, promotion_ready: bool) -> str:
    if runtime_enabled > 0:
        return "unsafe_transition_runtime_detected"
    if promotion_ready:
        return "manual_review_before_any_route_change"
    if posture == "frozen_diagnostic":
        return "base_playbook_only_transition_diagnostic"
    return "base_playbook_only_no_transition_gate"


def _notes(gate: Mapping[str, Any]) -> str:
    blockers = list(gate.get("blockers", []))
    if blockers:
        return "transition_blockers=" + ";".join(str(item) for item in blockers)
    if gate:
        return "transition_gate_present"
    return "transition_gate_not_attached"


def _recommended_next_step(gate: Mapping[str, Any]) -> str:
    posture = _transition_posture(gate)
    if posture == "frozen_diagnostic":
        return "resume_base_playbook_orchestration_and_shadow_reporting"
    if posture == "promotion_candidate_review_required":
        return "manual_safety_review_required_before_runtime_change"
    return "attach_latest_transition_stop_gate_before_runtime_review"


def _recent_rows(frame: pd.DataFrame, n: int = 12) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.tail(n).iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("playbook_orchestration_state"),
                "routeable": bool(row.get("playbook_orchestration_routeable", False)),
                "runtime_action": row.get("playbook_orchestration_runtime_action"),
            }
        )
    return rows


def _true_count(series: Any) -> int:
    if series is None:
        return 0
    return int(pd.Series(series).fillna(False).astype(bool).sum())


def _counts(series: Any) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in pd.Series(series).fillna("missing").tolist()).most_common())


def _rate(num: int, den: int) -> float | None:
    return float(num) / float(den) if den else None


__all__ = [
    "build_playbook_orchestration_frame",
    "build_playbook_orchestration_gate_report",
    "render_playbook_orchestration_gate_markdown",
]
